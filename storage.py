"""Persistent storage - VOLUME FIX - never wipes"""
import os, json, logging, sqlite3, time
from pathlib import Path

logger = logging.getLogger("zombie.storage")

# Railway volume mounts at /data - if it exists, use it
if Path("/data").exists():
    DB_PATH = Path("/data/players.db")
else:
    DB_PATH = Path("data/players.db")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
print(f"[STORAGE] DB_PATH = {DB_PATH} exists={DB_PATH.exists()} parent={DB_PATH.parent}")

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
            print(f"[STORAGE] No DB file yet at {DB_PATH}, starting fresh")
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
        print(f"[STORAGE] Loaded {len(result)} players from {DB_PATH}")
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

def get_db():
    return _get_conn()

SAVE_FILE = DB_PATH
# Compat for old main.py expecting these
USE_POSTGRES = False
DATABASE_URL = ""
