"""AIModelJudge Web Agent — точка входа FastAPI + uvicorn (без авторизации)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from routes import router

from config import load_settings, _validate_env
from logging_config import setup_logging
from correlation import create_correlation_middleware, _CorrelationLogFilter
from rate_limit import get_rate_limiter, check_token_rate_limit
from app_config import is_maintenance_mode
from cost_guard import get_monthly_counter, check_model_allowed_for_tier, COST_LIMITS
from agent_manager import get_agent_manager
from auth import resolve_user_identity

# Application start timestamp for /health uptime
import time as _time
_app_start_time = _time.time()


def create_app() -> FastAPI:
    settings = load_settings()

    app = FastAPI(
        title="AIModelJudge Web Agent",
        version="1.5.0",
        description="AI-powered code analysis platform. Multi-model judge with 4-phase SSE processing, JWT auth, Telegram bot, PWA.",
        swagger_ui_parameters={"defaultModelsExpandDepth": 1},
    )
    app.state.settings = settings
    app.state.active_cancel_events: dict[str, object] = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:9651",
            "http://localhost:9651",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "X-AMJ-API-Key", "Content-Type", "X-Stream-Session", "X-Local-Session", "X-Correlation-ID"],
    )

    # ── Correlation ID middleware (before security headers, after CORS) ──
    _CorrelationMiddleware = create_correlation_middleware()
    app.add_middleware(_CorrelationMiddleware)

    # ── Security Headers middleware ──
    class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            # HSTS — только в production (в dev ломает localhost)
            if os.getenv("AMJ_ENV", "") == "prod":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=63072000; includeSubDomains; preload"
                )
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
                "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
                "font-src 'self'; frame-src 'none'; object-src 'none'",
            )
            return response
    app.add_middleware(_SecurityHeadersMiddleware)

    # ── Maintenance mode check (before rate limiter) ──
    class _MaintenanceMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if path.startswith("/admin/") and is_maintenance_mode():
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": "Service is in maintenance mode"}, status_code=503)
            return await call_next(request)
    app.add_middleware(_MaintenanceMiddleware)

    # ── Rate Limit middleware ──
    from fastapi.responses import JSONResponse

    class _RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            limiter = get_rate_limiter()
            path = request.url.path
            ip = request.client.host if request.client else "127.0.0.1"

            if path.startswith("/auth/") and not path.startswith("/auth/me") and not path.startswith("/auth/api-keys"):
                allowed, remaining, limit, reset = limiter.check_auth_limit(ip)
            elif path.startswith("/admin/") or path.startswith("/chat") or path.startswith("/model/switch"):
                identity = await resolve_user_identity(request)
                if identity:
                    user_id, tier, scope = identity
                    allowed, remaining, limit, reset = check_token_rate_limit(user_id, ip, tier, scope)
                else:
                    allowed, remaining, limit, reset = limiter.check_rate_limit(None, ip, "default")
            else:
                return await call_next(request)

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(int(reset))

            if not allowed:
                return JSONResponse(
                    {"error": "Rate limit exceeded. Try again later."},
                    status_code=429,
                    headers={
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(reset)),
                        "Retry-After": str(int(reset) + 1),
                    },
                )
            return response
    app.add_middleware(_RateLimitMiddleware)

    # ── Cost Guard middleware (monthly limits + model gating) ──
    class _CostGuardMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if path.startswith("/chat") or path.startswith("/model/switch"):
                identity = await resolve_user_identity(request)
                if identity:
                    user_id, tier, scope = identity
                    import sqlite3 as _sql
                    conn = _sql.connect(str(Path.home() / ".hermes-aimodeljudge" / "state.db"))
                    conn.row_factory = _sql.Row
                    try:
                        # Check subscription for effective tier
                        sub = conn.execute(
                            "SELECT status FROM subscriptions WHERE user_id = ? AND status = 'active' LIMIT 1",
                            (user_id,),
                        ).fetchone()
                        eff_tier = tier if sub else "default"

                        counter = get_monthly_counter()
                        allowed, current, limit = counter.check_and_increment(user_id, eff_tier)
                        if not allowed:
                            return JSONResponse(
                                {"error": f"Превышен лимит запросов ({limit}/мес). Перейдите на следующий тариф.",
                                 "limit": limit, "current": current, "period": "monthly"},
                                status_code=429,
                            )
                    finally:
                        conn.close()
            return await call_next(request)

    app.add_middleware(_CostGuardMiddleware)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # React app (built)
    react_dist = Path(__file__).resolve().parent.parent / "web-react" / "dist"
    if react_dist.is_dir():
        app.mount("/app", StaticFiles(directory=str(react_dist), html=True), name="react")

    app.include_router(router)

    # Landing page at root (must be after router so API routes take priority)
    landing_dir = Path(__file__).resolve().parent.parent / "landing"
    if landing_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(landing_dir), html=True), name="landing")

    @app.on_event("startup")
    async def warm_memory_cache():
        """Прогрев горячего кэша Memory MCP при старте + инициализация хуков."""
        # ── Validate AMJ_ENV before anything else ──
        env = _validate_env()
        log = setup_logging()
        log.info("AIModelJudge starting (env=%s)", env)

        # ── Secrets Vault ──
        try:
            from secrets_vault import get_secrets_vault
            vault = get_secrets_vault()
            if vault.is_unlocked():
                names = vault.list_secrets()
                log.info("Secrets Vault: unlocked (%d secrets)", len(names))
            else:
                log.info("Secrets Vault: locked — using env vars")
        except Exception as e:
            log.warning("Secrets Vault: init failed — %s", e)

        # ── Correlation ID log filter ──
        logging.getLogger().addFilter(_CorrelationLogFilter())

        # ── DB Migration (users, subscriptions, telegram_links) ──
        state_db = Path.home() / ".hermes-aimodeljudge" / "state.db"
        state_db.parent.mkdir(parents=True, exist_ok=True)
        os.umask(0o077)  # все новые файлы создаются с permissions 0600
        try:
            conn = sqlite3.connect(str(state_db))
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    api_key TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'default'
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_period_end TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS telegram_links (
                    chat_id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    linked_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    discount_percent INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL DEFAULT 0,
                    current_uses INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS email_subscribers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    source TEXT DEFAULT 'landing',
                    subscribed_at TEXT NOT NULL DEFAULT (datetime('now')),
                    unsubscribed_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS referral_codes (
                    code TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    reward_credited INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_referral_codes_owner ON referral_codes(owner_user_id);
                """
            )
            # ── Migrations: add columns that may not exist on older DBs ──
            try:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE users ADD COLUMN banned INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # ── Profiles table (Stage 11: Profile Manager v2) ──
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    models TEXT DEFAULT '[]',
                    tools TEXT DEFAULT '[]',
                    ha_enabled INTEGER DEFAULT 0,
                    is_default INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(user_id, name)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_profiles_user_id ON profiles(user_id)"
            )
            # ── Migrate old profiles table (add new columns if missing) ──
            try:
                conn.execute("ALTER TABLE profiles ADD COLUMN models TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE profiles ADD COLUMN tools TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE profiles ADD COLUMN ha_enabled INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # ── Sessions table: ensure user_id column exists ──
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
            except sqlite3.OperationalError:
                pass
            # ── Sessions table: ensure profile_id column exists ──
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN profile_id TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            conn.commit()
            conn.close()
            state_db.chmod(0o600)

            # ── Kanban DB: ensure user_id column exists on tasks ──
            kanban_db = Path.home() / ".hermes-aimodeljudge" / "kanban.db"
            try:
                kconn = sqlite3.connect(str(kanban_db))
                try:
                    kconn.execute("ALTER TABLE tasks ADD COLUMN user_id TEXT")
                    kconn.commit()
                except sqlite3.OperationalError:
                    pass
                kconn.close()
            except Exception:
                pass
        except Exception:
            log.warning("Ошибка миграции таблиц пользователей", exc_info=True)

        # ── Hooks + Rules Engine ──
        from rules import ensure_rules_dir, get_rules_engine
        from hooks import init_hooks
        try:
            ensure_rules_dir()
            get_rules_engine().load_all()
            loaded = init_hooks(settings.hook_profile)
            if loaded > 0:
                log.info("Хуки: загружено %d (профиль=%s)", loaded, settings.hook_profile)
        except Exception:
            log.warning("Ошибка инициализации хуков", exc_info=True)

        # ── Agent Manager (WebSocket for local agents) ──
        try:
            get_agent_manager()
            log.info("Agent Manager: инициализирован")
        except Exception:
            log.warning("Ошибка инициализации Agent Manager", exc_info=True)

        # ── Memory MCP ──
        mem_db = Path.home() / ".memory-mcp" / "memory.db"
        if mem_db.exists():
            try:
                conn = sqlite3.connect(str(mem_db))
                conn.row_factory = sqlite3.Row
                project_id = "github/strong-prog/AIModelJudge"
                cnt = conn.execute(
                    "SELECT COUNT(*) as cnt FROM memories WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                hot = conn.execute(
                    "SELECT COUNT(*) as cnt FROM memories WHERE project_id = ? AND is_hot = 1",
                    (project_id,),
                ).fetchone()
                conn.close()
                # Memory bootstrap: если нет фактов о проекте — предложить засеять
                if cnt["cnt"] == 0:
                    log.info(
                        "Memory MCP: проект AIModelJudge не найден в памяти. "
                        "Засеять через mcp__memory__bootstrap_project "
                        "или mcp__memory__seed_from_file"
                    )
            except Exception:
                pass

        # ── Telegram Bot ──
        if settings.telegram_token:
            try:
                from telegram_bot import start_bot

                app.state._tg_bot_task = asyncio.create_task(start_bot())
                log.info("Telegram-бот запущен (allowed_users=%s)", settings.telegram_allowed_users)
            except Exception:
                log.warning("Ошибка запуска Telegram-бота", exc_info=True)

        # ── Rate limiter cleanup (every 5 minutes) ──
        async def _cleanup_rate_limits():
            limiter = get_rate_limiter()
            while True:
                await asyncio.sleep(300)
                try:
                    limiter.cleanup()
                except Exception:
                    pass

        app.state._rl_cleanup_task = asyncio.create_task(_cleanup_rate_limits())

        # ── Daily spend midnight reset + data purge (03:00 UTC) ──
        async def _midnight_reset(time_sys):
            from cost_guard import get_daily_spend_tracker
            tracker = get_daily_spend_tracker()
            purge_done_today = False
            while True:
                now = time_sys.time()
                midnight = (int(now // 86400) + 1) * 86400
                await asyncio.sleep(midnight - now)
                tracker.reset_all()
                log.info("Daily spend tracker: midnight reset")
                purge_done_today = False
                # Schedule purge at 03:00 UTC (3 hours after midnight)
                await asyncio.sleep(3 * 3600)
                if not purge_done_today:
                    try:
                        from data_retention import purge_old_data
                        result = purge_old_data()
                        log.info("Data purge: %s", result)
                    except Exception:
                        log.warning("Data purge failed", exc_info=True)
                    purge_done_today = True

        import time as _time_sys
        app.state._midnight_task = asyncio.create_task(_midnight_reset(_time_sys))

        # ── Cost guard tables migration ──
        try:
            state_db_path = Path.home() / ".hermes-aimodeljudge" / "state.db"
            conn = sqlite3.connect(str(state_db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_request_counts (
                    user_id TEXT NOT NULL,
                    year_month TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, year_month)
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                    timestamp TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'default'
                );
            """)
            conn.commit()
            conn.close()
        except Exception:
            log.warning("Ошибка миграции cost guard таблиц", exc_info=True)

        # ── W10: JWT auth tables migration ──
        try:
            conn = sqlite3.connect(str(state_db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_blacklist (
                    jti TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    revoked_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jwt_secret_versions (
                    version INTEGER PRIMARY KEY,
                    secret_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scoped_api_keys (
                    api_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'full',
                    name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scoped_keys_user ON scoped_api_keys(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_expires ON token_blacklist(expires_at)")
            conn.commit()
            conn.close()
        except Exception:
            log.warning("Ошибка миграции JWT таблиц", exc_info=True)

        # ── W10: JWT secret init ──
        try:
            from jwt_auth import _get_jwt_secret
            _get_jwt_secret()
            log.info("JWT secret: initialized")
        except Exception as e:
            log.warning("JWT secret init failed: %s", e)

        # ── W10: Token blacklist cleanup (every hour) ──
        async def _cleanup_token_blacklist():
            from token_store import cleanup_expired_blacklist
            while True:
                await asyncio.sleep(3600)
                try:
                    removed = cleanup_expired_blacklist()
                    if removed > 0:
                        log.info("Token blacklist: cleaned %d expired entries", removed)
                except Exception:
                    pass

        app.state._bl_cleanup_task = asyncio.create_task(_cleanup_token_blacklist())

    @app.on_event("shutdown")
    async def shutdown_telegram_bot():
        tg_task = getattr(app.state, "_tg_bot_task", None)
        if tg_task:
            tg_task.cancel()
            try:
                await tg_task
            except asyncio.CancelledError:
                pass
        rl_task = getattr(app.state, "_rl_cleanup_task", None)
        if rl_task:
            rl_task.cancel()
            try:
                await rl_task
            except asyncio.CancelledError:
                pass
        midnight_task = getattr(app.state, "_midnight_task", None)
        if midnight_task:
            midnight_task.cancel()
            try:
                await midnight_task
            except asyncio.CancelledError:
                pass
        bl_task = getattr(app.state, "_bl_cleanup_task", None)
        if bl_task:
            bl_task.cancel()
            try:
                await bl_task
            except asyncio.CancelledError:
                pass
        # ── Close agent WebSocket connections ──
        try:
            from agent_manager import get_agent_manager
            get_agent_manager().close_all()
        except Exception:
            pass
        try:
            from telegram_bot import stop_bot

            await stop_bot()
        except Exception:
            pass
        # ── Close Secrets Vault ──
        try:
            from secrets_vault import get_secrets_vault
            get_secrets_vault().close()
        except Exception:
            pass

    return app


def main() -> None:
    import uvicorn

    settings = load_settings()
    app = create_app()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
