"""JWT Token Manager — HS256 access + refresh tokens with vault-first secret resolution."""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid

import jwt

from token_store import is_blacklisted, blacklist_token

_log = logging.getLogger("aimodeljudge.jwt")

_JWT_ISSUER = "aimodeljudge"
_ACCESS_TTL = 15 * 60       # 15 minutes
_REFRESH_TTL = 7 * 24 * 3600  # 7 days
_GRACE_PERIOD = 15 * 60     # 15 minutes for rotated secrets


def _get_jwt_secret() -> str:
    """vault-first resolution of JWT secret. Auto-generates on first start."""
    try:
        from secrets_vault import get_secrets_vault
        vault = get_secrets_vault()
        if vault.is_unlocked():
            secret = vault.get_secret("AMJ_JWT_SECRET")
            if secret:
                return secret
    except Exception:
        pass

    env_secret = os.getenv("AMJ_JWT_SECRET", "")
    if env_secret:
        return env_secret

    # Auto-generate and persist
    new_secret = os.urandom(32).hex()
    try:
        from secrets_vault import get_secrets_vault
        vault = get_secrets_vault()
        if vault.is_unlocked():
            vault.set_secret("AMJ_JWT_SECRET", new_secret)
    except Exception:
        pass
    os.environ["AMJ_JWT_SECRET"] = new_secret
    return new_secret


def _get_old_secrets(limit: int = 5) -> list[str]:
    """Retrieve up to `limit` previously rotated secrets from vault (grace period)."""
    try:
        from secrets_vault import get_secrets_vault
        vault = get_secrets_vault()
        if not vault.is_unlocked():
            return []
        secrets = []
        names = vault.list_secrets()
        for name in names:
            if name.startswith("AMJ_JWT_SECRET_v"):
                val = vault.get_secret(name)
                if val:
                    secrets.append(val)
        return secrets[-limit:]
    except Exception:
        return []


def create_access_token(
    user_id: str,
    email: str,
    tier: str,
    scope: str = "full",
    is_admin: bool = False,
) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email,
        "tier": tier,
        "scope": scope,
        "is_admin": is_admin,
        "iat": now,
        "exp": now + _ACCESS_TTL,
        "jti": f"jti_{uuid.uuid4().hex[:16]}",
        "iss": _JWT_ISSUER,
        "type": "access",
    }
    return jwt.encode(claims, _get_jwt_secret(), algorithm="HS256")


def create_refresh_token(user_id: str) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "iat": now,
        "exp": now + _REFRESH_TTL,
        "jti": f"jti_{uuid.uuid4().hex[:16]}",
        "iss": _JWT_ISSUER,
        "type": "refresh",
    }
    return jwt.encode(claims, _get_jwt_secret(), algorithm="HS256")


def verify_token(token: str, expected_type: str = "access") -> dict:
    """Verify JWT signature + expiry + blacklist. Returns claims dict or raises."""
    secret = _get_jwt_secret()
    last_err = None

    # Try current secret
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], issuer=_JWT_ISSUER)
    except jwt.ExpiredSignatureError:
        raise
    except jwt.InvalidTokenError as e:
        last_err = e
        claims = None

    # Grace period: try older secrets
    if claims is None:
        for old_secret in _get_old_secrets():
            try:
                claims = jwt.decode(token, old_secret, algorithms=["HS256"], issuer=_JWT_ISSUER)
                break
            except jwt.ExpiredSignatureError:
                raise
            except jwt.InvalidTokenError:
                continue

    if claims is None:
        raise last_err or jwt.InvalidTokenError("Invalid token")

    if claims.get("type") != expected_type:
        raise jwt.InvalidTokenError(
            f"Expected token type '{expected_type}', got '{claims.get('type')}'"
        )

    jti = claims.get("jti", "")
    if jti and is_blacklisted(jti):
        raise jwt.InvalidTokenError("Token has been revoked")

    return claims


def decode_user_context_from_token(token: str) -> dict | None:
    """Extract user fields from JWT claims (no SQLite needed). Returns None on failure."""
    try:
        claims = verify_token(token, expected_type="access")
        return {
            "user_id": claims["sub"],
            "email": claims.get("email", ""),
            "tier": claims.get("tier", "free"),
            "scope": claims.get("scope", "full"),
            "is_admin": claims.get("is_admin", False),
        }
    except Exception:
        return None


def rotate_jwt_secret() -> str:
    """Generate new JWT secret, store old one for grace period verification."""
    old_secret = _get_jwt_secret()
    new_secret = os.urandom(32).hex()

    # Store old secret in vault with versioned key for grace period
    try:
        from secrets_vault import get_secrets_vault
        vault = get_secrets_vault()
        if vault.is_unlocked():
            ts = int(time.time())
            vault.set_secret(f"AMJ_JWT_SECRET_v{ts}", old_secret)
    except Exception:
        pass

    # Record in jwt_secret_versions table
    import sqlite3
    from token_store import _get_conn
    old_hash = hashlib.sha256(old_secret.encode()).hexdigest()
    conn = _get_conn()
    try:
        conn.execute("UPDATE jwt_secret_versions SET active = 0")
        conn.execute(
            "INSERT INTO jwt_secret_versions (version, secret_hash, created_at, active) "
            "VALUES (COALESCE((SELECT MAX(version) FROM jwt_secret_versions), 0) + 1, ?, datetime('now'), 1)",
            (old_hash,),
        )
        conn.commit()
    finally:
        conn.close()

    # Update vault with new secret
    try:
        from secrets_vault import get_secrets_vault
        vault = get_secrets_vault()
        if vault.is_unlocked():
            vault.set_secret("AMJ_JWT_SECRET", new_secret)
    except Exception:
        pass
    os.environ["AMJ_JWT_SECRET"] = new_secret

    _log.info("JWT secret rotated (old hash=%s)", old_hash[:16])
    return new_secret
