"""Token bucket rate limiter — in-memory, no external dependencies."""

from __future__ import annotations

import time
import threading

_DEFAULT_RPM = 120
_AUTH_LIMIT = 5


class TokenBucket:
    """Token bucket with configurable refill rate and burst capacity."""

    def __init__(self, rate: float, capacity: int | None = None) -> None:
        self.rate = rate  # tokens per second
        self.capacity = capacity if capacity is not None else int(rate * 60)
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def remaining(self) -> int:
        with self._lock:
            self._refill()
            return int(self._tokens)

    @property
    def limit(self) -> int:
        return self.capacity

    @property
    def reset_time(self) -> float:
        with self._lock:
            deficit = self.capacity - self._tokens
            if deficit <= 0:
                return 0
            return deficit / self.rate


class RateLimiter:
    """Singleton rate limiter. Buckets auto-expire after inactivity."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, TokenBucket] = {}  # user_id or IP → bucket
        self._auth_buckets: dict[str, TokenBucket] = {}  # IP → auth bucket
        self._last_cleanup = time.monotonic()

    def _get_tier_bucket(self, key: str, tier: str) -> TokenBucket:
        rpm = _DEFAULT_RPM
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.limit != rpm:
                bucket = TokenBucket(rate=rpm / 60.0, capacity=rpm)
                self._buckets[key] = bucket
            return bucket

    def _get_auth_bucket(self, ip: str) -> TokenBucket:
        with self._lock:
            bucket = self._auth_buckets.get(ip)
            if bucket is None:
                bucket = TokenBucket(rate=_AUTH_LIMIT / 60.0, capacity=_AUTH_LIMIT)
                self._auth_buckets[ip] = bucket
            return bucket

    def check_rate_limit(
        self, user_id: str | None, ip: str, tier: str = "free"
    ) -> tuple[bool, int, int, float]:
        """Returns (allowed, remaining, limit, reset_seconds)."""
        key = user_id or ip
        if user_id:
            bucket = self._get_tier_bucket(key, tier)
        else:
            bucket = self._get_tier_bucket(key, "default")

        allowed = bucket.consume()
        return (allowed, bucket.remaining, bucket.limit, bucket.reset_time)

    def check_auth_limit(self, ip: str) -> tuple[bool, int, int, float]:
        bucket = self._get_auth_bucket(ip)
        allowed = bucket.consume()
        return (allowed, bucket.remaining, bucket.limit, bucket.reset_time)

    def cleanup(self) -> int:
        """Remove idle buckets. Returns count of removed buckets."""
        now = time.monotonic()
        with self._lock:
            removed = 0
            for d in (self._buckets, self._auth_buckets):
                stale = [
                    k for k, b in d.items()
                    if b.remaining >= b.limit and (now - b._last_refill) > 600
                ]
                for k in stale:
                    del d[k]
                    removed += 1
            self._last_cleanup = now
        return removed


_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _limiter


_SCOPE_MULTIPLIERS = {
    "full": 1.0,
    "readonly": 2.0,
    "admin": 300 / 300,  # always 300 rpm
}


def check_token_rate_limit(
    user_id: str, ip: str, tier: str = "free", scope: str = "full"
) -> tuple[bool, int, int, float]:
    """Scope-aware rate limit check. Returns (allowed, remaining, limit, reset_seconds)."""
    limiter = get_rate_limiter()
    base_rpm = _DEFAULT_RPM
    multiplier = _SCOPE_MULTIPLIERS.get(scope, 1.0)
    effective_rpm = int(base_rpm * multiplier)

    if scope == "admin":
        effective_rpm = 300

    # Cap at 300
    if effective_rpm > 300:
        effective_rpm = 300

    # Use a per-user bucket with effective rate
    bucket = limiter._get_tier_bucket(user_id, tier)
    # Override bucket rate/capacity for scope-aware limits
    if bucket.limit != effective_rpm:
        bucket.rate = effective_rpm / 60.0
        bucket.capacity = effective_rpm
        bucket._tokens = min(bucket._tokens, float(effective_rpm))

    allowed = bucket.consume()
    return (allowed, bucket.remaining, bucket.limit, bucket.reset_time)
