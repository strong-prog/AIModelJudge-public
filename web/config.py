"""AIModelJudge Web Agent — настройки (без пароля, без секретов)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("aimodeljudge.config")

_LOCAL_STATE_DIR = Path.home() / ".aimodeljudge-web-agent"
_LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MODEL_STATE_FILE", str(_LOCAL_STATE_DIR / "model_state.json"))


@dataclass(slots=True)
class WebAgentLocalSettings:
    hermes_url: str = "http://127.0.0.1:9084/v1/chat/completions"
    hermes_messages_url: str = "http://127.0.0.1:8084/v1/messages"
    hermes_api_key: str = ""
    host: str = "127.0.0.1"
    port: int = 9651
    hook_profile: str = "standard"  # ECC_HOOK_PROFILE: off | minimal | standard | strict
    telegram_token: str = ""  # AMJ_TELEGRAM_TOKEN — токен бота
    telegram_allowed_users: str = ""  # AMJ_TELEGRAM_ALLOWED_USERS — user_id через запятую
    # ── AI Provider API keys ──
    deepseek_api_key: str = ""  # DEEPSEEK_API_KEY
    openai_api_key: str = ""  # OPENAI_API_KEY
    anthropic_api_key: str = ""  # ANTHROPIC_API_KEY
    gemini_api_key: str = ""  # GEMINI_API_KEY
    side_proxy_key: str = ""  # AMJ_SIDE_PROXY_KEY
    # ── Core secrets ──
    audit_secret: str = ""  # AMJ_AUDIT_SECRET
    # ── JWT ──
    jwt_secret: str = ""  # AMJ_JWT_SECRET


def _validate_env() -> str:
    """Validate AMJ_ENV setting. Returns the env name or raises SystemExit.

    Protects against accidental prod-starts on non-server machines.
    AMJ_ENV=prod is only allowed when AMJ_ALLOW_PROD=true or on
    recognised server hostnames.
    """
    env = os.getenv("AMJ_ENV", "")
    if not env or env in ("dev", "test"):
        return env

    if env == "prod":
        hostname = os.uname().nodename
        allowed_prod = os.getenv("AMJ_ALLOW_PROD", "").lower() == "true"
        server_hostnames: set[str] = set()
        if not allowed_prod and hostname not in server_hostnames:
            import sys
            print(
                f"ERROR: AMJ_ENV=prod refused on host '{hostname}'.\n"
                f"  Set AMJ_ALLOW_PROD=true to override, or use AMJ_ENV=dev/test.\n"
                f"  Allowed server hostnames: {sorted(server_hostnames)}",
                file=sys.stderr,
            )
            sys.exit(1)

    return env


def _get_secret_or_env(name: str, env_var: str, default: str = "") -> str:
    """Resolve a secret: vault → env → default. Writes resolved value to os.environ."""
    try:
        from secrets_vault import get_secrets_vault
        vault = get_secrets_vault()
        if vault.is_unlocked():
            value = vault.get_secret(name)
            if value is not None:
                os.environ[env_var] = value
                return value
    except Exception as e:
        logger.debug("Vault lookup failed for '%s': %s", name, e)
    return os.getenv(env_var, default)


def load_settings() -> WebAgentLocalSettings:
    return WebAgentLocalSettings(
        hermes_url=os.getenv("AMJ_ROUTER_URL", "http://127.0.0.1:9084")
        + "/v1/chat/completions",
        hermes_messages_url=os.getenv("AMJ_MESSAGES_URL", "http://127.0.0.1:8084")
        + "/v1/messages",
        hermes_api_key=_get_secret_or_env("AMJ_API_KEY", "AMJ_API_KEY", ""),
        host=os.getenv("AMJ_WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("AMJ_WEB_PORT", "9651")),
        hook_profile=os.getenv("ECC_HOOK_PROFILE", "standard"),
        telegram_token=_get_secret_or_env("AMJ_TELEGRAM_TOKEN", "AMJ_TELEGRAM_TOKEN", ""),
        telegram_allowed_users=os.getenv("AMJ_TELEGRAM_ALLOWED_USERS", ""),
        deepseek_api_key=_get_secret_or_env("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", ""),
        openai_api_key=_get_secret_or_env("OPENAI_API_KEY", "OPENAI_API_KEY", ""),
        anthropic_api_key=_get_secret_or_env("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", ""),
        gemini_api_key=_get_secret_or_env("GEMINI_API_KEY", "GEMINI_API_KEY", ""),
        side_proxy_key=_get_secret_or_env("AMJ_SIDE_PROXY_KEY", "AMJ_SIDE_PROXY_KEY", ""),
        audit_secret=_get_secret_or_env("AMJ_AUDIT_SECRET", "AMJ_AUDIT_SECRET", ""),
        jwt_secret=_get_secret_or_env("AMJ_JWT_SECRET", "AMJ_JWT_SECRET", ""),
    )


SYSTEM_PROMPT = (
    "Ты — главный архитектор и инженер-решатель AIModelJudge. "
    "Твоя задача — решить проблему пользователя, используя "
    "команду экспертов (модели в боковых панелях).\n\n"
    "Ты НЕ судья и НЕ оркестратор сравнения. Ты — архитектор, "
    "который советуется с экспертами, взвешивает аргументы "
    "и выдаёт ОДНО ИДЕАЛЬНОЕ РЕШЕНИЕ.\n\n"
    "СТРОГИЙ ПОРЯДОК ДЕЙСТВИЙ:\n\n"
    "ШАГ 1 — АНАЛИЗ (быстрый, не затягивай):\n"
    "  • Пойми суть вопроса: это код-задача или теория?\n"
    "  • ДЛЯ КОД-ЗАДАЧ: codegraph_explore, grep, read_file — найди релевантный код\n"
    "  • ДЛЯ ТЕОРИИ (сравнения, архитектура, best practices): "
    "быстрый web_search или memory recall — 1-2 запроса максимум\n"
    "  • Сформулируй enriched query для экспертов "
    "(всегда, даже для теории — экспертам нужен контекст!)\n"
    "  • НЕ застревай на этом шаге — 30 секунд максимум, затем Шаг 2\n\n"
    "ШАГ 2 — КОНСУЛЬТАЦИЯ (ОБЯЗАТЕЛЬНО для ВСЕХ запросов!):\n"
    "  • ВСЕГДА вызывай query_primary_models с enriched query\n"
    "  • В enriched query включи: суть вопроса, найденный контекст, "
    "ключевые аспекты для анализа\n"
    "  • Для теории: проси экспертов дать СТРУКТУРИРОВАННЫЙ анализ "
    "с конкретными рекомендациями\n"
    "  • Для кода: проси экспертов предложить КОНКРЕТНЫЙ фикс с кодом\n\n"
    "ШАГ 3 — СИНТЕЗ (после получения ответов экспертов):\n"
    "  • Найди КОНСЕНСУС — в чём все эксперты согласны\n"
    "  • Выяви ПРОТИВОРЕЧИЯ — проверь кто прав\n"
    "  • Заполни ПРОБЕЛЫ — что все эксперты упустили, добавь "
    "свой анализ\n"
    "  • Сформируй ИДЕАЛЬНОЕ РЕШЕНИЕ (текст или правки кода)\n\n"
    "ШАГ 4 — ПРИМЕНЕНИЕ:\n"
    "  • Если нужны правки → edit_file / write_file\n"
    "  • Если нужна проверка → bash (тесты, линтер)\n"
    "  • Если нужен ответ → выдай готовый текст пользователю\n\n"
    "ЖЁСТКИЕ ПРАВИЛА:\n\n"
    "1. ВСЕГДА вызывай query_primary_models для консультации "
    "с экспертами. Это главный инструмент. "
    "Для теории — сразу после быстрого web_search. "
    "Для кода — после нахождения релевантных файлов.\n\n"
    "2. НИКОГДА не сравнивай «кто лучше ответил» и не выставляй "
    "оценки моделям — это не твоя задача. Твоя задача — "
    "выдать ГОТОВОЕ РЕШЕНИЕ.\n\n"
    "3. Используй CodeGraph и Memory MCP на ВСЕХ этапах "
    "для проверки фактов и поиска контекста (когда релевантно).\n\n"
    "4. Если инструмент query_primary_models вернул ошибку — "
    "сообщи пользователю и ответь самостоятельно на основе "
    "своего анализа.\n\n"
    "5. НЕ перефразируй вопрос пользователя в рассуждениях. "
    "НЕ повторяй вопрос в ответе. Если чувствуешь зацикливание "
    "на анализе — прекрати и дай прямой ответ.\n\n"
    "У тебя есть доступ к shell, файлам, codegraph, memory, "
    "web и другим инструментам на локальной машине. "
    "Для выхода в интернет используй ТОЛЬКО web_search "
    "(SearXNG) и web_fetch.\n\n"
    "ПРАВИЛА БЕЗОПАСНОСТИ И ДОСТОВЕРНОСТИ:\n"
    "1. НИКОГДА не выводи API-ключи, токены, пароли. "
    "В отчётах: 'DEEPSEEK_API_KEY: ✅ задан', а не сам ключ.\n"
    "2. НЕ выдумывай то, чего не проверял. Для каждого факта "
    "должно быть наблюдаемое подтверждение.\n"
    "3. Разделяй НАБЛЮДЕНИЯ и ПРЕДПОЛОЖЕНИЯ. Догадки помечай "
    "'[предположение]'."
)
