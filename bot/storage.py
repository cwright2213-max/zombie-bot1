import sqlite3
import json
import shutil
import logging
from pathlib import Path

logger = logging.getLogger("zombie.storage")

DB_PATH = Path("data/players.db")
BACKUP_PATH = Path("data/players.db.bak")
LEGACY_JSON = Path("zombie_saves.json")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    return conn

def validate_player_data(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "not a dict"
    for k in ["health", "zone_name", "weapon_name"]:
        if k not in data:
            return False, f"missing {k}"
    return True, "ok"

def save_player(player_id: str, data: dict) -> bool:
    ok, reason = validate_player_data(data)
    if not ok:
        logger.error(f"Rejecting save for {player_id}: {reason} - quarantining")
        q_path = Path(f"data/quarantine_{player_id}.json")
        try:
            q_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except:
            pass
        return False
    try:
        if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
            try:
                shutil.copy2(DB_PATH, BACKUP_PATH)
            except Exception as e:
                logger.warning(f"Backup failed: {e}")
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO players (id, data) VALUES (?, ?)", (str(player_id), json.dumps(data)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.exception(f"Save failed for {player_id}: {e}")
        return False

def load_all_players() -> dict:
    if not DB_PATH.exists() and LEGACY_JSON.exists():
        try:
            logger.info("Migrating legacy zombie_saves.json to SQLite")
            legacy = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
            if isinstance(legacy, dict):
                conn = get_db()
                for pid, pdata in legacy.items():
                    if isinstance(pdata, dict):
                        conn.execute("INSERT OR REPLACE INTO players VALUES (?, ?)", (str(pid), json.dumps(pdata)))
                conn.commit()
                conn.close()
                LEGACY_JSON.rename(LEGACY_JSON.with_suffix(".json.migrated.bak"))
        except Exception as e:
            logger.exception(f"Legacy migration failed: {e}")

    try:
        conn = get_db()
        rows = conn.execute("SELECT id, data FROM players").fetchall()
        conn.close()
        players = {}
        bad = 0
        for pid, raw in rows:
            try:
                data = json.loads(raw)
                players[pid] = data
            except Exception as e:
                logger.error(f"Corrupt DB record {pid} - skipping only this player: {e}")
                bad += 1
                continue
        if bad:
            logger.warning(f"Loaded {len(players)} good, quarantined {bad} bad")
        return players
    except Exception as e:
        logger.exception(f"DB load failed: {e}, trying backup")
        if BACKUP_PATH.exists():
            try:
                shutil.copy2(BACKUP_PATH, DB_PATH)
                return load_all_players()
            except Exception as e2:
                logger.exception(f"Backup restore failed: {e2}")
        return {}
