"""AIModelJudge Web Agent — FastAPI роуты (без авторизации)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from services.shared.hermes_proxy_v2 import agentic_stream
from services.shared.model_router import (
    get_active_model_label,
    get_display_name,
    get_other_model_label,
    list_available_models,
    switch_model,
)
from services.shared.tool_executor import TOOL_DEFINITIONS
from config import SYSTEM_PROMPT
from data_layer import (
    create_session as dl_create_session,
    list_sessions,
    search_sessions,
    get_session as dl_get_session,
    update_session_title,
    list_tasks,
    create_task,
    update_task,
    delete_task,
    list_cron,
    create_cron,
    toggle_cron,
    delete_cron as dl_delete_cron,
    trigger_cron,
    count_cron,
    list_skills as dl_list_skills,
    get_skill_content as dl_get_skill_content,
    create_skill as dl_create_skill,
    create_profile,
    list_profiles,
    get_profile,
    update_profile,
    delete_profile,
    set_default_profile,
    activate_profile,
    delete_user_cascade,
)
from auth import UserContext, create_user, get_user_context, get_user_context_optional, lookup_user_by_email, require_admin, resolve_user_identity, validate_password, verify_password, MIN_PASSWORD_LENGTH
from audit import log_audit
from tiers import get_tier_limit, clamp_side_models
from hooks import (
    fire_cron_complete,
    fire_notification,
    fire_session_start,
    fire_stop,
    invoke_pre_compact,
    invoke_user_prompt_submit,
)
from primary_models import (
    set_side_event_queue,
    set_primary_tools,
    TOOL_DEF as QUERY_PRIMARY_MODELS_TOOL,
    handle_query_primary_models,
    PRIMARY_TOOL_DEFINITIONS,
)


def _load_ecc_skills_for_ha() -> str:
    """Load ECC skill descriptions from ~/.hermes/skills/ecc-imports/ for HA injection."""
    ecc_dir = Path.home() / ".hermes" / "skills" / "ecc-imports"
    if not ecc_dir.exists():
        return ""

    lines: list[str] = []
    for skill_dir in sorted(ecc_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
            name = skill_dir.name
            desc = ""
            if content.startswith("---"):
                for line in content.splitlines()[1:]:
                    stripped = line.strip()
                    if stripped == "---":
                        break
                    if stripped.startswith("name:"):
                        name = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("description:"):
                        desc = stripped.split(":", 1)[1].strip()
            if desc:
                lines.append(f"- **{name}**: {desc}")
        except Exception:
            pass

    if not lines:
        return ""

    return "\n\nДОСТУПНЫЕ ECC-НАВЫКИ (Hermes Agent, используй при релевантных задачах):\n" + "\n".join(lines)


def _build_system_prompt(
    active_models: list[str] | None = None,
    ha_enabled: bool = False,
    user_tier: str = "free",
) -> str:
    """Дополняет базовый SYSTEM_PROMPT информацией о доступных экспертах."""
    model_label = get_active_model_label()
    model_display = get_display_name(model_label)

    def _short(model: str) -> str:
        return get_display_name(model)

    count = len(active_models) if active_models else 0

    # Harden system prompt with defensive instructions
    from web.prompt_guard import harden_system_prompt
    secured_prompt = harden_system_prompt(SYSTEM_PROMPT)

    # Собираем базовый промпт в зависимости от количества моделей
    if count == 0:
        base = (
            secured_prompt
            + f"\n\nТЕКУЩАЯ СЕССИЯ: Центральная модель — {model_display}. "
            "Эксперты (side-модели) отключены — работай самостоятельно. "
            "Используй CodeGraph, Memory MCP и другие инструменты для анализа."
        )
    elif count == 1:
        model = active_models[0]
        model_short = _short(model)
        base = (
            secured_prompt
            + f"\n\nТЕКУЩАЯ СЕССИЯ: Центральная модель — {model_display}. "
            f"Доступен 1 эксперт: {model_short}. "
            "ОБЯЗАТЕЛЬНО вызови query_primary_models с enriched query "
            "для консультации с экспертом ПЕРЕД тем как дать ответ. "
            "Синтезируй итоговое решение на основе своего анализа "
            "и ответа эксперта."
        )
    else:
        # count >= 2
        model_left = active_models[0]
        model_right = active_models[1]
        left_short = _short(model_left)
        right_short = _short(model_right)
        base = (
            secured_prompt
            + f"\n\nТЕКУЩАЯ СЕССИЯ: Центральная модель — {model_display}. "
            f"Доступны 2 эксперта: {left_short}, {right_short}. "
            "ОБЯЗАТЕЛЬНО вызови query_primary_models с enriched query "
            "для параллельной консультации с обоими ПЕРЕД тем как дать ответ. "
            "Синтезируй итоговое решение: консенсус, противоречия, пробелы. "
            "НЕ сравнивай «кто лучше» — ты архитектор, а не судья."
        )

    # ── ECC-навыки Hermes Agent (ha_enabled профиль) ──
    if ha_enabled:
        try:
            ecc_skills = _load_ecc_skills_for_ha()
            if ecc_skills:
                base += ecc_skills
        except Exception:
            pass

    # ── Инжекция топ-5 горячих навыков ──
    try:
        from web.skills_manager import SkillRanker
        hot = SkillRanker.get_top_hot(5)
        if hot:
            lines = ["\n\nДОСТУПНЫЕ НАВЫКИ (горячие, используй при релевантных задачах):"]
            for h in hot:
                lines.append(f"\n### {h['name']} (hot_score={h['hot_score']})\n{h['content']}")
            return base + "\n".join(lines)
    except Exception:
        pass

    return base


router = APIRouter()

# ── Route tags for OpenAPI docs ──
_ROUTE_TAGS = {
    "Core": "Health, metrics, OpenAPI, docs",
    "Auth": "Register, login, JWT, API keys",
    "Chat": "SSE chat streaming, approve, cancel",
    "Models": "Model list, switch, cache stats",
    "Profiles": "Profile management, switch, context",
    "Skills": "Skill CRUD, rating, content",
    "Sessions": "Session search, history, details",
    "Projects": "Project listing, context",
    "Kanban": "Kanban task management",
    "Cron": "Cron job scheduling",
    "Memory": "Memory graph, self-learning",
    "Analytics": "Token usage, benchmarks, token efficiency",
    "Diff": "File diff comparison",
    "Rules": "Rules engine management",
    "Admin": "User management, promo codes, audit, config",
    "Subscription": "Checkout, portal, webhooks",
}

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path("/tmp/aimodeljudge_web_uploads")


@router.get("/health", tags=['Core'])
async def health():
    """Healthcheck с расширенной информацией о состоянии сервиса.

    """
    import os
    import time
    import sys

    info: dict = {"status": "ok", "service": "aimodeljudge-web"}

    # Uptime (from main.py start timestamp)
    try:
        from web.main import _app_start_time
        info["uptime_seconds"] = round(time.time() - _app_start_time)
    except Exception:
        info["uptime_seconds"] = -1

    # Memory usage
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        info["memory_usage_mb"] = round(usage.ru_maxrss / 1024.0, 1)
    except Exception:
        info["memory_usage_mb"] = -1

    # Active SSE sessions (tracked by app.state)
    try:
        from starlette.requests import Request
    except Exception:
        pass
    # Попытка получить через metrics module
    try:
        from web.metrics import _active_sessions
        info["active_sessions"] = int(_active_sessions.get())
    except Exception:
        info["active_sessions"] = 0

    # Python version
    info["python_version"] = sys.version.split()[0]

    # Models
    try:
        from services.shared.model_router import list_available_models
        models = list_available_models()
        info["models_available"] = len(models)
    except Exception:
        info["models_available"] = -1

    # Rules Engine
    try:
        from rules import get_rules_engine
        engine = get_rules_engine()
        info["rules_loaded"] = sum(len(v) for v in engine.rules.values())
    except Exception:
        info["rules_loaded"] = 0

    # Hooks
    try:
        from hooks import get_hook_manager
        mgr = get_hook_manager()
        info["hooks_active"] = len(mgr.active_hooks)
    except Exception:
        info["hooks_active"] = 0

    # Model Cache
    try:
        from model_cache import get_cache
        cache = get_cache()
        info["cache_size"] = len(cache)
    except Exception:
        info["cache_size"] = 0

    # Prompt Guard
    try:
        from web.prompt_guard import get_guard_stats
        stats = get_guard_stats().as_dict()
        info["prompt_guard"] = {
            "total_scanned": stats.get("total_scanned", 0),
            "total_blocked": stats.get("total_blocked", 0),
        }
    except Exception:
        info["prompt_guard"] = {"error": "unavailable"}

    # Sandbox
    try:
        from web.sandbox import get_sandbox_stats
        sandbox_stats = get_sandbox_stats()
        info["sandbox"] = sandbox_stats
    except Exception:
        info["sandbox"] = {"error": "unavailable"}

    return info


@router.get("/metrics", tags=['Core'])
async def metrics():
    """Prometheus-compatible metrics endpoint."""
    from web.metrics import render_metrics
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=render_metrics(), media_type="text/plain; charset=utf-8")


# ── Auth ──

from passlib.hash import bcrypt


@router.post("/auth/register", tags=['Auth'])
async def auth_register(request: Request):
    """Register a new user. Returns API key + JWT tokens."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    pw_err = validate_password(password)
    if pw_err:
        return JSONResponse({"error": pw_err}, status_code=422)

    existing = lookup_user_by_email(email)
    if existing:
        return JSONResponse({"error": "Email already registered"}, status_code=409)

    password_hash = bcrypt.hash(password)
    user_id, api_key = create_user(email, password_hash)

    # Generate JWT tokens
    from jwt_auth import create_access_token, create_refresh_token
    is_admin = os.getenv("AMJ_ADMIN_EMAIL", "") == email
    access_token = create_access_token(user_id, email, "free", "full", is_admin)
    refresh_token = create_refresh_token(user_id)

    # Apply referral code if provided
    referral_code = (body.get("referral_code") or "").strip()
    referral_applied = False
    if referral_code:
        try:
            state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
            rconn = sqlite3.connect(str(state_db))
            try:
                ref = rconn.execute(
                    "SELECT owner_user_id, usage_count FROM referral_codes WHERE code = ?",
                    (referral_code,),
                ).fetchone()
                if ref and ref[0] != user_id:
                    rconn.execute(
                        "UPDATE referral_codes SET usage_count = usage_count + 1 WHERE code = ?",
                        (referral_code,),
                    )
                    # Credit reward: +1 month Pro for referrer
                    from datetime import datetime as _dt, timedelta as _td
                    referrer_sub = rconn.execute(
                        "SELECT id, current_period_end, tier FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                        (ref[0],),
                    ).fetchone()
                    if referrer_sub:
                        new_end = (_dt.fromisoformat(referrer_sub[2]) + _td(days=30)).isoformat()
                        rconn.execute(
                            "UPDATE subscriptions SET current_period_end = ? WHERE id = ?",
                            (new_end, referrer_sub[0]),
                        )
                    # Credit reward: +1 month Pro for new user (applied after registration)
                    rconn.execute(
                        "UPDATE subscriptions SET current_period_end = datetime(current_period_end, '+30 days') WHERE user_id = ? AND status = 'active'",
                        (user_id,),
                    )
                    rconn.commit()
                    referral_applied = True
            finally:
                rconn.close()
        except Exception:
            pass

    log_audit(user_id, "register", "auth", f"email={email}", request.client.host if request.client else None)

    onboarding_prompt = (
        "Проведи код-ревью файла web/routes.py и предложи архитектурные улучшения. "
        "Используй инструменты поиска и анализа кода."
    )

    return JSONResponse({
        "user_id": user_id,
        "email": email,
        "api_key": api_key,
        "tier": "free",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 900,
        "onboarding_prompt": onboarding_prompt if not referral_applied else None,
        "referral_applied": referral_applied,
    })


