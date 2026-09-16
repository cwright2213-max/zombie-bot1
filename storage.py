"""STORAGE V6 - POSTGRES CONSTANT SAVE - V6 FULL RESTORED"""
import os, json
from pathlib import Path

DB_PATH = Path("/data/players.db")
SAVE_FILE = Path("/data/players.json")

# Try to import psycopg2
try:
    import psycopg2
    USE_POSTGRES = bool(os.getenv("DATABASE_URL"))
    print(f"[STORAGE] Loading V6 Postgres Constant Save")
    print(f"[STORAGE] USE_POSTGRES={USE_POSTGRES} DATABASE_URL set={bool(os.getenv('DATABASE_URL'))}")
except ImportError:
    USE_POSTGRES = False
    print("[STORAGE] psycopg2 not installed - falling back to file")

def get_conn():
    if not USE_POSTGRES:
        return None
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def init_postgres():
    if not USE_POSTGRES:
        return
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id TEXT PRIMARY KEY,
                data JSONB NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id TEXT PRIMARY KEY,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT NOW()
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[STORAGE] Postgres connected + tables ready - PERSISTENT")
    except Exception as e:
        print(f"[STORAGE] Postgres init error: {e}")

def load_all_players():
    if USE_POSTGRES:
        try:
            init_postgres()
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT user_id, data FROM players;")
            rows = cur.fetchall()
            result = {r[0]: r[1] for r in rows}
            cur.close()
            conn.close()
            print(f"[STORAGE] Using POSTGRES - CONSTANT SAVE ENABLED - V6 FULL RESTORED")
            print(f"[STORAGE] POSTGRES Loaded {len(result)} players - PERSISTENT")
            return result
        except Exception as e:
            print(f"[STORAGE] Postgres load error: {e} - falling back to file")

    # Fallback file
    if SAVE_FILE.exists():
        try:
            data = json.loads(SAVE_FILE.read_text())
            print(f"[STORAGE] Loaded {len(data)} players from file")
            return data
        except:
            return {}
    return {}

def save_player(user_id: str, data: dict):
    if USE_POSTGRES:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO players (user_id, data) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data;
            """, (str(user_id), json.dumps(data)))
            conn.commit()
            cur.close()
            conn.close()
            return
        except Exception as e:
            print(f"[STORAGE] Postgres save error {user_id}: {e}")

    # Fallback file
    try:
        all_data = {}
        if SAVE_FILE.exists():
            all_data = json.loads(SAVE_FILE.read_text())
        all_data[str(user_id)] = data
        SAVE_FILE.write_text(json.dumps(all_data))
    except Exception as e:
        print(f"[STORAGE] File save error: {e}")

def get_bot_admins():
    if USE_POSTGRES:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM bot_admins;")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [r[0] for r in rows]
        except:
            return []
    return []

def is_bot_admin(user_id: int) -> bool:
    return str(user_id) in get_bot_admins()

def add_bot_admin(user_id: int, added_by: str = "system") -> bool:
    if USE_POSTGRES:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("INSERT INTO bot_admins (user_id, added_by) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (str(user_id), str(added_by)))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Add admin error: {e}")
            return False
    return False

def remove_bot_admin(user_id: int) -> bool:
    if USE_POSTGRES:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM bot_admins WHERE user_id = %s;", (str(user_id),))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except:
            return False
    return False

init_postgres()
