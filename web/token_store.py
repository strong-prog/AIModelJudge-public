"""Token blacklist + API key scopes in SQLite."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"
_STATE_DB = _BASE / "state.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_STATE_DB))
    conn.row_factory = sqlite3.Row
    return conn


# ── Token Blacklist ──

def is_blacklisted(jti: str) -> bool:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM token_blacklist WHERE jti = ?", (jti,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def blacklist_token(jti: str, user_id: str, expires_at: float) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO token_blacklist (jti, user_id, revoked_at, expires_at) VALUES (?, ?, ?, ?)",
            (jti, user_id, time.time(), expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def cleanup_expired_blacklist() -> int:
    conn = _get_conn()
    try:
        now = time.time()
        cursor = conn.execute(
            "DELETE FROM token_blacklist WHERE expires_at < ?", (now,)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# ── Scoped API Keys ──

def get_api_key_scope(api_key: str) -> dict | None:
    """Returns {user_id, scope, name} or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT user_id, scope, name FROM scoped_api_keys WHERE api_key = ?",
            (api_key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_api_key_scope(api_key: str, user_id: str, scope: str, name: str) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO scoped_api_keys (api_key, user_id, scope, name, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (api_key, user_id, scope, name),
        )
        conn.commit()
    finally:
        conn.close()


def list_scoped_keys(user_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT api_key, scope, name, created_at FROM scoped_api_keys WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_scoped_key(api_key: str) -> bool:
    conn = _get_conn()
    try:
        cursor = conn.execute("DELETE FROM scoped_api_keys WHERE api_key = ?", (api_key,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