@router.post("/auth/login", tags=['Auth'])
async def auth_login(request: Request):
    """Login with email + password. Returns API key + JWT tokens."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    user = lookup_user_by_email(email)
    if not user:
        log_audit(None, "login", "auth", f"email={email}", request.client.host if request.client else None, "failure")
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)

    try:
        if not bcrypt.verify(password, user["password_hash"]):
            log_audit(user["id"], "login", "auth", f"email={email}", request.client.host if request.client else None, "failure")
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)
    except ValueError:
        log_audit(user["id"], "login", "auth", f"email={email}", request.client.host if request.client else None, "failure")
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)

    if user.get("banned"):
        return JSONResponse({"error": "Account is banned"}, status_code=403)

    log_audit(user["id"], "login", "auth", f"email={email}", request.client.host if request.client else None)

    # Generate JWT tokens
    from jwt_auth import create_access_token, create_refresh_token
    access_token = create_access_token(
        user["id"], user["email"], user["tier"], "full", bool(user.get("is_admin"))
    )
    refresh_token = create_refresh_token(user["id"])

    return JSONResponse({
        "user_id": user["id"],
        "email": user["email"],
        "api_key": user["api_key"],
        "tier": user["tier"],
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 900,
    })


@router.get("/auth/me", tags=['Auth'])
async def auth_me(user=Depends(get_user_context)):
    """Return current user info. Bearer JWT or X-AMJ-API-Key."""
    return JSONResponse({
        "user_id": user.user_id,
        "email": user.email,
        "tier": user.tier,
        "api_key": user.api_key[:8] + "..." if user.api_key else "",
        "subscription_active": user.subscription_active,
        "is_admin": user.is_admin,
        "scope": user.scope,
    })


@router.delete("/auth/delete-account", tags=['Auth'])
async def delete_account(request: Request, user: UserContext = Depends(get_user_context)):
    """Delete own account with password confirmation. Cascade-deletes all user data."""
    body = await request.json()
    password = body.get("password", "")
    if not password:
        return JSONResponse({"error": "Password required for account deletion"}, status_code=400)
    if not verify_password(user.user_id, password):
        log_audit(user.user_id, "delete_account", "auth", f"email={user.email}", result="failure")
        return JSONResponse({"error": "Invalid password"}, status_code=401)
    try:
        stats = delete_user_cascade(user.user_id)
        log_audit(user.user_id, "delete_account", "auth", f"email={user.email}", result="success")
        return JSONResponse({"deleted": True, **stats})
    except Exception as e:
        log_audit(user.user_id, "delete_account", "auth", f"email={user.email}", result="failure")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── JWT Token routes ──

@router.post("/auth/refresh", tags=['Auth'])
async def auth_refresh(request: Request):
    """Exchange refresh_token for new access+refresh pair. Old refresh is blacklisted."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    refresh_token = str(body.get("refresh_token", "")).strip()
    if not refresh_token:
        return JSONResponse({"error": "refresh_token required"}, status_code=400)

    from jwt_auth import verify_token, create_access_token, create_refresh_token
    from token_store import blacklist_token
    import time as _time

    try:
        claims = verify_token(refresh_token, expected_type="refresh")
    except Exception:
        return JSONResponse({"error": "Invalid or expired refresh token"}, status_code=401)

    user_id = claims["sub"]
    # Blacklist the used refresh token
    blacklist_token(claims["jti"], user_id, claims["exp"])

    # Look up current user state
    conn = sqlite3.connect(str(_SUB_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT email, tier, is_admin FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            return JSONResponse({"error": "User not found"}, status_code=401)
        if row["banned"]:
            return JSONResponse({"error": "Account is banned"}, status_code=403)
    finally:
        conn.close()

    access_token = create_access_token(
        user_id, row["email"], row["tier"], "full", bool(row["is_admin"])
    )
    new_refresh = create_refresh_token(user_id)

    log_audit(user_id, "token_refresh", "auth", result="success")

    return JSONResponse({
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": 900,
    })


@router.post("/auth/logout", tags=['Auth'])
async def auth_logout(request: Request, user=Depends(get_user_context)):
    """Blacklist the current access token JTI."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        from jwt_auth import verify_token
        from token_store import blacklist_token
        try:
            # Don't enforce expiry here — allow logging out even with expired token
            import jwt as _jwt
            unverified = _jwt.decode(token, options={"verify_signature": False})
            jti = unverified.get("jti", "")
            exp = unverified.get("exp", 0)
            if jti:
                blacklist_token(jti, user.user_id, float(exp))
        except Exception:
            pass

    log_audit(user.user_id, "logout", "auth")
    return JSONResponse({"ok": True})


# ── Scoped API Keys ──

@router.get("/auth/api-keys", tags=['Auth'])
async def list_api_keys(user=Depends(get_user_context)):
    """List scoped API keys for the current user."""
    from token_store import list_scoped_keys
    keys = list_scoped_keys(user.user_id)
    return JSONResponse({
        "keys": [
            {"prefix": k["api_key"][:8], "scope": k["scope"], "name": k["name"], "created_at": k["created_at"]}
            for k in keys
        ],
    })


@router.post("/auth/api-keys", tags=['Auth'])
async def create_api_key(request: Request, user=Depends(get_user_context)):
    """Create a scoped API key. {scope, name}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    scope = str(body.get("scope", "readonly")).strip()
    name = str(body.get("name", "")).strip()

    if scope not in ("full", "readonly", "admin"):
        return JSONResponse({"error": "scope must be: full, readonly, admin"}, status_code=400)
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    if scope == "admin" and not user.is_admin:
        return JSONResponse({"error": "Only admins can create admin-scoped keys"}, status_code=403)

    import secrets
    from token_store import set_api_key_scope

    api_key = f"amj_{secrets.token_hex(16)}"
    set_api_key_scope(api_key, user.user_id, scope, name)

    log_audit(user.user_id, "create_api_key", "auth", f"scope={scope} name={name}")

    return JSONResponse({
        "api_key": api_key,
        "scope": scope,
        "name": name,
    })


@router.delete("/auth/api-keys/{prefix}", tags=['Auth'])
async def delete_api_key(prefix: str, user=Depends(get_user_context)):
    """Revoke a scoped API key by its first 8 characters."""
    if len(prefix) < 8:
        return JSONResponse({"error": "prefix must be at least 8 characters"}, status_code=400)

    from token_store import list_scoped_keys, delete_scoped_key

    keys = list_scoped_keys(user.user_id)
    for k in keys:
        if k["api_key"].startswith(prefix):
            delete_scoped_key(k["api_key"])
            log_audit(user.user_id, "delete_api_key", "auth", f"prefix={prefix}")
            return JSONResponse({"ok": True})

    return JSONResponse({"error": "API key not found"}, status_code=404)


# ── JWT Secret Rotation (admin only) ──

@router.post("/auth/rotate-secret", tags=['Auth'])
async def rotate_jwt_secret(user=Depends(require_admin)):
    """Rotate JWT signing secret. Old tokens remain valid for 15min grace period."""
    from jwt_auth import rotate_jwt_secret
    rotate_jwt_secret()
    log_audit(user.user_id, "rotate_jwt_secret", "auth")
    return JSONResponse({"ok": True, "message": "JWT secret rotated. Old tokens valid for 15 more minutes."})


# ── Subscription routes ──

_SUB_STATE_DB = Path.home() / ".hermes-aimodeljudge" / "state.db"



@router.post("/subscription/checkout", tags=['Subscription'])
async def subscription_checkout(request: Request, user=Depends(get_user_context)):
    """Payment checkout — disabled for public release."""
    return JSONResponse({"error": "Payment processing is not available in the open-source release"}, status_code=501)


@router.post("/subscription/portal", tags=['Subscription'])
async def subscription_portal(request: Request, user=Depends(get_user_context)):
    """Subscription portal — disabled for public release."""
    return JSONResponse({"error": "Payment processing is not available in the open-source release"}, status_code=501)


@router.post("/subscription/webhook", tags=['Subscription'])
async def subscription_webhook(request: Request):
    """Payment webhook — disabled for public release."""
    return JSONResponse({"error": "Payment processing is not available in the open-source release"}, status_code=501)


@router.get("/subscription/provider", tags=['Subscription'])
async def subscription_provider():
    """Return the currently active payment provider name."""
    import os
    return JSONResponse({
        "provider": "none",
    })


@router.get("/subscription/status", tags=['Subscription'])
async def subscription_status(request: Request, user=Depends(get_user_context)):
    """Return current subscription status."""
    conn = sqlite3.connect(str(_SUB_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        sub = conn.execute(
            "SELECT tier, status, current_period_end FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (user.user_id,),
        ).fetchone()
    finally:
        conn.close()

    return JSONResponse({
        "tier": user.tier,
        "subscription_active": user.subscription_active,
        "status": sub["status"] if sub else "none",
        "current_period_end": sub["current_period_end"] if sub else None,
    })


@router.get("/projects/list", tags=['Projects'])
async def list_projects(root: str = "", user: UserContext = Depends(get_user_context)):
    if not root:
        root = str(Path.home())
    if not os.path.isdir(root):
        return JSONResponse({"error": "Invalid root directory"}, status_code=400)
    projects = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if not os.path.isdir(full) or name.startswith("."):
            continue
        display = None
        for fname in ("CLAUDE.md", "README.md"):
            fpath = os.path.join(full, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    first = f.readline().strip()
                    if first.startswith("# "):
                        display = first[2:].strip()
                        break
            except OSError:
                pass
        projects.append({"name": name, "display": display, "path": full})
    return JSONResponse({"root": root, "projects": projects})


@router.get("/projects/context", tags=['Projects'])
async def get_project_context(path: str = "", user: UserContext = Depends(get_user_context)):
    """Читает CLAUDE.md и README.md из директории проекта."""
    if not path or not os.path.isdir(path):
        return JSONResponse({"error": "Invalid project path"}, status_code=400)
    if not os.path.abspath(path).startswith(os.path.expanduser("~")):
        return JSONResponse({"error": "Path outside home directory"}, status_code=403)

    MAX_SIZE = 64 * 1024  # 64 KB per file
    context_parts: list[str] = []
    for fname in ("CLAUDE.md", "README.md"):
        fpath = os.path.join(path, fname)
        try:
            content = open(fpath, encoding="utf-8").read(MAX_SIZE)
            if content.strip():
                context_parts.append(f"=== {fname} ===\n{content.strip()}")
        except OSError:
            pass

    return JSONResponse({
        "path": path,
        "name": os.path.basename(path),
        "context": "\n\n".join(context_parts),
    })


@router.get("/", tags=['Core'])
async def index(request: Request):
    index_html = STATIC_DIR / "index.html"
    if index_html.is_file():
        return FileResponse(str(index_html), media_type="text/html")
    return JSONResponse({"error": "index.html not found"}, status_code=404)


@router.post("/chat", tags=['Chat'])
async def chat(request: Request):
    try:
        body = await request.json()
        user_message = str(body.get("message", "")).strip()
        file_paths: list[str] = body.get("files") or []
        primary_models: list[str] = body.get("primary_models") or []
        caps: dict[str, list[str]] = body.get("caps") or {}
        plan_mode: bool = bool(body.get("plan_mode", False))
        dev_mode: bool = bool(body.get("dev_mode", False))
        side_tools_enabled: dict[str, bool] = body.get("side_tools_enabled") or {}
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not user_message and not file_paths:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    # Record chat start for metrics
    import time as _w8_time
    _chat_start = _w8_time.time()

    # Scan user message for injection patterns
    if user_message:
        from web.prompt_guard import scan_message, get_guard_stats
        scan = scan_message(user_message, source="user")
        get_guard_stats().record(scan)
        if scan.blocked:
            _log.warning(
                "Prompt Guard blocked message (%d injection matches): %s",
                len(scan.matches),
                user_message[:100],
            )
            blocked_rules = [m.rule_id for m in scan.matches if m.severity == "block"]
            return JSONResponse(
                {
                    "error": "Message blocked by security filter",
                    "code": "PROMPT_INJECTION_DETECTED",
                    "rules": blocked_rules[:5],
                    "hint": "Ваше сообщение содержит паттерны, характерные для prompt injection. Если вы считаете это ошибкой, переформулируйте запрос.",
                },
                status_code=400,
            )
        if scan.warnings > 0:
            _log.info("Prompt Guard warnings in user message: %d matches", len(scan.matches))

    # Conversation history: client sends persistent session_id
    client_session_id = str(body.get("session_id", "")).strip()
    if not client_session_id:
        client_session_id = str(uuid.uuid4())

    # Source tracking: web / telegram / api
    source = str(body.get("source", "web")).strip()
    if not hasattr(request.app.state, "session_sources"):
        request.app.state.session_sources: dict[str, str] = {}
    request.app.state.session_sources[client_session_id] = source

    if not hasattr(request.app.state, "conversations"):
        request.app.state.conversations: dict[str, list[dict]] = {}
    if not hasattr(request.app.state, "session_profiles"):
        request.app.state.session_profiles: dict[str, str] = {}

    # Profile tracking will be done after user_ctx is available (see below)

    history = list(request.app.state.conversations.get(client_session_id, []))
    compacted = len(history) > 20
    if compacted:
        # ── PreCompact hook: извлечь критическую информацию перед сжатием ──
        try:
            compact_context = await invoke_pre_compact(
                session_id=session_id,
                messages=history,
            )
            if compact_context:
                history.insert(0, {"role": "system", "content": compact_context})
        except Exception:
            pass
        dropped = len(history) - 20
        history = history[-20:]

    settings = request.app.state.settings

    if file_paths:
        existing = [p for p in file_paths if os.path.isfile(p)]
        if existing:
            file_list = "\n".join(f"- {p}" for p in existing)
            file_hint = (
                f"\n\n[Uploaded files — read from disk if needed:]\n{file_list}"
            )
            user_message = (user_message or "analyze uploaded files") + file_hint

    cancel_event = asyncio.Event()
    session_id = str(uuid.uuid4())
    request.app.state.active_cancel_events[session_id] = cancel_event

    if not hasattr(request.app.state, "active_approval_events"):
        request.app.state.active_approval_events = {}
    session_approvals: dict[str, asyncio.Event] = {}
    request.app.state.active_approval_events[session_id] = session_approvals

    # ── Tier gating: clamp side models ──
    user_ctx = await get_user_context_optional(request)
    user_tier = user_ctx.tier if user_ctx else "free"

    # Track session ownership for auth on /cancel and /approve
    if user_ctx:
        if not hasattr(request.app.state, "session_owners"):
            request.app.state.session_owners: dict[str, str] = {}
        request.app.state.session_owners[session_id] = user_ctx.user_id

    # ── Profile tracking: use request profile_id or active profile ──
    profile_id = str(body.get("profile_id", "")).strip()
    if not profile_id and user_ctx and user_ctx.active_profile_id:
        profile_id = user_ctx.active_profile_id
    if profile_id:
        request.app.state.session_profiles[client_session_id] = profile_id

    # ── Load profile for HA (Hermes Agent) skills injection ──
    ha_enabled = False
    if profile_id and user_ctx:
        try:
            profile = get_profile(user_ctx.user_id, profile_id)
            if profile and profile.get("ha_enabled"):
                ha_enabled = True
        except Exception:
            pass

    # Фильтруем выключенные модели (off / выключено / none / пусто)
    def _is_active(m: str) -> bool:
        return bool(m and m.strip().lower() not in ("off", "выключено", "none"))

    active_models_raw = [m for m in primary_models if _is_active(m)]

    # ── Model gating ──
    if user_ctx and active_models_raw:
        from cost_guard import check_model_allowed_for_tier
        for m in active_models_raw:
            if not check_model_allowed_for_tier(m, user_tier):
                return JSONResponse(
                    {"error": f"Модель '{m}' недоступна на тарифе {user_tier}. "
                               "Перейдите на Business для доступа ко всем моделям.",
                     "allowed_models": "any"},
                    status_code=402,
                )

    active_models = clamp_side_models(user_tier, active_models_raw)

    # ── Daily budget pre-check ──
    if user_ctx:
        from cost_guard import get_daily_spend_tracker, COST_LIMITS
        tracker = get_daily_spend_tracker()
        config = COST_LIMITS.get(user_tier, COST_LIMITS["default"])
        spent = tracker.get_spend(user_ctx.user_id)
        budget = config.daily_budget_usd
        if budget > 0 and spent >= budget:
            return JSONResponse(
                {"error": f"Дневной бюджет (${budget:.2f}) исчерпан. Сброс в полночь UTC.",
                 "spent": round(spent, 4), "budget": budget, "period": "daily"},
                status_code=429,
            )

    # ── Dev Mode: require local agent connection ──
    dev_user_id: str | None = None
    if dev_mode:
        if not user_ctx:
            return JSONResponse({"error": "Dev Mode requires authentication. Register at /app/"}, status_code=401)
        from agent_manager import get_agent_manager
        mgr = get_agent_manager()
        if not mgr.is_connected(user_ctx.user_id):
            return JSONResponse({
                "error": "Dev Mode is ON but no local agent is connected.",
                "hint": "Install: curl -sSL https://raw.githubusercontent.com/strong-prog/AIModelJudge/main/services/hermes-local-agent/install.sh | bash",
                "agent_required": True,
            }, status_code=400)
        dev_user_id = user_ctx.user_id

    # ── Request complexity check ──
    if user_ctx:
        from cost_guard import check_request_complexity
        # tool_count=0: tools are selected by the agent, not the user
        allowed, err = check_request_complexity(user_message, 0, user_tier)
        if not allowed:
            return JSONResponse({"error": err}, status_code=400)

    system_prompt = _build_system_prompt(active_models if active_models else None, ha_enabled=ha_enabled, user_tier=user_tier)

    # ── Plan mode: inject planning instructions ──
    if plan_mode:
        system_prompt = (
            "РЕЖИМ ПЛАНИРОВАНИЯ (plan mode):\n"
            "1. СНАЧАЛА составь структурированный план из 3-7 пунктов через create_task в колонку tasks\n"
            "2. Каждый пункт — конкретное действие с измеримым результатом\n"
            "3. После создания всех пунктов плана — начни выполнение. Перед началом пункта вызови update_task(task_id, status='in_progress')\n"
            "4. После завершения пункта вызови update_task(task_id, status='completed', result='краткий итог')\n"
            "5. НЕ создавай новые пункты после начала выполнения\n"
            "6. В ответе пользователю кратко перечисли план перед выполнением\n\n"
        ) + system_prompt

    # ── Caps filtering: disable unchecked tools per model ──
    def _filter_tools(all_tools: list[dict], disabled: set[str]) -> list[dict]:
        """Исключает инструменты, чьи имена в disabled."""
        if not disabled:
            return list(all_tools)
        return [t for t in all_tools if t["name"] not in disabled]

    # Which tool IDs are considered "safe" (available to primary models)
    _SAFE_TOOL_IDS = {t["name"] for t in PRIMARY_TOOL_DEFINITIONS}
    # Map capability IDs to tool names they control
    _ALL_TOOL_NAMES = {t["name"] for t in TOOL_DEFINITIONS}

    def _disabled_tools(enabled_caps: list[str], is_primary: bool = False) -> set[str]:
        """Вычисляет множество отключённых инструментов.
        Если набор caps непуст — отключаем всё, что НЕ выбрано.
        Если пуст — всё разрешено (disabled = empty set).
        """
        enabled = set(enabled_caps)
        if not enabled:
            return set()  # ничего не выбрано = всё включено
        disabled = set()
        for name in _ALL_TOOL_NAMES:
            if name not in enabled:
                disabled.add(name)
        # Для primary моделей дополнительно исключаем опасные (не из PRIMARY_TOOL_DEFINITIONS)
        if is_primary:
            for name in _ALL_TOOL_NAMES:
                if name not in _SAFE_TOOL_IDS:
                    disabled.add(name)
        return disabled

    center_disabled = _disabled_tools(caps.get("center", []))
    left_disabled = _disabled_tools(caps.get("left", []), is_primary=True)
    right_disabled = _disabled_tools(caps.get("right", []), is_primary=True)

    tools = _filter_tools(TOOL_DEFINITIONS, center_disabled)
    primary_tools = _filter_tools(PRIMARY_TOOL_DEFINITIONS, left_disabled)
    # Для правой панели — те же инструменты, но если левая/правая отличаются,
    # используем более строгий набор (пересечение disabled)
    # Пока: обе панели получают одинаковый набор (left_disabled),
    # т.к. caps.left используется для всех primary
    right_tools = _filter_tools(PRIMARY_TOOL_DEFINITIONS, right_disabled)

    # AIModelJudge mode: 2+ активных моделей (center + ≥1 side) → side-queue + custom tool
    is_judge_mode = len(active_models) >= 2
    side_event_queue: asyncio.Queue | None = None
    extra_handlers: dict | None = None
    tools = _filter_tools(TOOL_DEFINITIONS, center_disabled)

    if is_judge_mode:
        side_event_queue = asyncio.Queue()
        set_side_event_queue(side_event_queue)
        # Side tools toggle: если выключены — side-модель без инструментов
        _st_left = side_tools_enabled.get("left", True)
        _st_right = side_tools_enabled.get("right", True)
        set_primary_tools(primary_tools if _st_left else None, panel="left")
        set_primary_tools(right_tools if _st_right else None, panel="right")
        extra_handlers = {"query_primary_models": handle_query_primary_models}
        tools = tools + [QUERY_PRIMARY_MODELS_TOOL]

    original_user_message = user_message

    # ── UserPromptSubmit hook: инжекция контекста ──
    try:
        injected = await invoke_user_prompt_submit(
            message=user_message,
            session_id=session_id,
            history=history if history else [],
        )
        if injected:
            user_message = user_message + "\n\n" + injected
    except Exception:
        pass

    # ── Token-aware cache routing: простые запросы через кэш ──
    _is_simple = (
        len(user_message) < 200
        and len(user_message) // 4 < 100
        and not file_paths
        and not dev_mode
        and not plan_mode
    )
    cache_hit = False
    if _is_simple:
        try:
            from web.model_cache import get_cache
            active_model = get_active_model_label()
            cached = get_cache().get(active_model, [{"role": "user", "content": user_message}])
            if cached:
                cache_hit = True
                cached_text = cached.get("text") or cached.get("content") or str(cached)
                cached_session = str(uuid.uuid4())

                async def sse_from_cache():
                    yield f"data: {json.dumps({'type': 'run.started', 'runId': f'run_cache_{cached_session[:8]}', 'sessionId': cached_session, 'input': original_user_message}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'prompt', 'text': original_user_message}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'text_start'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'text_token', 'token': cached_text}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'text_end'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'stop_reason': 'end_turn', 'cache_hit': True}, ensure_ascii=False)}\n\n"

                # Record metrics
                try:
                    duration = _w8_time.time() - _chat_start
                    from web.metrics import record_chat_request, record_chat_duration
                    record_chat_request(tier=user_tier, status="success")
                    record_chat_duration(duration)
                except Exception:
                    pass

                response = StreamingResponse(
                    sse_from_cache(),
                    media_type="text/event-stream",
                )
                response.headers["Cache-Control"] = "no-cache"
                response.headers["X-Accel-Buffering"] = "no"
                response.headers["X-Stream-Session"] = cached_session
                response.headers["X-Cache-Hit"] = "true"
                return response
        except Exception:
            pass

    async def sse_generator():
        nonlocal user_message, history
        response_text_parts: list[str] = []
        final_usage: dict = {}
        final_error: str | None = None

        # ── Heartbeat: защита от разрыва соединения ──
        heartbeat_queue: asyncio.Queue = asyncio.Queue()

        async def heartbeat_loop():
            while not cancel_event.is_set():
                try:
                    await asyncio.wait_for(cancel_event.wait(), timeout=10)
                    break
                except asyncio.TimeoutError:
                    if not cancel_event.is_set():
                        await heartbeat_queue.put({"type": "streaming_heartbeat"})

        heartbeat_task = asyncio.create_task(heartbeat_loop())

        try:
            # ── Hermes SDK: run.started ──
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            yield f"data: {json.dumps({'type': 'run.started', 'runId': run_id, 'sessionId': session_id, 'input': original_user_message}, ensure_ascii=False)}\n\n"

            # ── SessionStart hook (fire-and-forget) ──
            fire_session_start(session_id=session_id, session_key=client_session_id)

            # ── Hermes SDK: compact_notification — уведомление о компактификации контекста ──
            if compacted:
                yield f"data: {json.dumps({'type': 'compact_notification', 'dropped_messages': dropped, 'remaining_messages': len(history), 'trigger': 'auto'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'summary_received', 'dropped_messages': dropped, 'remaining_messages': len(history), 'summary': f'Контекст сжат: удалены {dropped} старых сообщений, сохранены последние {len(history)}'}, ensure_ascii=False)}\n\n"

            # ── Отправляем исходный промпт для отображения в UI ──
            yield f"data: {json.dumps({'type': 'prompt', 'text': original_user_message}, ensure_ascii=False)}\n\n"

            # ── Plan mode: фазовый переход ──
            if plan_mode:
                yield f"data: {json.dumps({'type': 'phase', 'phase': 'plan'}, ensure_ascii=False)}\n\n"

            # ── Agent calls query_primary_models itself after exploration (Phase 1→2) ──

            # ── Run agent ──
            final_stop_reason = "end_turn"
            agent_iter = agentic_stream(
                system_prompt=system_prompt,
                user_message=user_message,
                cancel_event=cancel_event,
                hermes_messages_url=settings.hermes_messages_url,
                hermes_key=settings.hermes_api_key,
                tools=tools,
                session_id=session_id,
                approval_registry=request.app.state.active_approval_events,
                hermes_chat_url=settings.hermes_url,
                side_event_queue=side_event_queue,
                extra_tool_handlers=extra_handlers,
                history=history if history else None,
                user_id=dev_user_id,
            ).__aiter__()

            async def _drain_side_events():
                """Yield any pending side panel events from queue."""
                if side_event_queue is None:
                    return
                while not side_event_queue.empty():
                    try:
                        evt = side_event_queue.get_nowait()
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                        side_event_queue.task_done()
                    except asyncio.QueueEmpty:
                        break

            async def _get_side_event_or_none():
                """Get one side event with short timeout, or None."""
                if side_event_queue is None:
                    return None
                try:
                    return await asyncio.wait_for(side_event_queue.get(), timeout=0.3)
                except asyncio.TimeoutError:
                    return None

            agent_task = None  # Persistent across iterations — don't cancel
            session_user_id_set = False  # Ensure session.user_id is set once

            while not cancel_event.is_set():
                # Drain pending side events first (real-time streaming to panels)
                async for side_payload in _drain_side_events():
                    yield side_payload

                # Create agent task lazily (first iteration or after previous one completed)
                if agent_task is None:
                    agent_task = asyncio.create_task(agent_iter.__anext__())

                # Race agent vs heartbeat vs side events
                heartbeat_next = asyncio.create_task(heartbeat_queue.get())
                side_next = asyncio.create_task(_get_side_event_or_none())
                done, pending = await asyncio.wait(
                    [agent_task, heartbeat_next, side_next],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Process side event (arrived first or together with others)
                if side_next in done:
                    se = side_next.result()
                    if se is not None:
                        yield f"data: {json.dumps(se, ensure_ascii=False)}\n\n"
                        side_event_queue.task_done()
                elif side_next in pending:
                    side_next.cancel()

                # Process heartbeat
                if heartbeat_next in done:
                    hb = heartbeat_next.result()
                    yield f"data: {json.dumps(hb, ensure_ascii=False)}\n\n"
                elif heartbeat_next in pending:
                    heartbeat_next.cancel()

                # Process agent event (only if it completed)
                if agent_task not in done:
                    continue  # Agent still busy (tool execution) — loop back, try again

                # Agent yielded — process the event
                try:
                    event = agent_task.result()
                except StopAsyncIteration:
                    break
                agent_task = None  # Reset to recreate in next iteration

                # ── Set session.user_id on first event ──
                if not session_user_id_set and user_ctx:
                    _sid = session_id
                    _uid = user_ctx.user_id
                    try:
                        import sqlite3 as _sql3
                        _c = _sql3.connect(str(_STATE_DB))
                        _c.execute("UPDATE sessions SET user_id = ? WHERE id = ?", (_uid, _sid))
                        _c.commit()
                        _c.close()
                        session_user_id_set = True
                    except Exception:
                        pass

                if cancel_event.is_set():
                    final_stop_reason = "cancelled"
                    yield f"data: {json.dumps({'type': 'done', 'stop_reason': 'cancelled'}, ensure_ascii=False)}\n\n"
                    break
                if event.get("type") == "text_token":
                    response_text_parts.append(str(event.get("token", "")))
                if event.get("type") == "error":
                    final_error = event.get("message", "") or final_error
                if event.get("type") == "done":
                    final_stop_reason = event.get("stop_reason", "end_turn")
                    final_usage = event.get("usage", {})
                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n"

            # Drain remaining side events after agent completes
            async for side_payload in _drain_side_events():
                yield side_payload
            while not heartbeat_queue.empty():
                try:
                    hb = heartbeat_queue.get_nowait()
                    yield f"data: {json.dumps(hb, ensure_ascii=False)}\n\n"
                except asyncio.QueueEmpty:
                    break

            # ── Hermes SDK: run.completed / run.failed ──
            response_text = "".join(response_text_parts).strip()
            if final_stop_reason in ("end_turn",):
                yield f"data: {json.dumps({'type': 'run.completed', 'runId': run_id, 'sessionId': session_id, 'stopReason': final_stop_reason, 'usage': final_usage, 'messages': [{'role': 'user', 'content': original_user_message}, {'role': 'assistant', 'content': response_text[:4000]}]}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'run.failed', 'runId': run_id, 'sessionId': session_id, 'stopReason': final_stop_reason, 'error': final_error or 'Неизвестная ошибка', 'usage': final_usage}, ensure_ascii=False)}\n\n"

            # ── Notification hook (fire-and-forget) ──
            fire_notification(
                session_id=session_id,
                message=original_user_message,
                stop_reason=final_stop_reason,
            )

            # Store exchange in conversation history (only for successful runs)
            if final_stop_reason == "end_turn":
                response_text = "".join(response_text_parts).strip()
                if response_text:
                    history.append({"role": "user", "content": original_user_message})
                    history.append({"role": "assistant", "content": response_text[:4000]})
                    if len(history) > 20:
                        history = history[-20:]
                    request.app.state.conversations[client_session_id] = history
        finally:
            # ── Stop hook (fire-and-forget) ──
            fire_stop(
                session_id=session_id,
                messages=history if history else [],
                client_session_id=client_session_id,
            )
            # ── Self-Learning: анализ сессии на кандидата навыка ──
            try:
                from web.skill_analyzer import analyze_session as _analyze_session
                asyncio.create_task(_analyze_session(session_id))
            except Exception:
                pass
            # ── Cost tracking: log API usage ──
            if user_ctx and final_usage:
                try:
                    from cost_guard import log_api_usage
                    input_tokens = final_usage.get("input_tokens", 0) or 0
                    output_tokens = final_usage.get("output_tokens", 0) or 0
                    model_label = get_active_model_label()
                    log_api_usage(
                        user_id=user_ctx.user_id,
                        session_id=session_id,
                        model_name=model_label,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        tier=user_tier,
                    )
                except Exception:
                    pass
            try:
                heartbeat_task.cancel()
            except NameError:
                pass
            set_side_event_queue(None)
            request.app.state.active_cancel_events.pop(session_id, None)
            request.app.state.active_approval_events.pop(session_id, None)

            # Record chat metrics with actual stream status
            try:
                duration = _w8_time.time() - _chat_start
                from web.metrics import record_chat_request, record_chat_duration
                if final_stop_reason == "cancelled":
                    record_chat_request(tier=user_tier, status="cancelled")
                elif final_error:
                    record_chat_request(tier=user_tier, status="error")
                else:
                    record_chat_request(tier=user_tier, status="success")
                record_chat_duration(duration)
            except Exception:
                pass

    response = StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["X-Stream-Session"] = session_id
    return response


@router.get("/model/current", tags=['Models'])
async def get_current_model():
    label = get_active_model_label()
    return {
        "model": label,
        "display": get_display_name(label),
        "other": get_other_model_label(),
        "other_display": get_display_name(get_other_model_label()),
    }


@router.get("/model/list", tags=['Models'])
async def list_models():
    return {"models": list_available_models()}


@router.post("/model/switch", tags=['Models'])
async def switch_active_model(request: Request):
    try:
        body = await request.json()
        new_model = str(body.get("model", "")).strip()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not new_model:
        return JSONResponse({"error": "Model not specified"}, status_code=400)

    try:
        switch_model(new_model)
        from web.model_cache import invalidate_cache
        invalidate_cache()
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    user_ctx = await get_user_context_optional(request)
    log_audit(user_ctx.user_id if user_ctx else None, "model_switch", "model", f"model={new_model}", request.client.host if request.client else None)

    return {
        "ok": True,
        "model": new_model,
        "display": get_display_name(new_model),
    }


@router.post("/cancel", tags=['Chat'])
async def cancel(request: Request, user=Depends(get_user_context)):
    session_id = request.headers.get("X-Stream-Session", "")
    if not session_id:
        return JSONResponse({"ok": False, "error": "No session"}, status_code=400)

    session_owners: dict = getattr(request.app.state, "session_owners", {})
    if session_id in session_owners and session_owners[session_id] != user.user_id:
        return JSONResponse({"ok": False, "error": "Not your session"}, status_code=403)

    cancel_event = request.app.state.active_cancel_events.get(session_id)
    if cancel_event:
        cancel_event.set()
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "Session not found"}, status_code=404)


@router.post("/approve", tags=['Chat'])
async def approve(request: Request, user=Depends(get_user_context)):
    try:
        body = await request.json()
        tool_use_id = str(body.get("tool_use_id", "")).strip()
        decision = str(body.get("decision", "deny")).strip()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if decision not in ("allow", "deny", "allow_all"):
        return JSONResponse({"error": "Invalid decision"}, status_code=400)
    if not tool_use_id:
        return JSONResponse({"error": "tool_use_id required"}, status_code=400)

    session_id = request.headers.get("X-Stream-Session", "")
    if not session_id:
        return JSONResponse({"ok": False, "error": "No session"}, status_code=400)

    session_owners: dict = getattr(request.app.state, "session_owners", {})
    if session_id in session_owners and session_owners[session_id] != user.user_id:
        return JSONResponse({"ok": False, "error": "Not your session"}, status_code=403)

    approval_registry: dict = getattr(
        request.app.state, "active_approval_events", {}
    )
    session_approvals = approval_registry.get(session_id, {})
    event = session_approvals.get(tool_use_id)

    if not event:
        return JSONResponse(
            {"ok": False, "error": "Approval not found (already resolved?)"},
            status_code=404,
        )

    event.decision = decision
    event.set()
    return JSONResponse({"ok": True, "decision": decision})


@router.post("/upload", tags=['Core'])
async def upload(request: Request, user=Depends(get_user_context)):
    session_id = request.headers.get("X-Local-Session", "default")[:16]
    upload_dir = UPLOAD_DIR / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    form = await request.form()
    uploaded: list[dict] = []

    for field_name in form:
        file_obj = form[field_name]
        if not hasattr(file_obj, "filename"):
            continue
        filename = file_obj.filename or "unnamed"
        safe_name = Path(filename).name
        dest = upload_dir / safe_name
        content = await file_obj.read()
        if len(content) > 50 * 1024 * 1024:
            return JSONResponse(
                {"error": f"File {safe_name} too large (max 50 MB)"}, status_code=413
            )
        dest.write_bytes(content)
        uploaded.append({
            "name": safe_name,
            "size": len(content),
            "path": str(dest),
        })

    return JSONResponse({"ok": True, "files": uploaded})


# ═══════════════════════════════════════════════════════════════════════
# Skills
# ═══════════════════════════════════════════════════════════════════════

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _SKILLS_BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _SKILLS_BASE = Path.home() / ".hermes-aimodeljudge"

_SKILL_DIRS: list[tuple[str, Path]] = [
    ("local", _SKILLS_BASE / "skills"),
    ("shared", Path.home() / ".hermes" / "skills"),
    ("ecc", Path.home() / ".hermes" / "skills" / "ecc-imports"),
]

_SOURCE_LABELS = {"local": "Локальный", "shared": "Общий", "ecc": "ECC"}


def _parse_skill_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        kv = re.match(r"^(\w[\w\s]*?):\s*(.*)", line)
        if kv:
            key = kv.group(1).strip()
            val = kv.group(2).strip().strip('"').strip("'")
            if val:
                result[key] = val
    return result


@router.get("/skills/list", tags=['Skills'])
async def list_skills(user: UserContext = Depends(get_user_context_optional)):
    skills: list[dict] = []
    seen: set[str] = set()
    for source, base_dir in _SKILL_DIRS:
        if not base_dir.is_dir():
            continue
        for skill_dir in sorted(base_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            fm = _parse_skill_frontmatter(content)
            name = fm.get("name", skill_dir.name)
            if name in seen:
                continue
            seen.add(name)
            # Метрики из skills.json
            from web.skills_manager import get_metrics as _gm
            metrics = _gm(str(skill_md))
            hot_score = metrics.get("hot_score", 0.0)
            is_hot = metrics.get("is_hot", False)
            skills.append({
                "name": name,
                "description": fm.get("description", ""),
                "source": source,
                "source_label": _SOURCE_LABELS.get(source, source),
                "path": str(skill_md),
                "origin": fm.get("origin", ""),
                "call_count": metrics.get("call_count", 0),
                "upvotes": metrics.get("upvotes", 0),
                "downvotes": metrics.get("downvotes", 0),
                "hot_score": hot_score,
                "is_hot": is_hot,
            })
    # Разделяем на hot_skills (топ-10) и остальные
    skills.sort(key=lambda s: s.get("hot_score", 0), reverse=True)
    hot_skills = [s for s in skills if s["is_hot"]][:10]
    return JSONResponse({"skills": skills, "hot_skills": hot_skills})


@router.get("/skills/content", tags=['Skills'])
async def get_skill_content(path: str = "", user: UserContext = Depends(get_user_context_optional)):
    skill_path = Path(path)
    allowed = False
    for _, base_dir in _SKILL_DIRS:
        if base_dir.is_dir() and skill_path.is_relative_to(base_dir):
            allowed = True
            break
    if not allowed:
        return JSONResponse({"error": "Access denied"}, status_code=403)
    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError:
        return JSONResponse({"error": "File not found"}, status_code=404)
    fm = _parse_skill_frontmatter(content)
    return JSONResponse({
        "name": fm.get("name", skill_path.parent.name),
        "content": content,
    })


@router.post("/skills/create", tags=['Skills'])
async def create_skill(data: Request):
    """Создаёт новый навык из тела запроса."""
    try:
        body = await data.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    content = str(body.get("content", ""))
    tools = body.get("tools")

    if isinstance(tools, list):
        tools = [str(t) for t in tools]
    else:
        tools = None

    from web.skills_manager import create as create_skill_file, validate_name

    err = validate_name(name)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    if not description:
        return JSONResponse({"error": "Описание навыка не может быть пустым"}, status_code=400)

    # ── Tier gating ──
    user_ctx = await get_user_context_optional(data)
    tier = user_ctx.tier if user_ctx else "free"
    max_skills = get_tier_limit(tier, "max_skills")
    if isinstance(max_skills, int):
        local_dir = Path.home() / ".hermes-aimodeljudge" / "skills"
        if local_dir.is_dir():
            existing = [d for d in local_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if len(existing) >= max_skills:
                return JSONResponse(
                    {"error": f"Лимит навыков ({max_skills}) исчерпан. Перейдите на Pro/Business для создания дополнительных навыков"},
                    status_code=402,
                )

    try:
        target = create_skill_file(name, description, content, tools)
        log_audit(user_ctx.user_id if user_ctx else None, "skill_create", "skills", f"name={name}", data.client.host if data.client else None)
        return JSONResponse({
            "ok": True,
            "name": name,
            "path": str(target),
        })
    except FileExistsError:
        return JSONResponse({"error": f"Навык «{name}» уже существует"}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/skills/candidate", tags=['Skills'])
async def get_skill_candidate(session_id: str = ""):
    """Возвращает кандидата навыка для сессии (если анализ завершён)."""
    if not session_id:
        return JSONResponse({"candidate": None})
    try:
        from web.skill_analyzer import get_candidate as _gc
        candidate = _gc(session_id)
        return JSONResponse({"candidate": candidate})
    except Exception:
        return JSONResponse({"candidate": None})


@router.post("/skills/create-from-session", tags=['Skills'])
async def create_skill_from_session(data: Request):
    """Создаёт навык из кандидата сессии."""
    try:
        body = await data.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    session_id = str(body.get("session_id", "")).strip()
    if not session_id:
        return JSONResponse({"error": "session_id обязателен"}, status_code=400)

    try:
        from web.skill_analyzer import get_candidate as _gc, remove_candidate as _rc

        candidate = _gc(session_id)
        if not candidate:
            return JSONResponse({"error": "Кандидат не найден для этой сессии"}, status_code=404)

        name = str(body.get("name") or candidate["suggested_name"]).strip().lower()
        description = str(body.get("description") or candidate["description"]).strip()
        content = str(body.get("content") or candidate["content"])

        from web.skills_manager import create as _create_skill
        from web.tiers import get_tier_limit as _gtl, require_tier as _rt

        # Проверка лимита навыков по tier
        tier = getattr(data.state, "user", None)
        tier_val = tier.tier if tier else "free"
        max_skills = _gtl(tier_val, "max_skills")
        current_count = len([d for d in Path.home().joinpath(".hermes-aimodeljudge", "skills").iterdir() if d.is_dir()])
        if current_count >= max_skills:
            return JSONResponse(
                {"error": f"Достигнут лимит навыков ({max_skills}) для уровня {tier_val}. Перейдите на Pro/Business."},
                status_code=402,
            )

        target = _create_skill(
            name=name,
            description=description,
            content=content,
            tools=candidate.get("tools_used", []),
        )

        _rc(session_id)
        return JSONResponse({"ok": True, "name": name, "path": str(target)})
    except FileExistsError:
        return JSONResponse({"error": f"Навык «{name}» уже существует"}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/skills/rate", tags=['Skills'])
async def rate_skill(data: Request):
    """Записывает рейтинг навыка (up/down)."""
    try:
        body = await data.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    path = str(body.get("path", "")).strip()
    rating = str(body.get("rating", "")).strip().lower()

    if not path:
        return JSONResponse({"error": "path обязателен"}, status_code=400)
    if rating not in ("up", "down"):
        return JSONResponse({"error": "rating должен быть 'up' или 'down'"}, status_code=400)

    # Проверка что путь в допустимых директориях
    skill_path = Path(path)
    allowed = False
    for _, base_dir in _SKILL_DIRS:
        if base_dir.is_dir() and skill_path.is_relative_to(base_dir):
            allowed = True
            break
    if not allowed:
        return JSONResponse({"error": "Access denied"}, status_code=403)

    from web.skills_manager import record_rating as record

    metrics = record(path, rating)
    return JSONResponse({
        "ok": True,
        "call_count": metrics.get("call_count", 0),
        "upvotes": metrics.get("upvotes", 0),
        "downvotes": metrics.get("downvotes", 0),
    })


@router.post("/skills/auto-rank", tags=['Skills'])
async def auto_rank_skills():
    """Пересчитывает hot_score для всех навыков. Возвращает отсортированный список."""
    try:
        from web.skills_manager import SkillRanker
        results = SkillRanker.rank_all()
        ranked = [
            {
                "path": r.path,
                "hot_score": r.hot_score,
                "is_hot": r.is_hot,
                "call_count": r.call_count,
                "upvotes": r.upvotes,
                "downvotes": r.downvotes,
                "suggest_delete": r.suggest_delete,
            }
            for r in results
        ]
        promoted = sum(1 for r in results if r.is_hot)
        demoted = sum(1 for r in results if not r.is_hot and r.hot_score > 0)
        suggest_delete = sum(1 for r in results if r.suggest_delete)
        return JSONResponse({
            "ranked": ranked,
            "promoted": promoted,
            "demoted": demoted,
            "suggest_delete": suggest_delete,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/skills/use", tags=['Skills'])
async def record_skill_use(data: Request):
    """Записывает использование навыка (увеличивает call_count)."""
    try:
        body = await data.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    path = str(body.get("path", "")).strip()
    if not path:
        return JSONResponse({"error": "path обязателен"}, status_code=400)

    skill_path = Path(path)
    allowed = False
    for _, base_dir in _SKILL_DIRS:
        if base_dir.is_dir() and skill_path.is_relative_to(base_dir):
            allowed = True
            break
    if not allowed:
        return JSONResponse({"error": "Access denied"}, status_code=403)

    from web.skills_manager import inc_call_count as _icc
    _icc(path)
    from web.skills_manager import get_metrics as _gm
    metrics = _gm(path)
    return JSONResponse({
        "path": path,
        "call_count": metrics.get("call_count", 0),
        "upvotes": metrics.get("upvotes", 0),
        "downvotes": metrics.get("downvotes", 0),
        "hot_score": metrics.get("hot_score"),
    })


@router.get("/skills/graph", tags=['Skills'])
async def get_skills_graph():
    """Возвращает граф навыков: узлы (навыки) и рёбра (shared tools)."""
    import re

    from web.skills_manager import _load_metrics, calculate_hot_score

    # Собираем узлы из skills.json + парсим tools из SKILL.md
    metrics = _load_metrics()
    nodes: list[dict] = []
    skill_tools: dict[str, set[str]] = {}

    for path, entry in metrics.items():
        skill_dir = Path(path)
        name = skill_dir.name
        skill_file = skill_dir / "SKILL.md" if skill_dir.is_dir() else skill_dir
        tools: set[str] = set()

        if skill_file.is_file():
            try:
                content = skill_file.read_text(encoding="utf-8")
                # Извлекаем `tool_name` из Markdown
                tools = set(re.findall(r"`([a-z_]+)`", content))
            except OSError:
                pass

        skill_tools[path] = tools
        nodes.append({
            "id": path,
            "name": name,
            "path": path,
            "hot_score": entry.get("hot_score", calculate_hot_score(entry)),
            "is_hot": entry.get("is_hot", False),
            "call_count": entry.get("call_count", 0),
            "upvotes": entry.get("upvotes", 0),
            "downvotes": entry.get("downvotes", 0),
            "description": "",
        })

    # Строим рёбра: shared tools >= 2 между навыками
    edges: list[dict] = []
    paths = list(skill_tools.keys())
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            tools_a = skill_tools[paths[i]]
            tools_b = skill_tools[paths[j]]
            shared = tools_a & tools_b
            if len(shared) >= 2:
                max_tools = max(len(tools_a), len(tools_b), 1)
                weight = round(len(shared) / max_tools, 3)
                edges.append({
                    "source": paths[i],
                    "target": paths[j],
                    "type": "shared_tools",
                    "weight": weight,
                })

    return JSONResponse({"nodes": nodes, "edges": edges})


@router.post("/diff", tags=['Diff'])
async def compute_diff(data: Request):
    """Вычисляет unified diff между old_content и new_content.

    Принимает JSON {file_path, old_content, new_content}.
    Возвращает структурированный diff: hunks с типами строк.
    """
    import difflib

    try:
        body = await data.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    file_path = str(body.get("file_path", "")).strip()
    old_content = str(body.get("old_content", ""))
    new_content = str(body.get("new_content", ""))

    if not file_path:
        return JSONResponse({"error": "file_path обязателен"}, status_code=400)
    if not old_content and not new_content:
        return JSONResponse({"error": "old_content и new_content не могут быть оба пустыми"}, status_code=400)

    # Генерируем unified diff с 3 строками контекста
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=file_path, tofile=file_path,
        n=3,
    ))

    if not diff_lines:
        return JSONResponse({"file_path": file_path, "hunks": []})

    # Парсим unified diff в структурированные hunks
    hunks: list[dict] = []
    current_hunk: dict | None = None

    for line in diff_lines:
        if line.startswith("@@"):
            if current_hunk is not None:
                hunks.append(current_hunk)
            current_hunk = {"header": line.rstrip("\n"), "lines": []}
        elif current_hunk is not None:
            stripped = line.rstrip("\n")
            if line.startswith("+"):
                current_hunk["lines"].append({"type": "add", "content": stripped})
            elif line.startswith("-"):
                current_hunk["lines"].append({"type": "remove", "content": stripped})
            else:
                current_hunk["lines"].append({"type": "keep", "content": stripped})

    if current_hunk is not None:
        hunks.append(current_hunk)

    return JSONResponse({
        "file_path": file_path,
        "hunks": hunks,
    })


# ═══════════════════════════════════════════════════════════════════════
# Kanban
# ═══════════════════════════════════════════════════════════════════════

_VALID_KANBAN_STATUSES = frozenset({"pending", "in_progress", "review", "completed", "archived"})


@router.get("/kanban/tasks", tags=['Kanban'])
async def list_kanban_tasks(user: UserContext = Depends(get_user_context)):
    tasks = list_tasks(user.user_id)
    return JSONResponse({"tasks": tasks})


@router.post("/kanban/tasks", tags=['Kanban'])
async def create_kanban_task(request: Request, user: UserContext = Depends(get_user_context)):
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    title = str(body.get("title", "")).strip()
    if not title:
        return JSONResponse({"error": "Title required"}, status_code=400)
    status = str(body.get("status", "pending")).strip()
    if status not in _VALID_KANBAN_STATUSES:
        return JSONResponse(
            {"error": f"Invalid status. Must be one of: {', '.join(sorted(_VALID_KANBAN_STATUSES))}"},
            status_code=400,
        )
    desc = str(body.get("body", "")).strip()
    priority = int(body.get("priority", 0))
    try:
        task_id = create_task(user.user_id, title, body=desc, status=status, priority=priority)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "task": {"id": task_id, "title": title, "status": status, "priority": priority}})


@router.patch("/kanban/tasks/{task_id}", tags=['Kanban'])
async def update_kanban_task(task_id: str, request: Request, user: UserContext = Depends(get_user_context)):
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    allowed = {"status", "title", "body", "priority", "assignee", "result"}
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)
    ok = update_task(user.user_id, task_id, **fields)
    if not ok:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse({"ok": True})


@router.delete("/kanban/tasks/{task_id}", tags=['Kanban'])
async def delete_kanban_task(task_id: str, user: UserContext = Depends(get_user_context)):
    ok = delete_task(user.user_id, task_id)
    if not ok:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse({"ok": True})


# ═══════════════════════════════════════════════════════════════════════
# Sessions
# ═══════════════════════════════════════════════════════════════════════

_STATE_DB = Path.home() / ".hermes-aimodeljudge" / "state.db"


def _state_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_STATE_DB))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/sessions/recent", tags=['Sessions'])
async def list_recent_sessions(limit: int = 20, user: UserContext = Depends(get_user_context)):
    sessions = list_sessions(user.user_id, limit=limit)
    return JSONResponse({"sessions": sessions})


@router.get("/sessions/search", tags=['Sessions'])
async def search_sessions(q: str = "", limit: int = 20, user: UserContext = Depends(get_user_context)):
    sessions = search_sessions(user.user_id, q, limit=limit)
    return JSONResponse({"sessions": sessions, "query": q})


@router.get("/sessions/{session_id}", tags=['Sessions'])
async def get_session(session_id: str, user: UserContext = Depends(get_user_context)):
    result = dl_get_session(user.user_id, session_id)
    if result is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(result)


# ═══════════════════════════════════════════════════════════════════════
# Memory Graph
# ═══════════════════════════════════════════════════════════════════════

_MEMORY_DB = Path.home() / ".memory-mcp" / "memory.db"


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_MEMORY_DB))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/memory/graph", tags=['Memory'])
async def get_memory_graph(project_id: str = ""):
    conn = _memory_conn()
    try:
        if project_id:
            rows = conn.execute(
                "SELECT id, content, memory_type, is_hot, trust_score, access_count, "
                "importance_score, category, created_at "
                "FROM memories WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, content, memory_type, is_hot, trust_score, access_count, "
                "importance_score, category, created_at "
                "FROM memories ORDER BY id"
            ).fetchall()
        nodes = []
        for r in rows:
            d = dict(r)
            d["is_hot"] = bool(d["is_hot"])
            tag_rows = conn.execute(
                "SELECT tag FROM memory_tags WHERE memory_id = ?", (d["id"],)
            ).fetchall()
            d["tags"] = [t[0] for t in tag_rows]
            nodes.append(d)

        edge_rows = conn.execute(
            "SELECT from_memory_id, to_memory_id, relation_type FROM memory_relationships"
        ).fetchall()
        edges = [{"source": r[0], "target": r[1], "type": r[2]} for r in edge_rows]
    finally:
        conn.close()
    return JSONResponse({"nodes": nodes, "edges": edges})


# ═══════════════════════════════════════════════════════════════════════
# Token Analytics
# ═══════════════════════════════════════════════════════════════════════

_ANALYTICS_DB = Path.home() / ".hermes" / "state.db"


@router.get("/analytics/tokens", tags=['Analytics'])
async def get_token_analytics(days: int = 14):
    conn = sqlite3.connect(str(_ANALYTICS_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT date(started_at, 'unixepoch') as day, "
            "COUNT(*) as sessions, "
            "SUM(input_tokens) as input_tokens, "
            "SUM(output_tokens) as output_tokens, "
            "SUM(cache_read_tokens) as cache_read_tokens, "
            "SUM(estimated_cost_usd) as estimated_cost_usd "
            "FROM sessions "
            "WHERE started_at >= unixepoch('now', ? || ' days') "
            "GROUP BY day ORDER BY day",
            (f"-{min(max(days, 1), 90)}",),
        ).fetchall()
        days_data = [dict(r) for r in rows]

        totals = conn.execute(
            "SELECT SUM(input_tokens) as input_tokens, "
            "SUM(output_tokens) as output_tokens, "
            "SUM(estimated_cost_usd) as estimated_cost_usd "
            "FROM sessions"
        ).fetchone()
    finally:
        conn.close()

    return JSONResponse({
        "days": days_data,
        "totals": {
            "input_tokens": totals["input_tokens"] or 0,
            "output_tokens": totals["output_tokens"] or 0,
            "estimated_cost_usd": round(totals["estimated_cost_usd"] or 0, 2),
        },
    })


# ── Usage (cost tracking) ──

@router.get("/api/usage/current", tags=['Analytics'])
async def api_usage_current(user=Depends(get_user_context)):
    """Текущие расходы пользователя: дневной/месячный бюджет."""
    from cost_guard import get_daily_spend_tracker, get_monthly_counter, COST_LIMITS

    tracker = get_daily_spend_tracker()
    daily_spend = tracker.get_spend(user.user_id)

    counter = get_monthly_counter()
    monthly_count = counter.get_count(user.user_id)

    config = COST_LIMITS.get(user.tier, COST_LIMITS["default"])

    # Today's usage breakdown by model
    state_db_path = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db_path))
    conn.row_factory = sqlite3.Row
    try:
        by_model_rows = conn.execute(
            "SELECT model_name, SUM(input_tokens) as total_input, "
            "SUM(output_tokens) as total_output, "
            "SUM(estimated_cost_usd) as total_cost "
            "FROM api_usage_log "
            "WHERE user_id = ? AND date(timestamp) = date('now') "
            "GROUP BY model_name",
            (user.user_id,),
        ).fetchall()
        by_model = [dict(r) for r in by_model_rows]
    finally:
        conn.close()

    return JSONResponse({
        "daily_spend_usd": round(daily_spend, 4),
        "daily_budget_usd": config.daily_budget_usd,
        "daily_percent": round(daily_spend / config.daily_budget_usd * 100, 1)
            if config.daily_budget_usd > 0 else 0,
        "monthly_requests": monthly_count,
        "monthly_request_limit": config.monthly_requests,
        "monthly_percent": round(monthly_count / config.monthly_requests * 100, 1)
            if config.monthly_requests > 0 else 0,
        "tier": user.tier,
        "by_model_today": by_model,
    })


