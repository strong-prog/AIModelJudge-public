"""System configuration — SQLite key-value store."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_STATE_DB = Path.home() / ".hermes-aimodeljudge" / "state.db"

_DEFAULTS: dict[str, str] = {
    "maintenance_mode": "false",
    "welcome_message": "",
    "max_free_users": "0",
    "feature_flags": "{}",
}


def _get_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(_STATE_DB))


def get_config(key: str) -> str:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM system_config WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else _DEFAULTS.get(key, "")
    finally:
        conn.close()


def set_config(key: str, value: str) -> None:
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_config() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT key, value, updated_at FROM system_config ORDER BY key"
        ).fetchall()
        stored = {r[0]: {"key": r[0], "value": r[1], "updated_at": r[2]} for r in rows}
    finally:
        conn.close()
    # Merge defaults for keys not yet stored
    for key, default_value in _DEFAULTS.items():
        if key not in stored:
            stored[key] = {"key": key, "value": default_value, "updated_at": ""}
    return sorted(stored.values(), key=lambda x: x["key"])


def is_maintenance_mode() -> bool:
    return get_config("maintenance_mode").lower() == "true"
