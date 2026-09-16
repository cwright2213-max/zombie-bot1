"""Persistent storage - FORCE /data - never wipes"""
import os, json, logging, sqlite3, time
from pathlib import Path

logger = logging.getLogger("zombie.storage")

# FORCE /data - always try /data first, this is where Railway volume mounts
# Even if folder doesn't exist, we create it - Railway will make it persistent if volume configured
DB_PATH = Path("/data/players.db")
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"[STORAGE] FORCED DB_PATH = {DB_PATH} exists={DB_PATH.exists()} parent={DB_PATH.parent} - volume mounted={Path('/data').exists()}")
except Exception as e:
    # Fallback if /data not writable (shouldn't happen)
    DB_PATH = Path("data/players.db")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"[STORAGE] Fallback to {DB_PATH} because /data failed: {e}")

def _get_conn():
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
    conn.commit()
    return conn

def load_all_players():
    try:
        if not DB_PATH.exists():
            print(f"[STORAGE] No DB file yet at {DB_PATH}, starting fresh - first boot")
            return {}
        conn = _get_conn()
        cur = conn.execute("SELECT user_id, data FROM players")
        result = {}
        for uid, jdata in cur.fetchall():
            try:
                result[uid] = json.loads(jdata)
            except:
                pass
        conn.close()
        print(f"[STORAGE] Loaded {len(result)} players from {DB_PATH} - THIS IS PERSISTENT")
        return result
    except Exception as e:
        print(f"[STORAGE] Load failed: {e}")
        return {}

def save_player(user_id, player_dict):
    for attempt in range(5):
        try:
            conn = _get_conn()
            conn.execute("INSERT OR REPLACE INTO players (user_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (str(user_id), json.dumps(player_dict)))
            conn.commit()
            conn.close()
            return
        except Exception as e:
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(0.2*(attempt+1))
                continue
            print(f"[STORAGE] Save failed for {user_id}: {e}")
            try:
                conn.close()
            except:
                pass
            return

# --- BOT ADMIN SYSTEM ---
def _get_admin_conn():
    return _get_conn()

def get_bot_admins():
    """Returns set of user_id strings who are bot admins"""
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id TEXT PRIMARY KEY,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur = conn.execute("SELECT user_id FROM bot_admins")
        admins = {row[0] for row in cur.fetchall()}
        conn.close()
        return admins
    except Exception as e:
        print(f"[ADMIN] get_bot_admins failed: {e}")
        return set()

def is_bot_admin(user_id):
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id TEXT PRIMARY KEY,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur = conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (str(user_id),))
        exists = cur.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        print(f"[ADMIN] is_bot_admin check failed: {e}")
        return False

def add_bot_admin(user_id, added_by="system"):
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id TEXT PRIMARY KEY,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT OR REPLACE INTO bot_admins (user_id, added_by, added_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (str(user_id), str(added_by)))
        conn.commit()
        conn.close()
        print(f"[ADMIN] Added bot admin {user_id} by {added_by}")
        return True
    except Exception as e:
        print(f"[ADMIN] add_bot_admin failed: {e}")
        return False

def remove_bot_admin(user_id):
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM bot_admins WHERE user_id=?", (str(user_id),))
        conn.commit()
        conn.close()
        print(f"[ADMIN] Removed bot admin {user_id}")
        return True
    except Exception as e:
        print(f"[ADMIN] remove failed: {e}")
        return False

def get_db():
    return _get_conn()

SAVE_FILE = DB_PATH
USE_POSTGRES = False
DATABASE_URL = ""