@router.get("/api/usage/daily", tags=['Analytics'])
async def api_usage_daily(admin=Depends(require_admin)):
    """Админ: дневные расходы всех пользователей."""
    state_db_path = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT u.email, u.tier, "
            "COALESCE(SUM(ul.estimated_cost_usd), 0) as today_cost, "
            "COUNT(DISTINCT ul.session_id) as sessions_today "
            "FROM users u "
            "LEFT JOIN api_usage_log ul ON u.id = ul.user_id "
            "AND date(ul.timestamp) = date('now') "
            "GROUP BY u.id ORDER BY today_cost DESC"
        ).fetchall()
    finally:
        conn.close()

    return JSONResponse({"users": [dict(r) for r in rows]})


# ── Benchmarks ──

@router.get("/benchmarks/stats", tags=['Analytics'])
async def get_benchmark_stats(days: int = 7):
    from benchmarks import get_tracker
    return JSONResponse(get_tracker().stats(days=days))


@router.get("/benchmarks/recent", tags=['Analytics'])
async def get_benchmark_recent(limit: int = 50):
    from benchmarks import get_tracker
    return JSONResponse(get_tracker().recent(limit=limit))


@router.get("/analytics/token-efficiency", tags=['Analytics'])
async def get_token_efficiency(days: int = 7):
    from benchmarks import get_tracker
    recent = get_tracker().recent(limit=200)
    # Aggregate tokens per phase and cache hit stats from recent records
    total_requests = 0
    cache_hits = 0
    phase_tokens: dict[str, dict] = {}  # phase -> {count, total_in, total_out}
    for r in recent:
        total_requests += 1
        if r.get("cache_hit"):
            cache_hits += 1
        tpp = r.get("tokens_per_phase") or {}
        for phase, tokens in tpp.items():
            if phase not in phase_tokens:
                phase_tokens[phase] = {"count": 0, "total_in": 0, "total_out": 0}
            phase_tokens[phase]["count"] += 1
            if isinstance(tokens, dict):
                phase_tokens[phase]["total_in"] += tokens.get("in", 0) or 0
                phase_tokens[phase]["total_out"] += tokens.get("out", 0) or 0
            elif isinstance(tokens, (int, float)):
                phase_tokens[phase]["total_in"] += int(tokens)
    return JSONResponse({
        "total_requests": total_requests,
        "cache_hit_rate": round(cache_hits / max(total_requests, 1), 3),
        "tokens_per_phase": {k: {
            "count": v["count"],
            "avg_tokens_in": round(v["total_in"] / max(v["count"], 1)),
            "avg_tokens_out": round(v["total_out"] / max(v["count"], 1)),
        } for k, v in phase_tokens.items()},
    })


