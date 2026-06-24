"""AIModelJudge — движок хуков (PreToolUse, PostToolUse, SessionStart, ...).

Хранилище: ~/.hermes-aimodeljudge/hooks/ — по одному .py на хук.
Профиль: ECC_HOOK_PROFILE = off | minimal | standard | strict (по умолчанию standard).
"""

from __future__ import annotations

import asyncio
import enum
import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

_log = logging.getLogger("aimodeljudge.hooks")

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"

HOOKS_DIR = _BASE / "hooks"
HOOKS_DIR.mkdir(parents=True, exist_ok=True)

VALID_HOOKS: set[str] = {
    "pre_tool_use",
    "post_tool_use",
    "user_prompt_submit",
    "stop",
    "pre_compact",
    "session_start",
    "notification",
    "cron_complete",
}


# ── Profile ────────────────────────────────────────────────────────────


class HookProfile(enum.StrEnum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    STRICT = "strict"


_PROFILE_HOOKS: dict[HookProfile, set[str]] = {
    HookProfile.MINIMAL: {"pre_tool_use"},
    HookProfile.STANDARD: {"pre_tool_use", "post_tool_use", "stop", "session_start", "pre_compact"},
    HookProfile.STRICT: set(VALID_HOOKS),
}


def _resolve_profile(raw: str | None) -> HookProfile | None:
    """Возвращает None если хуки выключены (пустая строка или off)."""
    if not raw or raw.strip().lower() in ("off", "none", ""):
        return None
    raw = raw.strip().lower()
    try:
        return HookProfile(raw)
    except ValueError:
        _log.warning("Неизвестный профиль хуков %r, использую standard", raw)
        return HookProfile.STANDARD


# ── Data types ─────────────────────────────────────────────────────────


@dataclass
class HookResult:
    """Результат, возвращаемый хуком."""
    action: Literal["allow", "block", "continue"] = "continue"
    message: str = ""
    modified_args: dict[str, Any] | None = None
    context: str = ""
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"action": self.action}
        if self.message:
            d["message"] = self.message
        if self.modified_args is not None:
            d["modified_args"] = self.modified_args
        if self.context:
            d["context"] = self.context
        if self.decisions:
            d["decisions"] = self.decisions
        return d


# ── Hook dispatch helpers ──────────────────────────────────────────────


