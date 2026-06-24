"""Audit log — JSONL file with rotation and HMAC chain tamper detection."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"
_AUDIT_DIR = _BASE / "logs"
_AUDIT_PATH = _AUDIT_DIR / "audit.jsonl"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_BACKUPS = 5
_LOGGER: logging.Logger | None = None
_AUDIT_SECRET: bytes | None = None


def _get_or_create_secret() -> bytes:
    """Return the audit HMAC secret, creating one if needed.

    Order of precedence:
    1. AMJ_AUDIT_SECRET env var
    2. Stored in system_config table
    3. Generated random (persisted to system_config)
    """
    global _AUDIT_SECRET
    if _AUDIT_SECRET is not None:
        return _AUDIT_SECRET

    env_secret = os.getenv("AMJ_AUDIT_SECRET", "")
    if env_secret:
        _AUDIT_SECRET = env_secret.encode()
        return _AUDIT_SECRET

    try:
        from app_config import get_config, set_config
        stored = get_config("audit_secret")
        if stored:
            _AUDIT_SECRET = stored.encode()
            return _AUDIT_SECRET
        # Generate and persist
        new_secret = os.urandom(32).hex()
        set_config("audit_secret", new_secret)
        _AUDIT_SECRET = new_secret.encode()
        return _AUDIT_SECRET
    except Exception:
        _AUDIT_SECRET = b"aimodeljudge-audit-default"
        return _AUDIT_SECRET


def _rotate_if_needed(file: logging.FileHandler | None, path: Path) -> logging.FileHandler | None:
    """Rename audit.jsonl if it exceeds _MAX_BYTES, keeping _MAX_BACKUPS old files."""
    try:
        if not path.exists() or path.stat().st_size < _MAX_BYTES:
            return file
    except OSError:
        return file

    # Close current handler so we can rename
    if file is not None:
        file.close()

    # Rotate: audit.jsonl → audit.1.jsonl, audit.1.jsonl → audit.2.jsonl, ...
    for i in range(_MAX_BACKUPS - 1, -1, -1):
        old_path = path if i == 0 else path.with_name(f"audit.{i}.jsonl")
        new_path = path.with_name(f"audit.{i + 1}.jsonl")
        if old_path.exists():
            try:
                old_path.replace(new_path)
            except OSError:
                pass

    # Remove backups beyond _MAX_BACKUPS
    for i in range(_MAX_BACKUPS + 1, _MAX_BACKUPS + 5):
        extra = path.with_name(f"audit.{i}.jsonl")
        try:
            extra.unlink()
        except OSError:
            pass

    return None  # signal that handler needs recreation


def _get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    _LOGGER = logging.getLogger("aimodeljudge.audit")
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False

    _rotate_if_needed(None, _AUDIT_PATH)
    handler = logging.FileHandler(str(_AUDIT_PATH))
    handler.setFormatter(logging.Formatter("%(message)s"))

    class _RedactFilter(logging.Filter):
        _PWD_RE = re.compile(
            r"(password|api_key|secret)[=:]\s*[^\s,;}\]\"]+", re.IGNORECASE
        )
        _STRIPE_RE = re.compile(
            r"(?:sk_live_|sk_test_|rk_live_|rk_test_|whsec_)[A-Za-z0-9_]+"
        )
        _BEARER_RE = re.compile(
            r"(?:bearer|Bearer)\s+[A-Za-z0-9\-._~+/]+=*"
        )
        _MASTER_KEY_RE = re.compile(
            r"AMJ_MASTER_KEY[=:]\s*[A-Za-z0-9\-_+/]+=*", re.IGNORECASE
        )

        def filter(self, record: logging.LogRecord) -> bool:
            if isinstance(record.msg, str):
                record.msg = self._PWD_RE.sub(r"\1=[REDACTED]", record.msg)
                record.msg = self._STRIPE_RE.sub("[STRIPE_KEY_REDACTED]", record.msg)
                record.msg = self._BEARER_RE.sub("Bearer [REDACTED]", record.msg)
                record.msg = self._MASTER_KEY_RE.sub("AMJ_MASTER_KEY=[REDACTED]", record.msg)
            return True

    _LOGGER.addFilter(_RedactFilter())
    _LOGGER.addHandler(handler)
    return _LOGGER


def _rotate_check() -> None:
    """Check audit log size and rotate if needed."""
    global _LOGGER
    lg = _LOGGER
    handler = lg.handlers[0] if lg and lg.handlers else None
    new_handler = _rotate_if_needed(
        handler if isinstance(handler, logging.FileHandler) else None, _AUDIT_PATH
    )
    if new_handler is None and handler is not None and _LOGGER:
        # Re-create handler after rotation
        _LOGGER.removeHandler(handler)
        fresh = logging.FileHandler(str(_AUDIT_PATH))
        fresh.setFormatter(logging.Formatter("%(message)s"))
        for f in _LOGGER.filters:
            fresh.addFilter(f)
        _LOGGER.addHandler(fresh)


def _prev_entry_hash() -> str:
    """Read the last audit entry's chain_hash, or '0' * 64 for the first entry."""
    try:
        if not _AUDIT_PATH.exists():
            return "0" * 64
        with open(_AUDIT_PATH, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() == 0:
                return "0" * 64
            # Read last ~2KB to find last line
            pos = max(0, f.tell() - 2048)
            f.seek(pos)
            tail = f.read().decode("utf-8", errors="replace")
            lines = [l for l in tail.strip().split("\n") if l]
            if not lines:
                return "0" * 64
            last = json.loads(lines[-1])
            return last.get("chain_hash", "0" * 64)
    except Exception:
        return "0" * 64


def log_audit(
    user_id: str | None,
    action: str,
    resource: str,
    detail: str | None = None,
    ip_address: str | None = None,
    result: str = "success",
) -> None:
    """Write a structured audit entry as one JSON line with HMAC chain hash."""
    secret = _get_or_create_secret()
    prev_hash = _prev_entry_hash()

    corr_id = _get_correlation_id()
    payload: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "user_id": user_id or "anon",
        "action": action,
        "resource": resource,
        "detail": detail or "",
        "ip": ip_address or "",
        "result": result,
        "correlation_id": corr_id,
    }
    # Deterministic serialization for chain verification
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    chain_input = f"{prev_hash}|{payload_json}".encode()
    chain_hash = hmac.new(secret, chain_input, hashlib.sha256).hexdigest()
    payload["chain_hash"] = chain_hash

    _get_logger().info(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    # Check rotation after each write (cheap stat() check)
    _rotate_check()


def _get_correlation_id() -> str:
    """Extract correlation_id from the current logging context if available."""
    try:
        from correlation import _CorrelationLogFilter
        cv = _CorrelationLogFilter._context_var
        if cv:
            return cv.get(None) or ""
    except Exception:
        pass
    return ""


def verify_chain() -> dict:
    """Replay all audit entries and verify the HMAC chain integrity.

    Returns:
        {"valid": bool, "total_lines": int, "broken_at_line": int | None}
    """
    secret = _get_or_create_secret()
    prev_hash = "0" * 64
    total = 0
    verified = 0

    if not _AUDIT_PATH.exists():
        return {"valid": True, "total_lines": 0, "verified": 0, "broken_at_line": None}

    with open(_AUDIT_PATH, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total = line_num
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return {"valid": False, "total_lines": total, "broken_at_line": line_num}

            stored_hash = entry.pop("chain_hash", "")
            if not stored_hash:
                # Pre-chain entry — skip verification but keep counting
                continue

            payload_json = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            chain_input = f"{prev_hash}|{payload_json}".encode()
            expected = hmac.new(secret, chain_input, hashlib.sha256).hexdigest()

            if stored_hash != expected:
                return {"valid": False, "total_lines": total, "verified": verified, "broken_at_line": line_num}

            prev_hash = stored_hash
            verified += 1

    return {"valid": True, "total_lines": total, "verified": verified, "broken_at_line": None}