# ── Model Cache Stats ──

@router.get("/model/cache/stats", tags=['Models'])
async def get_model_cache_stats():
    from model_cache import get_cache, get_semantic_cache, get_tool_cache
    mc = get_cache()
    sc = get_semantic_cache()
    tc = get_tool_cache()
    return JSONResponse({
        "model": {
            "size": len(mc),
            "max_size": mc._max,
            "base_ttl_s": mc._ttl,
            "effective_ttl_s": round(mc.effective_ttl, 1),
            "hit_count": mc.hit_count,
            "miss_count": mc.miss_count,
            "hit_rate": round(mc.hit_rate, 3),
        },
        "semantic": {
            "size": len(sc),
            "max_size": sc._max,
            "threshold": sc._threshold,
            "model_available": sc._model is not None,
            "hit_count": sc.hit_count,
            "miss_count": sc.miss_count,
            "hit_rate": round(sc.hit_rate, 3),
        },
        "tool": {
            "size": len(tc),
            "max_size": tc._max,
            "ttl_s": tc._ttl,
            "hit_count": tc.hit_count,
            "miss_count": tc.miss_count,
        },
    })


# ── Rules Engine ──

@router.get("/rules/violations", tags=['Rules'])
async def get_rules_violations(limit: int = 50):
    """История срабатываний правил безопасности (AgentShield)."""
    from rules import get_rules_engine
    engine = get_rules_engine()
    return JSONResponse(engine.get_violations(limit=limit))