async def _invoke_with_timeout(coro: Any, hook_name: str, timeout: float = 5.0) -> Any | None:
    """Обёртка с таймаутом — fail-open: исключения не пробрасываются."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        _log.warning("Хук %s превысил таймаут %.1fs", hook_name, timeout)
        return None
    except Exception:
        _log.warning("Хук %s завершился с ошибкой", hook_name, exc_info=True)
        return None


def _fire_and_forget(coro: Any, hook_name: str, timeout: float = 5.0) -> None:
    """Запускает корутину в фоне, логирует исключения."""

    async def _wrapper() -> None:
        await _invoke_with_timeout(coro, hook_name, timeout)

    try:
        asyncio.create_task(_wrapper())
    except RuntimeError:
        pass  # нет event loop — хуки отключены


# ── Hook Manager ───────────────────────────────────────────────────────


class HookManager:
    """Singleton: загружает .py хуки из HOOKS_DIR и вызывает по имени."""

    def __init__(self) -> None:
        self._loaded: dict[str, Callable[..., Any]] = {}
        self._profile: HookProfile | None = None
        self._active_hooks: set[str] = set()

    # ── load ──────────────────────────────────────────────────────────

    def load(self, profile: HookProfile | None = None) -> int:
        """Сканирует HOOKS_DIR/*.py, загружает хуки разрешённые профилем."""
        self._loaded.clear()
        self._active_hooks.clear()
        self._profile = profile

        if profile is None:
            _log.info("Хуки выключены (профиль off)")
            return 0

        allowed = _PROFILE_HOOKS.get(profile, set())
        if not allowed:
            return 0

        loaded = 0
        for py_file in sorted(HOOKS_DIR.glob("*.py")):
            hook_name = py_file.stem
            if hook_name not in VALID_HOOKS:
                _log.debug("Пропущен %s — неизвестное имя хука", py_file)
                continue
            if hook_name not in allowed:
                _log.debug("Пропущен %s — не входит в профиль %s", py_file, profile.value)
                continue
            if self._load_one(hook_name, py_file):
                loaded += 1

        _log.info("Загружено %d хуков (профиль=%s)", loaded, profile.value)
        return loaded

    def _load_one(self, hook_name: str, path: Path) -> bool:
        """Загружает один .py файл через importlib."""
        mod_name = f"hook_{hook_name}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, str(path))
            if spec is None or spec.loader is None:
                _log.warning("Не удалось загрузить spec для %s", path)
                return False
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            _log.warning("Ошибка загрузки хука %s", path, exc_info=True)
            return False

        fn = getattr(mod, hook_name, None)
        if fn is None or not callable(fn):
            _log.warning("Модуль %s не содержит async def %s(…)", path, hook_name)
            return False

        self._loaded[hook_name] = fn
        self._active_hooks.add(hook_name)
        return True

    # ── query ─────────────────────────────────────────────────────────

    def has(self, hook_name: str) -> bool:
        return hook_name in self._active_hooks

    def get(self, hook_name: str) -> Callable[..., Any] | None:
        return self._loaded.get(hook_name)

    @property
    def active(self) -> set[str]:
        return frozenset(self._active_hooks)  # type: ignore[return-value]

    @property
    def profile(self) -> HookProfile | None:
        return self._profile


# ── Singleton access ───────────────────────────────────────────────────

_hook_manager: HookManager | None = None


def get_hook_manager() -> HookManager:
    """Возвращает глобальный singleton HookManager."""
    global _hook_manager
    if _hook_manager is None:
        _hook_manager = HookManager()
    return _hook_manager


def init_hooks(profile_raw: str | None = None) -> int:
    """Инициализирует хуки из env (вызывается при старте приложения)."""
    profile = _resolve_profile(profile_raw or os.getenv("ECC_HOOK_PROFILE", "standard"))
    return get_hook_manager().load(profile)


# ── Convenience: async invoke wrappers ─────────────────────────────────


async def invoke_pre_tool_use(
    tool_name: str,
    args: dict[str, Any],
    session_id: str | None = None,
) -> HookResult | None:
    """Ждёт PreToolUse-хук (блокирующий, таймаут 2s, fail-open)."""
    hm = get_hook_manager()
    fn = hm.get("pre_tool_use")
    if fn is None:
        return None

    async def _call() -> Any:
        result = await fn(tool_name=tool_name, args=args, session_id=session_id)
        if isinstance(result, dict):
            return HookResult(
                action=result.get("action", "continue"),
                message=result.get("message", ""),
                modified_args=result.get("modified_args"),
            )
        return result

    raw = await _invoke_with_timeout(_call(), "pre_tool_use", timeout=2.0)
    if isinstance(raw, HookResult):
        return raw
    if isinstance(raw, dict):
        return HookResult(
            action=raw.get("action", "continue"),
            message=raw.get("message", ""),
            modified_args=raw.get("modified_args"),
        )
    return None


def fire_post_tool_use(
    tool_name: str,
    args: dict[str, Any],
    result: str,
    duration_ms: int = 0,
    session_id: str | None = None,
) -> None:
    """Запускает PostToolUse в фоне (fire-and-forget)."""
    hm = get_hook_manager()
    fn = hm.get("post_tool_use")
    if fn is None:
        return
    _fire_and_forget(
        fn(tool_name=tool_name, args=args, result=result, duration_ms=duration_ms, session_id=session_id),
        "post_tool_use",
        timeout=5.0,
    )


async def invoke_user_prompt_submit(
    message: str,
    session_id: str | None = None,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Ждёт UserPromptSubmit-хук, возвращает injected context (может быть пустым)."""
    hm = get_hook_manager()
    fn = hm.get("user_prompt_submit")
    if fn is None:
        return ""
    result = await _invoke_with_timeout(
        fn(message=message, session_id=session_id, history=history or []),
        "user_prompt_submit",
        timeout=2.0,
    )
    if isinstance(result, dict):
        return result.get("context", "")
    if isinstance(result, HookResult):
        return result.context
    return ""


def fire_stop(
    session_id: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    client_session_id: str | None = None,
) -> None:
    """Запускает Stop-хук в фоне."""
    hm = get_hook_manager()
    fn = hm.get("stop")
    if fn is None:
        return
    _fire_and_forget(
        fn(session_id=session_id, messages=messages or [], decisions=decisions or [],
           client_session_id=client_session_id),
        "stop",
        timeout=5.0,
    )


async def invoke_pre_compact(
    session_id: str | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> str:
    """Ждёт PreCompact-хук, возвращает extracted context."""
    hm = get_hook_manager()
    fn = hm.get("pre_compact")
    if fn is None:
        return ""
    result = await _invoke_with_timeout(
        fn(session_id=session_id, messages=messages or []),
        "pre_compact",
        timeout=3.0,
    )
    if isinstance(result, dict):
        return result.get("context", "")
    if isinstance(result, HookResult):
        return result.context
    return ""


def fire_session_start(session_id: str | None = None, session_key: str | None = None) -> None:
    """Запускает SessionStart-хук в фоне."""
    hm = get_hook_manager()
    fn = hm.get("session_start")
    if fn is None:
        return
    _fire_and_forget(
        fn(session_id=session_id, session_key=session_key),
        "session_start",
        timeout=5.0,
    )


def fire_notification(
    session_id: str | None = None,
    message: str = "",
    stop_reason: str = "",
) -> None:
    """Запускает Notification-хук в фоне."""
    hm = get_hook_manager()
    fn = hm.get("notification")
    if fn is None:
        return
    _fire_and_forget(
        fn(session_id=session_id, message=message, stop_reason=stop_reason),
        "notification",
        timeout=5.0,
    )


def fire_cron_complete(job_id: str, result: dict[str, Any] | None = None) -> None:
    """Запускает CronComplete-хук в фоне."""
    hm = get_hook_manager()
    fn = hm.get("cron_complete")
    if fn is None:
        return
    _fire_and_forget(
        fn(job_id=job_id, result=result or {}),
        "cron_complete",
        timeout=5.0,
    )
