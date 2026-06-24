"""User identity — JWT + API key authentication (header-polymorphic)."""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, Request

_log = logging.getLogger("aimodeljudge.auth")

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"
_STATE_DB = _BASE / "state.db"

MIN_PASSWORD_LENGTH = 10

# Top-100 most common passwords — banned for security
_COMMON_PASSWORDS: set[str] = {
    "123456", "password", "123456789", "12345678", "12345", "1234567890",
    "1234567", "qwerty123", "qwerty1", "qwerty", "111111", "11111111",
    "abc123", "football", "monkey", "dragon", "master", "letmein",
    "login", "princess", "welcome", "admin", "password1", "passw0rd",
    "iloveyou", "sunshine", "trustno1", "batman", "access", "hello",
    "charlie", "donald", "freedom", "whatever", "cheese", "pepper",
    "shadow", "michael", "superman", "starwars", "qazwsx", "1q2w3e4r",
    "123321", "password123", "admin123", "letmein123", "welcome123",
    "qwertyuiop", "asdfghjkl", "zxcvbnm", "1234", "123", "12",
    "000000", "666666", "888888", "baseball", "hockey", "soccer",
    "ashley", "bailey", "buster", "cookie", "dakota", "testing",
    "test", "guest", "root", "administrator", "user", "pass",
    "changeme", "secret", "temp123", "qwerty12345", "p@ssw0rd",
    "P@ssw0rd", "Pa$$w0rd", "Password", "PASSWORD", "qwert",
    "123qwe", "abc", "aaaaaa", "1111", "7777777", "121212",
    "flower", "lovely", "chocolate", "summer", "winter",
}

_INVALID_PASSWORD_MSG = (
    f"Password must be at least {MIN_PASSWORD_LENGTH} characters "
    "and not a commonly used password"
)


def validate_password(password: str) -> str | None:
    """Returns error message if password fails policy, None if valid."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return _INVALID_PASSWORD_MSG
    if password.lower() in _COMMON_PASSWORDS:
        return _INVALID_PASSWORD_MSG
    return None


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_STATE_DB))
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class UserContext:
    user_id: str
    email: str
    tier: str
    api_key: str
    subscription_active: bool
    scope: str = "full"
    is_admin: bool = False
    banned: bool = False
    active_profile_id: str | None = None
    profile_count: int = 0


async def get_user_context(request: Request) -> UserContext:
    """FastAPI dependency. Tries Bearer JWT first, falls back to X-AMJ-API-Key."""
    # 1. Try Bearer JWT
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            from jwt_auth import verify_token
            claims = verify_token(token, expected_type="access")
            user_id = claims["sub"]
            banned = _is_user_banned(user_id)
            if banned:
                raise HTTPException(status_code=403, detail="Account is banned")
            ctx = _build_user_context_from_db(user_id, api_key="", claims=claims)
            if ctx:
                return ctx
        except HTTPException:
            raise
        except Exception:
            pass  # Fall through to API key auth

    # 2. Fall back to X-AMJ-API-Key
    api_key = (request.headers.get("X-AMJ-API-Key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await _resolve_api_key_user(api_key)


def _is_user_banned(user_id: str) -> bool:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT banned FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row["banned"]) if row else False
    finally:
        conn.close()


def _build_user_context_from_db(user_id: str, api_key: str, claims: dict | None = None) -> UserContext | None:
    """Build UserContext from DB row + optional JWT claims."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, tier, api_key, is_admin, banned FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None

        sub = conn.execute(
            "SELECT tier, status FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()

        active = conn.execute(
            "SELECT id, name FROM profiles WHERE user_id = ? AND is_default = 1 LIMIT 1",
            (user_id,),
        ).fetchone()
        if not active:
            active = conn.execute(
                "SELECT id, name FROM profiles WHERE user_id = ? ORDER BY created_at ASC LIMIT 1",
                (user_id,),
            ).fetchone()
        profile_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()["cnt"]
    finally:
        conn.close()

    subscription_active = sub is not None
    tier = sub["tier"] if subscription_active else (row["tier"] or "free")
    scope = claims.get("scope", "full") if claims else "full"

    return UserContext(
        user_id=row["id"],
        email=row["email"],
        tier=tier,
        api_key=api_key if api_key else row["api_key"],
        subscription_active=subscription_active,
        scope=scope,
        is_admin=bool(row["is_admin"]),
        banned=bool(row["banned"]),
        active_profile_id=active["id"] if active else None,
        profile_count=profile_count,
    )


async def _resolve_api_key_user(api_key: str) -> UserContext:
    """Resolve user from API key (users.api_key or scoped_api_keys)."""
    conn = _get_conn()
    try:
        # Try primary API key
        row = conn.execute(
            "SELECT id, email, tier, api_key, is_admin, banned FROM users WHERE api_key = ?",
            (api_key,),
        ).fetchone()
        if row:
            if row["banned"]:
                raise HTTPException(status_code=403, detail="Account is banned")
            return _build_user_context_from_db(row["id"], api_key)

        # Try scoped API key
        from token_store import get_api_key_scope
        scoped = get_api_key_scope(api_key)
        if scoped:
            return _build_user_context_from_db(scoped["user_id"], api_key, claims={"scope": scoped["scope"]})

        raise HTTPException(status_code=401, detail="Invalid API key")
    finally:
        conn.close()


async def resolve_user_identity(request: Request) -> tuple[str, str, str] | None:
    """Extract (user_id, tier, scope) from request without full UserContext. For middleware."""
    # Try Bearer JWT
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            from jwt_auth import verify_token
            claims = verify_token(token, expected_type="access")
            return (claims["sub"], claims.get("tier", "free"), claims.get("scope", "full"))
        except Exception:
            pass

    # Try X-AMJ-API-Key
    api_key = (request.headers.get("X-AMJ-API-Key") or "").strip()
    if not api_key:
        return None

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, tier FROM users WHERE api_key = ?", (api_key,)
        ).fetchone()
        if row:
            return (row["id"], row["tier"], "full")

        from token_store import get_api_key_scope
        scoped = get_api_key_scope(api_key)
        if scoped:
            row2 = conn.execute(
                "SELECT tier FROM users WHERE id = ?", (scoped["user_id"],)
            ).fetchone()
            return (scoped["user_id"], row2["tier"] if row2 else "free", scoped["scope"])
    finally:
        conn.close()

    return None