@router.get("/rules/count", tags=['Rules'])
async def get_rules_count():
    """Количество загруженных правил."""
    from rules import get_rules_engine
    engine = get_rules_engine()
    return JSONResponse({
        "total": sum(len(v) for v in engine.rules.values()),
        "by_category": {k: len(v) for k, v in engine.rules.items()},
    })


# ── OpenAPI / Docs ──

@router.get("/openapi.json", tags=['Core'])
async def get_openapi(request: Request):
    """Auto-generated OpenAPI 3.0 schema."""
    return JSONResponse(request.app.openapi())


@router.get("/docs", tags=['Core'])
async def get_swagger_ui():
    """Static Swagger UI page."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AIModelJudge — API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"/>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js" crossorigin></script>
<script>
  SwaggerUIBundle({{ url: "/openapi.json", dom_id: "#swagger-ui", defaultModelsExpandDepth: -1 }});
</script>
</body>
</html>""")


# ═══════════════════════════════════════════════════════════════════════
# Self-learning Status
# ═══════════════════════════════════════════════════════════════════════

_SKILL_DIRS_SL = [
    _SKILLS_BASE / "skills",
    Path.home() / ".hermes" / "skills",
    Path.home() / ".hermes" / "skills" / "ecc-imports",
]
_MEMORY_DB_SL = Path.home() / ".memory-mcp" / "memory.db"
_ECC_SEED = Path.home() / ".hermes" / "ecc-memory-seed.txt"
_MEMORY_CHAR_LIMIT = 2200


