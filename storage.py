"""Persistent PostgreSQL storage for the zombie game.

PostgreSQL is the single source of truth.  A database failure is never
reported as an empty save set, because that can make a deployment appear to
have wiped every player.
"""
import json
import os
import threading
import time
from typing import Dict, Any

print("[STORAGE] Loading PostgreSQL persistent storage")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

# Kept for compatibility with the existing main.py imports.
DB_PATH = DATABASE_URL
SAVE_FILE = ""

_pg_conn = None
_pg_lock = threading.Lock()


def _close_pg_conn():
    global _pg_conn
    with _pg_lock:
        if _pg_conn is not None:
            try:
                _pg_conn.close()
            except Exception as e:
                print(f"[STORAGE] Connection close warning: {e}")
            _pg_conn = None


def _connect_pg():
    if not USE_POSTGRES:
        raise RuntimeError(
            "DATABASE_URL/POSTGRES_URL is missing or is not a PostgreSQL URL. "
            "Refusing to start without persistent player storage."
        )

    import psycopg2

    sslmode = (
        "disable" if "railway.internal" in DATABASE_URL
        else "require" if "railway" in DATABASE_URL
        else "prefer"
    )
    conn = psycopg2.connect(DATABASE_URL, sslmode=sslmode, connect_timeout=10)
    conn.autocommit = False

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                user_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id TEXT PRIMARY KEY,
                added_by TEXT,
                added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    conn.commit()
    return conn


def _get_pg_conn():
    global _pg_conn
    with _pg_lock:
        if _pg_conn is not None:
            try:
                with _pg_conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return _pg_conn
            except Exception as e:
                print(f"[STORAGE] Existing PostgreSQL connection unusable: {e}")
                try:
                    _pg_conn.close()
                except Exception:
                    pass
                _pg_conn = None

        _pg_conn = _connect_pg()
        print("[STORAGE] PostgreSQL connected; schema verified")
        return _pg_conn


def verify_storage():
    """Fail-fast startup check. Never replace a DB failure with empty saves."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM players")
            count = cur.fetchone()[0]
        conn.commit()
        print(f"[STORAGE] Persistent database verified: {count} player(s)")
        return count
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        _close_pg_conn()
        raise


def load_all_players() -> Dict[str, Dict[str, Any]]:
    """Load every player. Database errors are raised, never converted to {}."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, data FROM players ORDER BY user_id")
            rows = cur.fetchall()
        conn.commit()

        result = {}
        for uid, jdata in rows:
            try:
                data = json.loads(jdata) if isinstance(jdata, str) else jdata
            except Exception as e:
                raise RuntimeError(f"Invalid JSON for player {uid}: {e}") from e
            if not isinstance(data, dict):
                raise RuntimeError(f"Stored data for player {uid} is not an object")
            result[str(uid)] = data

        print(f"[STORAGE] Loaded {len(result)} players from PostgreSQL")
        return result
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        _close_pg_conn()
        raise


def save_player(user_id, player_dict) -> bool:
    """Persist one player immediately. Returns True only after commit succeeds."""
    payload = json.dumps(player_dict, separators=(",", ":"), ensure_ascii=False)

    for attempt in range(5):
        try:
            conn = _get_pg_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO players (user_id, data, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        data = EXCLUDED.data,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (str(user_id), payload),
                )
            conn.commit()
            return True
        except Exception as e:
            try:
                if _pg_conn is not None:
                    _pg_conn.rollback()
            except Exception:
                pass
            _close_pg_conn()
            if attempt == 4:
                print(f"[STORAGE] Save FAILED {user_id}: {e}")
                return False
            time.sleep(0.1 * (attempt + 1))
    return False


def get_bot_admins():
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM bot_admins ORDER BY user_id")
            rows = cur.fetchall()
        conn.commit()
        return {str(row[0]) for row in rows}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        _close_pg_conn()
        raise


def is_bot_admin(user_id) -> bool:
    return str(user_id) in get_bot_admins()


def add_bot_admin(user_id, added_by=None) -> bool:
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bot_admins (user_id, added_by)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (str(user_id), str(added_by) if added_by is not None else None),
            )
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        _close_pg_conn()
        raise


def remove_bot_admin(user_id) -> bool:
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bot_admins WHERE user_id = %s", (str(user_id),))
            changed = cur.rowcount > 0
        conn.commit()
        return changed
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        _close_pg_conn()
        raise