async def require_admin(user: UserContext = Depends(get_user_context)) -> UserContext:
    """FastAPI dependency — returns UserContext if admin, raises 403 otherwise."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_user_context_optional(request: Request) -> UserContext | None:
    """Optional auth — returns None for unauthenticated requests."""
    try:
        return await get_user_context(request)
    except HTTPException:
        return None


def generate_api_key() -> str:
    return secrets.token_hex(16)


def create_user(email: str, password_hash: str) -> tuple[str, str]:
    """Creates a user row + default profile. Returns (user_id, api_key). First user or AMJ_ADMIN_EMAIL match → admin."""
    user_id = f"usr_{secrets.token_hex(6)}"
    api_key = generate_api_key()
    conn = _get_conn()
    try:
        # Auto-admin: first user or matches AMJ_ADMIN_EMAIL
        is_first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        admin_email = os.getenv("AMJ_ADMIN_EMAIL", "")
        is_admin = 1 if (is_first or (admin_email and email == admin_email)) else 0
        conn.execute(
            "INSERT INTO users (id, email, password_hash, api_key, created_at, tier, is_admin) VALUES (?, ?, ?, ?, datetime('now'), 'free', ?)",
            (user_id, email, password_hash, api_key, is_admin),
        )
        # ── Auto-create default profile ──
        import uuid
        profile_id = f"prf_{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO profiles (id, user_id, name, description, models, tools, ha_enabled, is_default, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))",
            (profile_id, user_id, "Мой первый профиль", "Default profile", "[]", "[]", 0),
        )
        conn.commit()
    finally:
        conn.close()
    return user_id, api_key


def lookup_user_by_email(email: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_tier(user_id: str) -> str:
    conn = _get_conn()
    try:
        sub = conn.execute(
            "SELECT tier FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if sub:
            return sub["tier"]
        row = conn.execute("SELECT tier FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["tier"] if row else "free"
    finally:
        conn.close()


def verify_password(user_id: str, password: str) -> bool:
    """Verify the user's password. Used for self-service account deletion."""
    from passlib.hash import bcrypt
    conn = _get_conn()
    try:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return False
        return bcrypt.verify(password, row["password_hash"])
    finally:
        conn.close()