@router.get("/selflearning/status", tags=['Memory'])
async def get_selflearning_status():
    # Skills count
    def count_skills(d: Path) -> int:
        if not d.is_dir():
            return 0
        return sum(1 for p in d.rglob("SKILL.md") if p.is_file())

    local_skills = count_skills(_SKILL_DIRS_SL[0])
    # Exclude ecc-imports subdir from shared
    ecc_dir = _SKILL_DIRS_SL[2]
    shared_skills = 0
    if _SKILL_DIRS_SL[1].is_dir():
        for p in _SKILL_DIRS_SL[1].rglob("SKILL.md"):
            if p.is_file() and not str(p).startswith(str(ecc_dir)):
                shared_skills += 1
    ecc_skills = count_skills(ecc_dir)

    # Memory MCP stats
    memory_stats = {"total": 0, "project": 0, "pattern": 0, "reference": 0, "hot": 0, "relationships": 0}
    last_session = None
    if _MEMORY_DB_SL.exists():
        conn = sqlite3.connect(str(_MEMORY_DB_SL))
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()
            memory_stats["total"] = total["cnt"] if total else 0
            hot = conn.execute("SELECT COUNT(*) as cnt FROM memories WHERE is_hot=1").fetchone()
            memory_stats["hot"] = hot["cnt"] if hot else 0
            type_rows = conn.execute(
                "SELECT memory_type, COUNT(*) as cnt FROM memories GROUP BY memory_type"
            ).fetchall()
            for r in type_rows:
                memory_stats[r["memory_type"]] = r["cnt"]
            rels = conn.execute("SELECT COUNT(*) as cnt FROM memory_relationships").fetchone()
            memory_stats["relationships"] = rels["cnt"] if rels else 0
            sess = conn.execute(
                "SELECT started_at, project_path FROM sessions ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if sess:
                last_session = {"started_at": sess["started_at"], "project_path": sess["project_path"]}
        finally:
            conn.close()

    hot_cache = {"size": memory_stats["hot"], "max": 10}

    # ECC seed size
    ecc_used = _ECC_SEED.stat().st_size if _ECC_SEED.exists() else 0
    memory_budget = {
        "used": ecc_used,
        "limit": _MEMORY_CHAR_LIMIT,
        "percent": round(ecc_used / _MEMORY_CHAR_LIMIT * 100) if _MEMORY_CHAR_LIMIT else 0,
    }

    return JSONResponse({
        "skills": {
            "local": local_skills,
            "shared": shared_skills,
            "ecc": ecc_skills,
            "total": local_skills + shared_skills + ecc_skills,
        },
        "memory": memory_stats,
        "hot_cache": hot_cache,
        "memory_budget": memory_budget,
        "last_session": last_session,
    })


# ═══════════════════════════════════════════════════════════════════════
# Profile Manager v2 (/profiles/*)
# ═══════════════════════════════════════════════════════════════════════


def _profile_context_dir(user_id: str, profile_id: str) -> Path:
    env = os.getenv("AMJ_ENV", "")
    base = Path.home() / ".hermes-aimodeljudge"
    if env:
        base = base / env
    return base / "users" / user_id / "profiles" / profile_id / "context"


@router.get("/profiles/list", tags=["Profiles"])
async def profiles_list(user: UserContext = Depends(get_user_context)):
    profiles = list_profiles(user.user_id)
    # Auto-create default profile if user has none
    if not profiles:
        try:
            create_profile(user.user_id, "Мой первый профиль", is_default=True)
            profiles = list_profiles(user.user_id)
        except Exception:
            pass
    return JSONResponse({"profiles": profiles, "active": user.active_profile_id})


@router.post("/profiles/create", tags=["Profiles"])
async def profiles_create(request: Request, user: UserContext = Depends(get_user_context)):
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    name = str(body.get("name", "")).strip()
    if not name:
        return JSONResponse({"error": "Profile name required"}, status_code=400)

    # Tier gating
    max_profiles = get_tier_limit(user.tier, "max_profiles")
    if isinstance(max_profiles, int) and user.profile_count >= max_profiles:
        return JSONResponse(
            {"error": f"Достигнут лимит профилей ({max_profiles}). Перейдите на следующий тариф."},
            status_code=402,
        )

    description = str(body.get("description", ""))
    models = body.get("models") or []
    tools = body.get("tools") or []
    ha_enabled = bool(body.get("ha_enabled", False))
    if ha_enabled and not get_tier_limit(user.tier, "ha_access"):
        ha_enabled = False  # HA not available in this tier

    try:
        profile_id = create_profile(
            user.user_id, name, description=description,
            models=models, tools=tools, ha_enabled=ha_enabled,
        )
    except sqlite3.IntegrityError:
        return JSONResponse({"error": f"Профиль «{name}» уже существует"}, status_code=409)

    log_audit(user.user_id, "profile_create", "profiles",
              f"name={name} id={profile_id}",
              request.client.host if request.client else None)
    return JSONResponse({"ok": True, "profile_id": profile_id, "name": name})


@router.get("/profiles/{profile_id}", tags=["Profiles"])
async def profiles_get(profile_id: str, user: UserContext = Depends(get_user_context)):
    profile = get_profile(user.user_id, profile_id)
    if profile is None:
        return JSONResponse({"error": "Profile not found"}, status_code=404)
    return JSONResponse({"profile": profile})


@router.patch("/profiles/{profile_id}", tags=["Profiles"])
async def profiles_patch(profile_id: str, request: Request, user: UserContext = Depends(get_user_context)):
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    allowed = {"name", "description", "models", "tools", "ha_enabled", "is_default"}
    fields = {k: v for k, v in body.items() if k in allowed}

    # HA access check
    if "ha_enabled" in fields and fields["ha_enabled"] and not get_tier_limit(user.tier, "ha_access"):
        fields["ha_enabled"] = False

    if not fields:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)
    ok = update_profile(user.user_id, profile_id, **fields)
    if not ok:
        return JSONResponse({"error": "Profile not found"}, status_code=404)
    return JSONResponse({"ok": True})


