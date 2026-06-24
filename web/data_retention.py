"""W6 — Data Retention: auto-purge old data + manual triggers.

Purges: sessions, api_usage_log, audit.jsonl based on configurable
retention periods stored in system_config.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("aimodeljudge.data_retention")

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"

_STATE_DB = _BASE / "state.db"
_AUDIT_PATH = _BASE / "logs" / "audit.jsonl"


def _get_retention_config() -> dict[str, int]:
    """Read retention config from system_config, falling back to defaults."""
    from app_config import get_config

    defaults = {"retention_sessions_days": 90, "retention_usage_days": 90, "retention_audit_days": 365}
    result: dict[str, int] = {}
    for key, default in defaults.items():
        try:
            result[key] = int(get_config(key) or str(default))
        except (ValueError, TypeError):
            result[key] = default
    return result


def purge_old_data() -> dict:
    """Delete data older than configured retention periods. Returns stats."""
    config = _get_retention_config()
    stats: dict = {"sessions": 0, "messages_orphaned": 0, "api_usage": 0, "audit_trimmed": False}

    now = time.time()

    # ── 1. Purge old sessions from AIModelJudge state.db ──
    cutoff_sessions = now - config["retention_sessions_days"] * 86400
    conn = sqlite3.connect(str(_STATE_DB))
    try:
        cur = conn.execute("DELETE FROM sessions WHERE started_at < ?", (cutoff_sessions,))
        stats["sessions"] = cur.rowcount
        # Clean orphaned messages (sessions that no longer exist)
        cur = conn.execute(
            "DELETE FROM messages WHERE session_id NOT IN (SELECT id FROM sessions)"
        )
        stats["messages_orphaned"] = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    # ── 2. Purge old api_usage_log ──
    retention_days = config["retention_usage_days"]
    conn = sqlite3.connect(str(_STATE_DB))
    try:
        cur = conn.execute(
            "DELETE FROM api_usage_log WHERE timestamp < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        stats["api_usage"] = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    # ── 3. Trim audit.jsonl ──
    stats["audit_trimmed"] = _trim_audit_log(config["retention_audit_days"])

    log.info("Data purge complete: %s", stats)
    return stats


def _trim_audit_log(retention_days: int) -> bool:
    """Trim audit.jsonl to entries within retention period."""
    if not _AUDIT_PATH.exists():
        return False

    cutoff = time.time() - retention_days * 86400

    try:
        entries: list[str] = []
        kept = 0
        trimmed = 0
        with open(_AUDIT_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("ts", "")
                    # Parse ISO timestamp or fallback to keeping entry
                    if ts:
                        try:
                            et = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                            if et < cutoff:
                                trimmed += 1
                                continue
                        except (ValueError, OSError):
                            pass  # unparseable timestamp — keep
                    kept += 1
                    entries.append(line)
                except json.JSONDecodeError:
                    entries.append(line)  # preserve corrupted lines

        if trimmed == 0:
            return False

        # Backup before overwriting
        backup_path = _AUDIT_PATH.with_suffix(".jsonl.bak")
        shutil.copy2(_AUDIT_PATH, backup_path)

        with open(_AUDIT_PATH, "w") as f:
            for entry in entries:
                f.write(entry + "\n")

        log.info("Audit log trimmed: %d removed, %d kept", trimmed, kept)
        return True
    except Exception:
        log.warning("Failed to trim audit log", exc_info=True)
        return False
