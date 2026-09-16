"""Persistent storage - POSTGRES + VOLUME HYBRID - works on Trial"""
import os, json, logging, sqlite3, time
from pathlib import Path

logger = logging.getLogger("zombie.storage")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith("postgres"))

print(f"[STORAGE] USE_POSTGRES={USE_POSTGRES} DATABASE_URL set={bool(DATABASE_URL)}")

# --- POSTGRES MODE (100% persistent, works on Trial if you add Postgres service) ---
_pg_conn = None
def _get_pg_conn():
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, sslmode='require' if 'railway' in DATABASE_URL or 'supabase' in DATABASE_URL or 'neon' in DATABASE_URL else 'prefer')
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id TEXT PRIMARY KEY,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.commit()
    return conn

# --- SQLITE MODE (for volume) ---
DB_PATH = Path("/data/players.db")
# Try to detect if /data is a REAL volume (has .railway or is mount) vs fake folder we created
# On Railway, real volumes will have data persist. We can't detect, but we try both
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except:
    DB_PATH = Path("data/players.db")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

print(f"[STORAGE] SQLITE fallback DB_PATH={DB_PATH} exists={DB_PATH.exists()}")

def _get_sqlite_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id TEXT PRIMARY KEY,
            added_by TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

def _get_conn():
    if USE_POSTGRES:
        return _get_pg_conn()
    else:
        return _get_sqlite_conn()

def load_all_players():
    try:
        if USE_POSTGRES:
            import psycopg2
            conn = _get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, data FROM players")
                rows = cur.fetchall()
            conn.close()
            result = {}
            for uid, jdata in rows:
                try:
                    result[uid] = json.loads(jdata) if isinstance(jdata, str) else jdata
                except:
                    pass
            print(f"[STORAGE] POSTGRES Loaded {len(result)} players - PERSISTENT")
            return result
        else:
            if not DB_PATH.exists():
                print(f"[STORAGE] No DB file yet at {DB_PATH}, starting fresh - FIRST BOOT ON THIS VOLUME")
                return {}
            conn = _get_sqlite_conn()
            cur = conn.execute("SELECT user_id, data FROM players")
            result = {}
            for uid, jdata in cur.fetchall():
                try:
                    result[uid] = json.loads(jdata)
                except:
                    pass
            conn.close()
            print(f"[STORAGE] SQLITE Loaded {len(result)} players from {DB_PATH} - {'PERSISTENT IF VOLUME MOUNTED ELSE EPHEMERAL'}")
            return result
    except Exception as e:
        print(f"[STORAGE] Load failed: {e}")
        import traceback
        traceback.print_exc()
        return {}

def save_player(user_id, player_dict):
    for attempt in range(5):
        try:
            if USE_POSTGRES:
                import psycopg2
                conn = _get_pg_conn()
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO players (user_id, data, updated_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP", (str(user_id), json.dumps(player_dict)))
                conn.commit()
                conn.close()
                return
            else:
                conn = _get_sqlite_conn()
                conn.execute("INSERT OR REPLACE INTO players (user_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (str(user_id), json.dumps(player_dict)))
                conn.commit()
                conn.close()
                return
        except Exception as e:
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(0.2*(attempt+1))
                continue
            print(f"[STORAGE] Save failed for {user_id}: {e}")
            import traceback
            traceback.print_exc()
            return

# --- BOT ADMIN SYSTEM ---
def get_bot_admins():
    try:
        if USE_POSTGRES:
            import psycopg2
            conn = _get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM bot_admins")
                admins = {row[0] for row in cur.fetchall()}
            conn.close()
            return admins
        else:
            conn = _get_sqlite_conn()
            cur = conn.execute("SELECT user_id FROM bot_admins")
            admins = {row[0] for row in cur.fetchall()}
            conn.close()
            return admins
    except Exception as e:
        print(f"[ADMIN] get_bot_admins failed: {e}")
        return set()

def is_bot_admin(user_id):
    try:
        if USE_POSTGRES:
            import psycopg2
            conn = _get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM bot_admins WHERE user_id=%s", (str(user_id),))
                exists = cur.fetchone() is not None
            conn.close()
            return exists
        else:
            conn = _get_sqlite_conn()
            cur = conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (str(user_id),))
            exists = cur.fetchone() is not None
            conn.close()
            return exists
    except Exception as e:
        print(f"[ADMIN] is_bot_admin check failed: {e}")
        return False

def add_bot_admin(user_id, added_by="system"):
    try:
        if USE_POSTGRES:
            import psycopg2
            conn = _get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("INSERT INTO bot_admins (user_id, added_by, added_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO UPDATE SET added_by=EXCLUDED.added_by", (str(user_id), str(added_by)))
            conn.commit()
            conn.close()
            return True
        else:
            conn = _get_sqlite_conn()
            conn.execute("INSERT OR REPLACE INTO bot_admins (user_id, added_by, added_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (str(user_id), str(added_by)))
            conn.commit()
            conn.close()
            return True
    except Exception as e:
        print(f"[ADMIN] add_bot_admin failed: {e}")
        return False

def remove_bot_admin(user_id):
    try:
        if USE_POSTGRES:
            import psycopg2
            conn = _get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bot_admins WHERE user_id=%s", (str(user_id),))
            conn.commit()
            conn.close()
            return True
        else:
            conn = _get_sqlite_conn()
            conn.execute("DELETE FROM bot_admins WHERE user_id=?", (str(user_id),))
            conn.commit()
            conn.close()
            return True
    except Exception as e:
        print(f"[ADMIN] remove failed: {e}")
        return False

def get_db():
    return _get_conn()

SAVE_FILE = DB_PATH