@router.delete("/profiles/{profile_id}", tags=["Profiles"])
async def profiles_delete(profile_id: str, request: Request, user: UserContext = Depends(get_user_context)):
    ok = delete_profile(user.user_id, profile_id)
    if not ok:
        return JSONResponse(
            {"error": "Cannot delete profile — not found or is the last remaining"},
            status_code=400,
        )
    log_audit(user.user_id, "profile_delete", "profiles", f"id={profile_id}",
              request.client.host if request.client else None)
    return JSONResponse({"ok": True})


@router.post("/profiles/{profile_id}/activate", tags=["Profiles"])
async def profiles_activate(profile_id: str, request: Request, user: UserContext = Depends(get_user_context)):
    profile = get_profile(user.user_id, profile_id)
    if profile is None:
        return JSONResponse({"error": "Profile not found"}, status_code=404)
    activate_profile(user.user_id, profile_id)
    log_audit(user.user_id, "profile_activate", "profiles", f"id={profile_id}",
              request.client.host if request.client else None)
    return JSONResponse({"ok": True, "profile_id": profile_id, "name": profile["name"]})


@router.get("/profiles/{profile_id}/context", tags=["Profiles"])
async def profiles_get_context(profile_id: str, user: UserContext = Depends(get_user_context)):
    profile = get_profile(user.user_id, profile_id)
    if profile is None:
        return JSONResponse({"error": "Profile not found"}, status_code=404)
    ctx_dir = _profile_context_dir(user.user_id, profile_id)
    files = []
    if ctx_dir.is_dir():
        for f in sorted(ctx_dir.iterdir()):
            if f.is_file():
                try:
                    content = f.read_text()
                except Exception:
                    content = ""
                files.append({"name": f.name, "content": content, "size": f.stat().st_size})
    return JSONResponse({"profile_id": profile_id, "files": files})


@router.post("/profiles/{profile_id}/context", tags=["Profiles"])
async def profiles_upload_context(profile_id: str, request: Request, user: UserContext = Depends(get_user_context)):
    profile = get_profile(user.user_id, profile_id)
    if profile is None:
        return JSONResponse({"error": "Profile not found"}, status_code=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    file_name = str(body.get("name", "")).strip()
    content = str(body.get("content", ""))
    if not file_name:
        return JSONResponse({"error": "File name required"}, status_code=400)
    if not content:
        return JSONResponse({"error": "Content required"}, status_code=400)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file_name)
    ctx_dir = _profile_context_dir(user.user_id, profile_id)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    (ctx_dir / safe_name).write_text(content)
    log_audit(user.user_id, "profile_context_upload", "profiles",
              f"id={profile_id} file={safe_name}",
              request.client.host if request.client else None)
    return JSONResponse({"ok": True, "name": safe_name})


# ═══════════════════════════════════════════════════════════════════════
# Company Mode
# ═══════════════════════════════════════════════════════════════════════

from company_mode import list_available_specialists, SPECIALIST_ROLES
from company_orchestrator import CompanyOrchestrator


@router.get("/company/specialists", tags=['Core'])
async def list_company_specialists(user: UserContext = Depends(get_user_context)):
    available = list_available_specialists()
    all_specialists = [
        {"name": n, "display_name": {
            "marketer": "Маркетолог",
            "lawyer": "Юрист",
            "accountant": "Бухгалтер",
            "devops": "DevOps",
        }.get(n, n), "available": n in available}
        for n in sorted(SPECIALIST_ROLES)
    ]
    max_count = CompanyOrchestrator(user.tier).max_specialists
    return JSONResponse({"specialists": all_specialists, "max_for_tier": max_count, "tier": user.tier})


@router.post("/company/chat", tags=['Core'])
async def company_chat(request: Request, user: UserContext = Depends(get_user_context)):
    """SSE-стриминг Company Mode. Hub-and-spoke: специалисты → Архитектор."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    user_message = str(body.get("message", "")).strip()
    if not user_message:
        return JSONResponse({"error": "Message required"}, status_code=400)

    specialist_names = body.get("specialists", [])
    if not isinstance(specialist_names, list) or not specialist_names:
        return JSONResponse({"error": "specialists list required"}, status_code=400)

    orchestrator = CompanyOrchestrator(tier=user.tier)
    session_id = str(uuid.uuid4())
    request.app.state.session_owners = getattr(request.app.state, "session_owners", {})
    request.app.state.session_owners[session_id] = user.user_id

    async def _company_sse():
        gen = orchestrator.orchestrate(
            user_query=user_message,
            specialist_names=specialist_names,
            user_id=user.user_id,
            session_id=session_id,
        )
        async for event in gen:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        _company_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ═══════════════════════════════════════════════════════════════════════
# Cron Manager
# ═══════════════════════════════════════════════════════════════════════


@router.get("/cron/list", tags=['Cron'])
async def get_cron_list(user: UserContext = Depends(get_user_context)):
    jobs_out = list_cron(user.user_id)
    return JSONResponse({"jobs": jobs_out, "updated_at": ""})


@router.post("/cron/trigger", tags=['Cron'])
async def post_cron_trigger(request: Request, user: UserContext = Depends(get_user_context)):
    body = await request.json()
    job_id = body.get("job_id", "")
    ok = trigger_cron(user.user_id, job_id)
    if ok:
        fire_cron_complete(job_id=job_id, result={"state": "scheduled"})
        return JSONResponse({"ok": True, "job_id": job_id})
    return JSONResponse({"ok": False, "error": "Job not found"}, status_code=404)


@router.post("/cron/toggle", tags=['Cron'])
async def post_cron_toggle(request: Request, user: UserContext = Depends(get_user_context)):
    body = await request.json()
    job_id = body.get("job_id", "")
    action = body.get("action", "pause")
    pause = action == "pause"
    ok = toggle_cron(user.user_id, job_id, pause=pause)
    if ok:
        target_state = "paused" if pause else "scheduled"
        return JSONResponse({"ok": True, "job_id": job_id, "state": target_state})
    return JSONResponse({"ok": False, "error": "Job not found"}, status_code=404)


@router.post("/cron/create", tags=['Cron'])
async def post_cron_create(request: Request, user: UserContext = Depends(get_user_context)):
    body = await request.json()

    # ── Tier gating ──
    max_jobs = get_tier_limit(user.tier, "max_cron_jobs")
    if isinstance(max_jobs, int):
        current = count_cron(user.user_id)
        if current >= max_jobs:
            return JSONResponse(
                {"error": f"Лимит cron-задач ({max_jobs}) исчерпан. Перейдите на Pro/Business для создания дополнительных задач"},
                status_code=402,
            )

    name = (body.get("name") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    job_id = create_cron(
        user.user_id, name, prompt,
        schedule=body.get("schedule") or "",
        schedule_display=body.get("schedule_display") or body.get("schedule", ""),
        skills=body.get("skills") or [],
    )
    log_audit(user.user_id, "cron_create", "cron", f"name={name}", request.client.host if request.client else None)
    return JSONResponse({"ok": True, "job": {"id": job_id, "name": name, "state": "scheduled"}})


@router.delete("/cron/{job_id}", tags=['Cron'])
async def delete_cron_job(job_id: str, user: UserContext = Depends(get_user_context)):
    ok = dl_delete_cron(user.user_id, job_id)
    if not ok:
        return JSONResponse({"ok": False, "error": "Job not found"}, status_code=404)
    return JSONResponse({"ok": True, "job_id": job_id})


# ═══════════════════════════════════════════════════════════════════════
# Admin Panel — audit, users, promo codes, stats, config
# ═══════════════════════════════════════════════════════════════════════

_AUDIT_LOG_PATH = Path.home() / ".hermes-aimodeljudge" / "logs" / "audit.jsonl"


@router.get("/admin/audit", tags=['Admin'])
async def admin_audit(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    action: str = "",
    user_id: str = "",
    admin=Depends(require_admin),
):
    """Paginated audit log. Requires admin."""
    entries: list[dict] = []
    try:
        with open(_AUDIT_LOG_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if action and e.get("action") != action:
                    continue
                if user_id and e.get("user_id") != user_id:
                    continue
                entries.append(e)
    except FileNotFoundError:
        pass

    total = len(entries)
    entries.sort(key=lambda e: e.get("epoch", 0), reverse=True)
    page = entries[offset : offset + limit]
    return JSONResponse({"entries": page, "total": total, "limit": limit, "offset": offset})


@router.get("/admin/audit/verify", tags=['Admin'])
async def admin_audit_verify(admin=Depends(require_admin)):
    """Verify audit log chain integrity via HMAC. Requires admin."""
    from audit import verify_chain

    result = verify_chain()
    return JSONResponse(result)


@router.get("/admin/prompt-guard/stats", tags=['Admin'])
async def admin_prompt_guard_stats(admin=Depends(require_admin)):
    """Prompt Guard detection stats. Requires admin."""
    try:
        from web.prompt_guard import get_guard_stats
        stats = get_guard_stats()
        return JSONResponse(stats.as_dict())
    except ImportError:
        return JSONResponse({"error": "Prompt Guard module not loaded"}, status_code=500)


_ADMIN_STATE_DB = Path.home() / ".hermes-aimodeljudge" / "state.db"


@router.get("/admin/users", tags=['Admin'])
async def admin_users(
    request: Request,
    search: str = "",
    tier: str = "",
    limit: int = 50,
    offset: int = 0,
    admin=Depends(require_admin),
):
    """List users with optional search/filter. Requires admin."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT id, email, tier, is_admin, banned, created_at FROM users WHERE 1=1"
        params: list = []
        if search:
            query += " AND email LIKE ?"
            params.append(f"%{search}%")
        if tier:
            query += " AND tier = ?"
            params.append(tier)
        count_row = conn.execute(f"SELECT COUNT(*) as cnt FROM ({query})", params).fetchone()
        total = count_row["cnt"] if count_row else 0
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        users = [dict(r) for r in rows]
    finally:
        conn.close()
    return JSONResponse({"users": users, "total": total, "limit": limit, "offset": offset})


@router.get("/admin/users/{user_id}", tags=['Admin'])
async def admin_user_detail(user_id: str, admin=Depends(require_admin)):
    """Get user detail with subscription info. Requires admin."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)
        sub = conn.execute(
            "SELECT tier, status, current_period_end FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        skills_count = 0
        skills_dir = Path.home() / ".hermes-aimodeljudge" / "skills"
        if skills_dir.is_dir():
            skills_count = len([d for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
    finally:
        conn.close()
    return JSONResponse({
        "user": dict(user),
        "subscription": dict(sub) if sub else None,
        "skills_count": skills_count,
    })


@router.patch("/admin/users/{user_id}", tags=['Admin'])
async def admin_user_update(user_id: str, request: Request, admin=Depends(require_admin)):
    """Update user tier, banned, is_admin. Requires admin."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    allowed_fields = {"tier", "banned", "is_admin"}
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    if not updates:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    try:
        sets = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]
        cur = conn.execute(f"UPDATE users SET {sets} WHERE id = ?", values)
        conn.commit()
        if cur.rowcount == 0:
            return JSONResponse({"error": "User not found"}, status_code=404)
    finally:
        conn.close()
    return JSONResponse({"ok": True, "user_id": user_id, **updates})


@router.delete("/admin/users/{user_id}", tags=['Admin'])
async def admin_user_delete(user_id: str, admin=Depends(require_admin)):
    """Delete user and all associated data (cascade). Requires admin."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    try:
        cur = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if not cur.fetchone():
            return JSONResponse({"error": "User not found"}, status_code=404)
    finally:
        conn.close()
    stats = delete_user_cascade(user_id)
    log_audit(admin.user_id, "admin.delete_user", "admin", f"deleted={user_id}", result="success")
    return JSONResponse({"ok": True, "user_id": user_id, **stats})


# ═══════════════════════════════════════════════════════════════════════
# Admin Promo Codes
# ═══════════════════════════════════════════════════════════════════════

@router.get("/admin/promo-codes", tags=['Admin'])
async def admin_promo_codes(admin=Depends(require_admin)):
    """List all promo codes. Requires admin."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM promo_codes ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return JSONResponse({"promo_codes": [dict(r) for r in rows]})


@router.post("/admin/promo-codes", tags=['Admin'])
async def admin_promo_code_create(request: Request, admin=Depends(require_admin)):
    """Create a promo code. Requires admin."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    code = str(body.get("code", "")).strip().upper()
    discount_percent = int(body.get("discount_percent", 0))
    max_uses = int(body.get("max_uses", 0))
    expires_at = body.get("expires_at") or None

    if not code or discount_percent <= 0 or discount_percent > 100:
        return JSONResponse({"error": "code and valid discount_percent (1-100) required"}, status_code=400)

    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    try:
        existing = conn.execute("SELECT id FROM promo_codes WHERE code = ?", (code,)).fetchone()
        if existing:
            return JSONResponse({"error": "Promo code already exists"}, status_code=409)
        conn.execute(
            "INSERT INTO promo_codes (code, discount_percent, max_uses, expires_at, created_by) VALUES (?, ?, ?, ?, ?)",
            (code, discount_percent, max_uses, expires_at, admin.user_id),
        )
        conn.commit()
        promo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()
    return JSONResponse({"ok": True, "id": promo_id, "code": code, "discount_percent": discount_percent})


@router.delete("/admin/promo-codes/{promo_id}", tags=['Admin'])
async def admin_promo_code_delete(promo_id: int, admin=Depends(require_admin)):
    """Deactivate a promo code. Requires admin."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    try:
        cur = conn.execute("UPDATE promo_codes SET active = 0 WHERE id = ?", (promo_id,))
        conn.commit()
        if cur.rowcount == 0:
            return JSONResponse({"error": "Promo code not found"}, status_code=404)
    finally:
        conn.close()
    return JSONResponse({"ok": True, "promo_id": promo_id})


