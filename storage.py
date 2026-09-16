"""STORAGE V6 - POSTGRES ONLY - CONSTANT INSTANT SAVE - ZERO LOSS"""
import os, json, time, threading
print("[STORAGE] Loading V6 Postgres Constant Save")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith("postgres"))
print(f"[STORAGE] USE_POSTGRES={USE_POSTGRES} DATABASE_URL set={bool(DATABASE_URL)}")

_pg_conn = None
_pg_lock = threading.Lock()

def _get_pg_conn():
    global _pg_conn
    with _pg_lock:
        try:
            if _pg_conn:
                try:
                    with _pg_conn.cursor() as cur:
                        cur.execute("SELECT 1")
                    return _pg_conn
                except:
                    try: _pg_conn.close()
                    except: pass
                    _pg_conn = None
            import psycopg2
            sslmode = 'disable' if 'railway.internal' in DATABASE_URL else ('require' if 'railway' in DATABASE_URL else 'prefer')
            _pg_conn = psycopg2.connect(DATABASE_URL, sslmode=sslmode)
            _pg_conn.autocommit = True
            with _pg_conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS players (user_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                cur.execute("CREATE TABLE IF NOT EXISTS bot_admins (user_id TEXT PRIMARY KEY, added_by TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            print("[STORAGE] Postgres connected + tables ready - PERSISTENT")
            return _pg_conn
        except Exception as e:
            print(f"[STORAGE] PG connect failed: {e}")
            _pg_conn = None
            raise

def load_all_players():
    try:
        if not USE_POSTGRES:
            print("[STORAGE] ERROR: No DATABASE_URL - data would be lost! Add Postgres")
            return {}
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, data FROM players")
            rows = cur.fetchall()
        result = {}
        for uid, jdata in rows:
            try: result[uid] = json.loads(jdata) if isinstance(jdata, str) else jdata
            except: pass
        print(f"[STORAGE] POSTGRES Loaded {len(result)} players - PERSISTENT")
        return result
    except Exception as e:
        print(f"[STORAGE] Load failed: {e}")
        return {}

def save_player(user_id, player_dict):
    """CONSTANT SAVE - called after EVERY action - instant Postgres write"""
    for attempt in range(5):
        try:
            if not USE_POSTGRES:
                print("[STORAGE] CRITICAL: No Postgres!")
                return False
            conn = _get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("INSERT INTO players (user_id, data, updated_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO UPDATE SET data=EXCLUDED.data, updated_at=CURRENT_TIMESTAMP", (str(user_id), json.dumps(player_dict)))
            return True
        except Exception as e:
            if attempt < 4:
                time.sleep(0.1*(attempt+1))
                with _pg_lock:
                    global _pg_conn
                    _pg_conn = None
                continue
            print(f"[STORAGE] Save FAILED {user_id}: {e}")
            return False

def get_bot_admins():
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM bot_admins")
            return {r[0] for r in cur.fetchall()}
    except: return set()

def is_bot_admin(uid):
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM bot_admins WHERE user_id=%s", (str(uid),))
            return cur.fetchone() is not None
    except: return False

def add_bot_admin(uid, added_by="system"):
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO bot_admins (user_id, added_by) VALUES (%s,%s) ON CONFLICT (user_id) DO UPDATE SET added_by=EXCLUDED.added_by", (str(uid), str(added_by)))
        return True
    except: return False

def remove_bot_admin(uid):
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bot_admins WHERE user_id=%s", (str(uid),))
        return True
    except: return False

# Compat for old code that imported these
from pathlib import Path
DB_PATH = Path("/data/players.db")
SAVE_FILE = DB_PATH
def get_db(): return _get_pg_conn() if USE_POSTGRES else None
