"""Persistent player storage - FIX for Railway volume"""
from __future__ import annotations
import json, os, sqlite3, logging
from pathlib import Path
from typing import Dict, Any

# Railway persistent volume should be mounted at /data
# Fallback to ./data for local/Replit
if Path("/data").exists():
    DB_PATH = Path("/data/players.db")
else:
    DB_PATH = Path("data/players.db")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

def load_all_players() -> Dict[str, Any]:
    """Load all players from SQLite - survives deploys if /data volume exists"""
    try:
        conn = _get_conn()
        cur = conn.execute("SELECT user_id, data FROM players")
        result = {}
        for uid, jdata in cur.fetchall():
            try:
                result[uid] = json.loads(jdata)
            except:
                logging.warning(f"Corrupt data for {uid}, skipping")
        conn.close()
        print(f"[STORAGE] Loaded {len(result)} players from {DB_PATH}")
        return result
    except Exception as e:
        print(f"[STORAGE] Load failed: {e}")
        return {}

def save_player(user_id: str, player_dict: dict):
    """Save single player immediately"""
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO players (user_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (str(user_id), json.dumps(player_dict))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[STORAGE] Save failed for {user_id}: {e}")
        logging.exception("save failed")

# Legacy compatibility - if you had old SAVE_FILE json
SAVE_FILE = DB_PATH
