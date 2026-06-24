"""Structured logging configuration with rotation and JSON formatter."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
from datetime import datetime, timezone
from pathlib import Path


LOG_DIR = Path.home() / ".hermes-aimodeljudge" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_LOG_FORMAT = os.getenv("AMJ_LOG_FORMAT", "json").lower()


class _JSONFormatter(logging.Formatter):
    """Emit log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        corr_id = getattr(record, "correlation_id", None)
        if corr_id:
            payload["correlation_id"] = corr_id
        if record.exc_info and record.exc_info[1]:
            payload["exc"] = str(record.exc_info[1])
        return json.dumps(payload, ensure_ascii=False)


def _plain_formatter() -> logging.Formatter:
    return logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("aimodeljudge")
    logger.setLevel(logging.INFO)

    # Rotation: 10 MB × 5 backups
    file_handler = logging.handlers.RotatingFileHandler(
        str(LOG_DIR / "web.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )

    if _LOG_FORMAT == "json":
        file_handler.setFormatter(_JSONFormatter())
    else:
        file_handler.setFormatter(_plain_formatter())

    logger.addHandler(file_handler)

    # stdout stays human-readable
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_plain_formatter())
    logger.addHandler(stream_handler)

    # Sanitization filter
    class _RedactAPIKeyFilter(logging.Filter):
        _KEY_RE = re.compile(
            r"X-AMJ-API-Key[=:]\s*[a-f0-9]{32}", re.IGNORECASE
        )
        _PWD_RE = re.compile(
            r"password[=:]\s*[^\s,;]+", re.IGNORECASE
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
                record.msg = self._PWD_RE.sub("password=[REDACTED]", record.msg)
                record.msg = self._KEY_RE.sub("X-AMJ-API-Key=[REDACTED]", record.msg)
                record.msg = self._STRIPE_RE.sub("[STRIPE_KEY_REDACTED]", record.msg)
                record.msg = self._BEARER_RE.sub("Bearer [REDACTED]", record.msg)
                record.msg = self._MASTER_KEY_RE.sub("AMJ_MASTER_KEY=[REDACTED]", record.msg)
            return True

    logger.addFilter(_RedactAPIKeyFilter())
    return logger