@router.post("/promo/validate", tags=['Admin'])
async def promo_validate(request: Request):
    """Validate a promo code (public endpoint)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    code = str(body.get("code", "")).strip().upper()
    if not code:
        return JSONResponse({"error": "code is required"}, status_code=400)

    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM promo_codes WHERE code = ? AND active = 1", (code,)
        ).fetchone()
        if not row:
            return JSONResponse({"valid": False, "error": "Promo code not found or inactive"})

        if row["expires_at"]:
            import datetime
            try:
                expires = datetime.datetime.fromisoformat(row["expires_at"])
                if datetime.datetime.now(datetime.timezone.utc) > expires:
                    return JSONResponse({"valid": False, "error": "Promo code expired"})
            except ValueError:
                pass

        if row["max_uses"] > 0 and row["current_uses"] >= row["max_uses"]:
            return JSONResponse({"valid": False, "error": "Promo code usage limit reached"})
    finally:
        conn.close()

    return JSONResponse({
        "valid": True,
        "code": row["code"],
        "discount_percent": row["discount_percent"],
        "expires_at": row["expires_at"],
    })


def _validate_and_apply_promo(code: str) -> int:
    """Validate promo code and return discount_percent, or 0 if invalid. Increments usage."""
    if not code:
        return 0
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM promo_codes WHERE code = ? AND active = 1", (code.strip().upper(),)
        ).fetchone()
        if not row:
            return 0
        if row["expires_at"]:
            import datetime
            try:
                expires = datetime.datetime.fromisoformat(row["expires_at"])
                if datetime.datetime.now(datetime.timezone.utc) > expires:
                    return 0
            except ValueError:
                pass
        if row["max_uses"] > 0 and row["current_uses"] >= row["max_uses"]:
            return 0
        conn.execute(
            "UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        return row["discount_percent"]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# Admin Stats / Dashboard
# ═══════════════════════════════════════════════════════════════════════

@router.get("/admin/stats", tags=['Admin'])
async def admin_stats(admin=Depends(require_admin)):
    """Overview stats for admin dashboard."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
        active_subs = conn.execute(
            "SELECT COUNT(*) as cnt FROM subscriptions WHERE status = 'active'"
        ).fetchone()["cnt"]
        tier_rows = conn.execute(
            "SELECT tier, COUNT(*) as cnt FROM subscriptions WHERE status = 'active' GROUP BY tier"
        ).fetchall()
        by_tier = {r["tier"]: r["cnt"] for r in tier_rows}
        # daily active users — users who sent a chat in last 24h (approximate via audit)
        dau = 0
        audit_path = Path.home() / ".hermes-aimodeljudge" / "logs" / "audit.jsonl"
        if audit_path.exists():
            import datetime as _dt
            cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=24)).isoformat()
            seen: set[str] = set()
            with open(audit_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("ts", "") >= cutoff and e.get("user_id") and e["user_id"] != "anon":
                        seen.add(e["user_id"])
            dau = len(seen)
    finally:
        conn.close()
    return JSONResponse({
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "subscriptions_by_tier": by_tier,
        "daily_active_users": dau,
    })


@router.get("/admin/stats/users", tags=['Admin'])
async def admin_stats_users(days: int = 30, admin=Depends(require_admin)):
    """User growth by day."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DATE(created_at) as day, COUNT(*) as cnt FROM users "
            "WHERE created_at >= DATE('now', ?) GROUP BY day ORDER BY day",
            (f"-{days} days",),
        ).fetchall()
    finally:
        conn.close()
    return JSONResponse({"growth": [dict(r) for r in rows], "days": days})


@router.get("/admin/stats/usage", tags=['Admin'])
async def admin_stats_usage(days: int = 14, admin=Depends(require_admin)):
    """Chat usage by day from audit log."""
    result: list[dict] = []
    audit_path = Path.home() / ".hermes-aimodeljudge" / "logs" / "audit.jsonl"
    if audit_path.exists():
        import datetime as _dt
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).isoformat()
        by_day: dict[str, int] = {}
        with open(audit_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("ts", "") >= cutoff and e.get("action") in ("chat", "login"):
                    day = e["ts"][:10]
                    by_day[day] = by_day.get(day, 0) + 1
        result = [{"day": k, "count": v} for k, v in sorted(by_day.items())]
    return JSONResponse({"usage": result, "days": days})


@router.get("/admin/stats/revenue", tags=['Admin'])
async def admin_stats_revenue(admin=Depends(require_admin)):
    """Revenue estimates."""
    conn = sqlite3.connect(str(_ADMIN_STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        tiers = conn.execute(
            "SELECT tier, COUNT(*) as cnt FROM subscriptions WHERE status = 'active' GROUP BY tier"
        ).fetchall()
        by_tier = {r["tier"]: r["cnt"] for r in tiers}
    finally:
        conn.close()
    return JSONResponse({"mrr": 0, "subscriptions_by_tier": by_tier})


# ═══════════════════════════════════════════════════════════════════════
# Admin System Config
# ═══════════════════════════════════════════════════════════════════════

from app_config import get_all_config, get_config as sys_get_config, set_config


@router.get("/admin/config", tags=['Admin'])
async def admin_config(admin=Depends(require_admin)):
    """Get all system config key-value pairs."""
    return JSONResponse({"config": get_all_config()})


@router.patch("/admin/config", tags=['Admin'])
async def admin_config_update(request: Request, admin=Depends(require_admin)):
    """Update system config keys."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not isinstance(body, dict) or not body:
        return JSONResponse({"error": "Request body must be a non-empty object"}, status_code=400)

    for key, value in body.items():
        set_config(str(key), str(value))

    return JSONResponse({"ok": True, "updated": list(body.keys())})


# ═══════════════════════════════════════════════════════════════════════
# Admin — Data Retention (W6)
# ═══════════════════════════════════════════════════════════════════════


@router.get("/admin/retention", tags=['Admin'])
async def admin_retention(admin=Depends(require_admin)):
    """Get current data retention configuration."""
    from app_config import get_config
    return JSONResponse({
        "retention_sessions_days": int(get_config("retention_sessions_days") or "90"),
        "retention_usage_days": int(get_config("retention_usage_days") or "90"),
        "retention_audit_days": int(get_config("retention_audit_days") or "365"),
    })


@router.patch("/admin/retention", tags=['Admin'])
async def admin_retention_update(request: Request, admin=Depends(require_admin)):
    """Update data retention configuration."""
    from app_config import set_config
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    valid_keys = {"retention_sessions_days", "retention_usage_days", "retention_audit_days"}
    updated = []
    for key, value in body.items():
        if key in valid_keys:
            set_config(key, str(value))
            updated.append(key)
    return JSONResponse({"ok": True, "updated": updated})


@router.post("/admin/purge", tags=['Admin'])
async def admin_trigger_purge(admin=Depends(require_admin)):
    """Manually trigger data purge now."""
    from data_retention import purge_old_data
    try:
        result = purge_old_data()
        log_audit(admin.user_id, "admin.manual_purge", "admin", "Manual data purge triggered", result="success")
        return JSONResponse({"purged": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Agent WebSocket + Status ───────────────────────────────────

@router.websocket("/agent/ws")
async def agent_websocket(ws: WebSocket):
    """WebSocket endpoint for local hermes-agent connections."""
    from agent_ws import handle_agent_ws
    await handle_agent_ws(ws)


@router.get("/agent/status", tags=['Core'])
async def agent_status(user: UserContext = Depends(get_user_context)):
    """Check if a local agent is connected for the current user."""
    from agent_manager import get_agent_manager
    mgr = get_agent_manager()
    connected = mgr.is_connected(user.user_id)
    info = mgr.get_agent_info(user.user_id) if connected else None
    return JSONResponse({
        "connected": connected,
        "version": info.get("version", "") if info else "",
        "project_root": info.get("project_root", "") if info else "",
    })


# ── Email Subscribe (Landing) ────────────────────────────────────

@router.post("/email/subscribe", tags=['Email'])
async def email_subscribe(request: Request):
    """Subscribe email from landing page."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    source = (body.get("source") or "landing").strip()

    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)

    state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db))
    try:
        existing = conn.execute(
            "SELECT id, active FROM email_subscribers WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            if not existing[1]:
                conn.execute(
                    "UPDATE email_subscribers SET active = 1, unsubscribed_at = NULL, source = ? WHERE email = ?",
                    (source, email),
                )
                conn.commit()
                return JSONResponse({"message": "Вы снова подписаны!", "resubscribed": True})
            return JSONResponse({"message": "Вы уже подписаны", "already_subscribed": True})
        conn.execute(
            "INSERT INTO email_subscribers (email, source) VALUES (?, ?)",
            (email, source),
        )
        conn.commit()
    finally:
        conn.close()

    return JSONResponse({"message": "Готово! Проверьте почту.", "subscribed": True})


@router.get("/email/unsubscribe", tags=['Email'])
async def email_unsubscribe(email: str = ""):
    """Unsubscribe email via GET link from email."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)

    state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db))
    try:
        conn.execute(
            "UPDATE email_subscribers SET active = 0, unsubscribed_at = datetime('now') WHERE email = ?",
            (email,),
        )
        conn.commit()
    finally:
        conn.close()

    return JSONResponse({"message": "Вы отписались от рассылки."})


# ── Referral System ───────────────────────────────────────────────

@router.get("/referral/code", tags=['Referral'])
async def get_referral_code(user: UserContext = Depends(get_user_context)):
    """Get or create user's referral code."""
    import secrets as _secrets
    state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT code, usage_count, reward_credited FROM referral_codes WHERE owner_user_id = ?",
            (user.user_id,),
        ).fetchone()
        if row:
            return JSONResponse({
                "code": row[0],
                "url": f"/app/?ref={row[0]}",
                "usage_count": row[1],
                "reward_credited": bool(row[2]),
            })

        code = _secrets.token_hex(4)
        conn.execute(
            "INSERT INTO referral_codes (code, owner_user_id) VALUES (?, ?)",
            (code, user.user_id),
        )
        conn.commit()
        return JSONResponse({
            "code": code,
            "url": f"/app/?ref={code}",
            "usage_count": 0,
            "reward_credited": False,
        })
    finally:
        conn.close()


@router.get("/referral/stats", tags=['Referral'])
async def get_referral_stats(user: UserContext = Depends(get_user_context)):
    """Get referral stats for the user."""
    state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT code, usage_count, reward_credited, created_at FROM referral_codes WHERE owner_user_id = ?",
            (user.user_id,),
        ).fetchone()
        if not row:
            return JSONResponse({"code": None, "usage_count": 0, "reward_credited": False})
        return JSONResponse({
            "code": row["code"],
            "url": f"/app/?ref={row['code']}",
            "usage_count": row["usage_count"],
            "reward_credited": bool(row["reward_credited"]),
            "created_at": row["created_at"],
        })
    finally:
        conn.close()


@router.post("/referral/apply", tags=['Referral'])
async def apply_referral(request: Request):
    """Validate and apply a referral code."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    code = (body.get("code") or "").strip()
    email = (body.get("email") or "").strip().lower()

    if not code:
        return JSONResponse({"error": "Referral code required"}, status_code=400)
    if not email:
        return JSONResponse({"error": "Email required"}, status_code=400)

    state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db))
    try:
        ref = conn.execute(
            "SELECT owner_user_id, usage_count FROM referral_codes WHERE code = ?",
            (code,),
        ).fetchone()
        if not ref:
            return JSONResponse({"error": "Invalid referral code"}, status_code=404)

        # Don't let users refer themselves
        referred = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if referred and referred[0] == ref[0]:
            return JSONResponse({"error": "Cannot refer yourself"}, status_code=400)

        return JSONResponse({
            "valid": True,
            "code": code,
            "message": "Реферальный код действителен. Будет применён при регистрации.",
        })
    finally:
        conn.close()


# ── Admin: Email Subscribers ──────────────────────────────────────

@router.get("/admin/email-subscribers", tags=['Admin'])
async def admin_email_subscribers(
    page: int = 1,
    active_only: bool = False,
    admin: UserContext = Depends(require_admin),
):
    """List email subscribers (admin only)."""
    state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
    conn = sqlite3.connect(str(state_db))
    conn.row_factory = sqlite3.Row
    try:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM email_subscribers WHERE active = 1 ORDER BY subscribed_at DESC LIMIT 50 OFFSET ?",
                ((page - 1) * 50,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM email_subscribers ORDER BY subscribed_at DESC LIMIT 50 OFFSET ?",
                ((page - 1) * 50,),
            ).fetchall()
        total = conn.execute("SELECT COUNT(*) as cnt FROM email_subscribers").fetchone()["cnt"]
        active = conn.execute("SELECT COUNT(*) as cnt FROM email_subscribers WHERE active = 1").fetchone()["cnt"]
        return JSONResponse({
            "subscribers": [dict(r) for r in rows],
            "total": total,
            "active": active,
            "page": page,
        })
    finally:
        conn.close()
