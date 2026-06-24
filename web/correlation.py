"""Correlation ID middleware — injects X-Correlation-ID into every request/response."""

from __future__ import annotations

import logging
import time
import uuid as _uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware


def _uuid7() -> str:
    """Generate UUID v7 (time-ordered, millisecond precision) without extra deps."""
    import os
    ticks = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    # Layout: 48-bit timestamp | 4-bit version(7) | 12-bit rand_a | 2-bit variant(10) | 62-bit rand_b
    uuid7 = (
        (ticks & 0xFFFFFFFFFFFF) << 80
        | 0x7000 << 64
        | (rand & 0x0FFFFFFFFFFFFFFF)
    )
    uuid7 |= 0x8000000000000000  # variant bits
    return str(_uuid.UUID(int=uuid7))


class _CorrelationLogFilter(logging.Filter):
    """Inject correlation_id from request state into log records."""

    _context_var = None  # set lazily

    def filter(self, record: logging.LogRecord) -> bool:
        cv = _CorrelationLogFilter._context_var
        if cv:
            corr_id = cv.get(None)
            if corr_id:
                record.correlation_id = corr_id
        return True


def create_correlation_middleware() -> type:
    """Create a Starlette middleware that sets X-Correlation-ID on every request.

    Returns the class (not an instance) so it can be passed to app.add_middleware().
    """
    import contextvars
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi import Request

    _corr_var = contextvars.ContextVar("correlation_id", default=None)

    class _CorrelationMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            corr_id = request.headers.get("X-Correlation-ID") or _uuid7()
            _corr_var.set(corr_id)
            request.state.correlation_id = corr_id
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = corr_id
            return response

    # Wire the context var to the log filter
    _CorrelationLogFilter._context_var = _corr_var
    return _CorrelationMiddleware
