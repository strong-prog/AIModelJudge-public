"""Audit logging for hermes-local-agent — all actions written to JSONL."""

from __future__ import annotations

import json
import time
from pathlib import Path

from config import get_agent_home

_AUDIT_PATH = get_agent_home() / "audit.jsonl"


def log_action(tool: str, params: dict, *, status: str, data: str = "", error: str = "", duration_ms: float = 0) -> None:
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": tool,
        "params": {k: str(v)[:200] for k, v in params.items()},
        "status": status,
        "duration_ms": round(duration_ms, 1),
    }
    if data:
        entry["data_preview"] = str(data)[:500]
    if error:
        entry["error"] = str(error)[:500]

    try:
        with open(_AUDIT_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
