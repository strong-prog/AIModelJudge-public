"""Стриминговые запросы к первичным моделям с live-трансляцией в панели.

Поддерживает multi-turn tool use — первичные модели получают те же инструменты,
что и центральный агент. События primary_tool_start/primary_tool_end
транслируются в панели через side_event_queue.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI


# ── .env fallback ──────────────────────────────────────────────────────

def _load_hermes_dotenv() -> None:
    """Загружает переменные из ~/.hermes/.env, если они ещё не заданы в окружении."""
    dotenv_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.isfile(dotenv_path):
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_hermes_dotenv()


# ── Module-level state ─────────────────────────────────────────────────

_side_event_queue: asyncio.Queue | None = None
_primary_tools: dict[str, list[dict] | None] = {"left": None, "right": None}


def set_side_event_queue(q: asyncio.Queue | None) -> None:
    global _side_event_queue
    _side_event_queue = q


def set_primary_tools(tools: list[dict] | None, panel: str = "both") -> None:
    """Задать инструменты, доступные первичным моделям (без query_primary_models).
    panel: 'left', 'right', или 'both' (установить для обеих панелей)."""
    global _primary_tools
    if panel == "both":
        _primary_tools["left"] = tools
        _primary_tools["right"] = tools
    else:
        _primary_tools[panel] = tools


# ── Restricted tool set for side models ─────────────────────────────────

PRIMARY_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "read_file",
        "description": (
            "Прочитать файл с диска с номерами строк. "
            "Используй offset и limit для больших файлов. "
            "Только чтение — запись запрещена."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Абсолютный путь к файлу.",
                },
                "offset": {
                    "type": "integer",
                    "description": "С какой строки начать (1-индексация).",
                    "default": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Максимум строк (по умолчанию 500, максимум 2000).",
                    "default": 500,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "glob",
        "description": "Найти файлы по glob-паттерну (например, **/*.py). Только чтение.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob-паттерн, например '**/*.py' или 'src/**/*.ts'.",
                },
                "path": {
                    "type": "string",
                    "description": "Директория для поиска (по умолчанию текущая).",
                    "default": ".",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Поиск по содержимому файлов через регулярные выражения (ripgrep). Только чтение.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Регулярное выражение для поиска.",
                },
                "path": {
                    "type": "string",
                    "description": "Директория или файл для поиска.",
                    "default": ".",
                },
                "glob": {
                    "type": "string",
                    "description": "Фильтр файлов, например '*.py'.",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": "Режим вывода.",
                    "default": "content",
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Максимум результатов (по умолчанию 50).",
                    "default": 50,
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "web_search",
        "description": "Поиск в интернете через SearXNG. Не более 10 вызовов за сессию.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Максимум результатов (по умолчанию 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Загрузить и извлечь содержимое веб-страницы. Не более 10 вызовов за сессию.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL страницы для загрузки.",
                },
            },
            "required": ["url"],
        },
    },
]


# ── AIProxy (hermes-smart-router) ───────────────────────────────────────

_SIDE_PROXY_URL = os.getenv("AMJ_SIDE_PROXY_URL", "http://127.0.0.1:9084/v1").strip()
_SIDE_PROXY_KEY = os.getenv("AMJ_SIDE_PROXY_KEY", "")

# Маппинг имён моделей для прокси (наши селекты → имена в роутере)
_PROXY_MODEL_MAP: dict[str, str] = {
    # Claude: model IDs → short names used by hermes-smart-router
    "claude-sonnet-4-20250514": "claude-sonnet-4.6",
    "claude-opus-4-20250514": "claude-opus-4.7",
}


def _map_model_for_proxy(model: str) -> str:
    """Преобразовать имя модели для прокси, если нужно."""
    return _PROXY_MODEL_MAP.get(model, model)


# ── API key/base URL resolution ────────────────────────────────────────

def _resolve_api_key(model: str) -> Optional[str]:
    if _SIDE_PROXY_URL:
        return _SIDE_PROXY_KEY
    if model.startswith("deepseek"):
        return os.getenv("DEEPSEEK_API_KEY")
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return os.getenv("OPENAI_API_KEY")
    if model.startswith("claude"):
        return os.getenv("ANTHROPIC_API_KEY")
    if model.startswith("gemini"):
        return os.getenv("GEMINI_API_KEY")
    return os.getenv("OPENAI_API_KEY")


def _resolve_base_url(model: str) -> str:
    if _SIDE_PROXY_URL:
        return _SIDE_PROXY_URL
    if model.startswith("deepseek"):
        return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if model.startswith("claude"):
        return os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
    if model.startswith("gemini"):
        return os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


def _translate_tools_to_openai(tools: list[dict] | None) -> list[dict] | None:
    """Anthropic-формат инструментов → OpenAI-формат."""
    if not tools:
        return None
    openai_tools: list[dict] = []
    for t in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        })
    return openai_tools


# ── Tool definition ────────────────────────────────────────────────────

TOOL_DEF = {
    "name": "query_primary_models",
    "description": (
        "Консультация с экспертами (side-модели). Вызывай ПОСЛЕ первичного "
        "анализа запроса (глубокий анализ кода НЕ требуется). "
        "Работает для ЛЮБЫХ запросов: сравнение технологий, архитектура, "
        "код-ревью, дебаг, теория. "
        "Отправляет enriched query экспертам для параллельной консультации. "
        "Ответы стримятся в боковые панели. "
        "Возвращает структурированные ответы для синтеза итогового решения."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "ОБОГАЩЁННЫЙ запрос для экспертов. Включи: "
                    "1) исходную проблему/вопрос пользователя, "
                    "2) релевантный контекст (код, grep, теория, доки — что применимо), "
                    "3) сформулированные гипотезы или альтернативы, "
                    "4) конкретный вопрос к экспертам."
                ),
            },
            "model_left": {
                "type": "string",
                "description": "Модель для левой панели (например, deepseek-chat).",
            },
            "model_right": {
                "type": "string",
                "description": "Модель для правой панели (например, gpt-4o).",
            },
        },
        "required": ["query", "model_left"],
    },
}


# ── Per-model streaming (with multi-turn tool loop) ────────────────────

SIDE_MODEL_SYSTEM_PROMPT = """Ты — эксперт-консультант в совете экспертов AIModelJudge.
Твоя роль: дать глубокий, технически точный и конкретный ответ на enriched query,
которую прислал Central Judge (главный архитектор).

ФОРМАТ ОТВЕТА:
1. Прямой ответ на вопрос — конкретное решение с кодом, если применимо
2. Обоснование — почему это решение правильное (со ссылками на код/доку)
3. Альтернативы — если есть другие подходы, упомяни кратко с плюсами/минусами
4. Риски — что может пойти не так, краевые случаи

ПРАВИЛА:
- Ты НЕ принимаешь итоговое решение — Central Judge синтезирует ответы всех экспертов
- НЕ сравнивай себя с другими экспертами и не оценивай их
- НЕ перефразируй вопрос — сразу к делу
- Если доступны инструменты (🧠 включены) — используй read_file/grep для верификации
- Если инструментов нет — опирайся на контекст из enriched query
- Предлагай КОНКРЕТНЫЙ код (edit_file/write_file), а не общие рассуждения
- Если enriched query содержит результаты grep/read_file — используй их как факты
- Отвечай на русском языке (как в запросе)"""


async def _dispatch_with_hooks(tool_name: str, tool_input: dict) -> str:
    """Обёртка dispatch с PreToolUse/PostToolUse хуками + AgentShield Rules для side-моделей."""
    from services.shared.tool_executor import dispatch

    # AgentShield Rules Engine check
    try:
        from rules import get_rules_engine
        engine = get_rules_engine()
        if engine.is_loaded:
            violations = engine.check_tool(tool_name, dict(tool_input))
            blocks = [v for v in violations if v.get("action") == "block"]
            if blocks:
                return json.dumps({
                    "error": "Инструмент заблокирован правилами безопасности",
                    "violations": [{k: v for k, v in b.items() if k != "args_summary"} for b in blocks],
                }, ensure_ascii=False)
    except ImportError:
        pass
    except Exception:
        pass

    try:
        from hooks import invoke_pre_tool_use, fire_post_tool_use as _fire_ptu
        hook_result = await invoke_pre_tool_use(tool_name=tool_name, args=dict(tool_input))
        if hook_result is not None and hook_result.action == "block":
            return json.dumps(
                {"error": f"Инструмент заблокирован: {hook_result.message}"},
                ensure_ascii=False,
            )
        if hook_result is not None and hook_result.modified_args:
            tool_input = hook_result.modified_args
        result = await dispatch(tool_name, tool_input)
        _fire_ptu(tool_name=tool_name, args=tool_input, result=result, duration_ms=0)
        return result
    except ImportError:
        return await dispatch(tool_name, tool_input)


async def _stream_one(
    query: str,
    model: str,
    panel: str,
    tools: list[dict] | None = None,
    max_rounds: int = 10,
) -> dict:
    """Стримит ответ одной первичной модели с поддержкой multi-turn tool use.

    События (primary_thinking_token, primary_text_token, primary_tool_start,
    primary_tool_end, primary_done, primary_error) пушатся в _side_event_queue.
    """
    from services.shared.tool_executor import dispatch

    api_key = _resolve_api_key(model)
    base_url = _resolve_base_url(model)
    if _SIDE_PROXY_URL:
        model = _map_model_for_proxy(model)

    if not api_key:
        err = f"Нет API-ключа для модели {model}"
        q = _side_event_queue
        if q is not None:
            await q.put({
                "type": "primary_error",
                "panel": panel,
                "message": err,
            })
        return {"model": model, "content": "", "reasoning_content": "", "error": err}

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    start = time.monotonic()
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    error: Optional[str] = None
    tool_calls_total = 0

    openai_tools = _translate_tools_to_openai(tools)
    messages: list[dict] = [
        {"role": "system", "content": SIDE_MODEL_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    # Check model cache before API call
    from web.model_cache import get_cache as _get_mcache
    _mcache = _get_mcache()
    _cached = _mcache.get(model, messages)
    if _cached is not None:
        q = _side_event_queue
        if q is not None:
            if _cached.get("content"):
                await q.put({"type": "primary_text_token", "panel": panel, "token": _cached["content"]})
            if _cached.get("reasoning_content"):
                await q.put({"type": "primary_thinking_token", "panel": panel, "token": _cached["reasoning_content"]})
            await q.put({"type": "primary_done", "panel": panel, "content": _cached.get("content", ""),
                          "reasoning_content": _cached.get("reasoning_content", ""), "elapsed_ms": 0})
        return _cached

    # Rate limiting for side models: max 10 web calls per session
    web_call_count = 0
    MAX_WEB_CALLS = 10

    try:
        for _round_idx in range(max_rounds):
            tool_use_map: dict[int, dict] = {}  # index → {id, name, arguments_str}
            finish_reason = None

            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=4000,
                tools=openai_tools,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # --- reasoning_content (DeepSeek thinking) ---
                if getattr(delta, "reasoning_content", None):
                    token = delta.reasoning_content
                    reasoning_parts.append(token)
                    q = _side_event_queue
                    if q is not None:
                        await q.put({
                            "type": "primary_thinking_token",
                            "panel": panel,
                            "token": token,
                        })

                # --- tool_calls ---
                tc_list = getattr(delta, "tool_calls", None)
                if tc_list:
                    for tc in tc_list:
                        idx = tc.index
                        if idx not in tool_use_map:
                            func_name = tc.function.name if tc.function else "unknown"
                            tool_use_map[idx] = {
                                "id": tc.id or f"call_{idx}",
                                "name": func_name,
                                "arguments_str": "",
                            }
                            q = _side_event_queue
                            if q is not None:
                                await q.put({
                                    "type": "primary_tool_start",
                                    "panel": panel,
                                    "name": func_name,
                                    "label": func_name,
                                })
                        if tc.function and tc.function.arguments:
                            tool_use_map[idx]["arguments_str"] += tc.function.arguments

                # --- text content ---
                if delta.content:
                    token = delta.content
                    content_parts.append(token)
                    q = _side_event_queue
                    if q is not None:
                        await q.put({
                            "type": "primary_text_token",
                            "panel": panel,
                            "token": token,
                        })

                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None

            # --- Process round result ---
            if finish_reason == "tool_calls" and tool_use_map:
                tool_calls_total += len(tool_use_map)
                assistant_tool_calls: list[dict] = []
                tool_results_msgs: list[dict] = []

                for idx in sorted(tool_use_map.keys()):
                    tm = tool_use_map[idx]
                    try:
                        parsed_args = json.loads(tm["arguments_str"])
                    except json.JSONDecodeError:
                        parsed_args = {}

                    q = _side_event_queue
                    if q is not None:
                        await q.put({
                            "type": "primary_tool_end",
                            "panel": panel,
                            "name": tm["name"],
                            "label": tm["name"],
                            "input": parsed_args,
                        })

                    # Enforce web call limit and blocked tools for side models
                    tool_name = tm["name"]
                    BLOCKED_TOOLS = {"bash", "write_file", "edit_file", "query_primary_models"}
                    if tool_name in BLOCKED_TOOLS:
                        result_str = json.dumps({
                            "error": f"Инструмент {tool_name} заблокирован для боковых моделей. "
                                     f"Доступны только read-only инструменты."
                        }, ensure_ascii=False)
                    elif tool_name in ("web_search", "web_fetch"):
                        if web_call_count >= MAX_WEB_CALLS:
                            result_str = json.dumps({
                                "error": f"Лимит веб-вызовов исчерпан ({MAX_WEB_CALLS}/сессию). "
                                         f"Используй уже полученную информацию."
                            }, ensure_ascii=False)
                        else:
                            web_call_count += 1
                            result_str = await _dispatch_with_hooks(tm["name"], parsed_args)
                    else:
                        result_str = await _dispatch_with_hooks(tm["name"], parsed_args)
                    tool_results_msgs.append({
                        "role": "tool",
                        "tool_call_id": tm["id"],
                        "content": result_str,
                    })
                    assistant_tool_calls.append({
                        "id": tm["id"],
                        "type": "function",
                        "function": {
                            "name": tm["name"],
                            "arguments": tm["arguments_str"],
                        },
                    })

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": assistant_tool_calls,
                })
                messages.extend(tool_results_msgs)
                continue  # next round

            # stop, length, or no tool_calls — done
            break

    except asyncio.TimeoutError:
        error = "Timeout after 120s"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc!s}"

    elapsed = (time.monotonic() - start) * 1000
    full_content = "".join(content_parts)
    full_reasoning = "".join(reasoning_parts)

    # ── Benchmark tracking ──
    try:
        from web.benchmarks import get_tracker as _get_btracker, RequestMetrics
        _btracker = _get_btracker()
        _tokens_est = max(len(query) // 3, 1)
        _btracker.track(RequestMetrics(
            request_id=f"{model}:{panel}",
            timestamp=time.time(),
            phase="consult",
            model=model,
            tokens_in=_tokens_est,
            tokens_out=len(full_content) // 3,
            duration_ms=round(elapsed, 1),
            tool_calls_count=tool_calls_total,
            success=error is None,
        ))
    except Exception:
        pass

    if error:
        q = _side_event_queue
        if q is not None:
            await q.put({
                "type": "primary_error",
                "panel": panel,
                "message": error,
            })
        return {
            "model": model, "content": full_content,
            "reasoning_content": full_reasoning,
            "elapsed_ms": round(elapsed, 1), "error": error,
        }

    result = {
        "model": model,
        "content": full_content,
        "reasoning_content": full_reasoning,
        "elapsed_ms": round(elapsed, 1),
    }

    _mcache.set(model, messages, result)

    q = _side_event_queue
    if q is not None:
        await q.put({
            "type": "primary_done",
            "panel": panel,
            "content": full_content,
            "reasoning_content": full_reasoning,
            "elapsed_ms": round(elapsed, 1),
        })

    return result

# ── Company Mode: specialist streaming (fork of _stream_one) ───────────

async def _stream_one_with_context(
    query: str,
    model: str,
    panel: str,
    system_prompt: str,
    tools: list[dict] | None = None,
    max_rounds: int = 10,
    specialist_config=None,  # SpecialistConfig | None
) -> dict:
    """Like _stream_one() but accepts a custom system_prompt and SpecialistConfig.

    Used by Company Mode: each specialist gets its own role-specific system prompt
    loaded from specialists/{name}/BRIEFING.md.
    """
    from services.shared.tool_executor import dispatch

    api_key = _resolve_api_key(model)
    base_url = _resolve_base_url(model)
    if _SIDE_PROXY_URL:
        model = _map_model_for_proxy(model)

    if not api_key:
        err = f"Нет API-ключа для модели {model}"
        q = _side_event_queue
        if q is not None:
            await q.put({
                "type": "primary_error",
                "panel": panel,
                "message": err,
            })
        return {"model": model, "content": "", "reasoning_content": "", "error": err}

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    start = time.monotonic()
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    error: Optional[str] = None
    tool_calls_total = 0

    openai_tools = _translate_tools_to_openai(tools)
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    # Resolve blocked tools from specialist config or use defaults
    if specialist_config and hasattr(specialist_config, 'tools_denylist'):
        BLOCKED_TOOLS = specialist_config.tools_denylist
    else:
        BLOCKED_TOOLS = frozenset({"bash", "write_file", "edit_file", "query_primary_models"})

    # Check model cache
    from web.model_cache import get_cache as _get_mcache
    _mcache = _get_mcache()
    _cached = _mcache.get(model, messages)
    if _cached is not None:
        q = _side_event_queue
        if q is not None:
            if _cached.get("content"):
                await q.put({"type": "primary_text_token", "panel": panel, "token": _cached["content"]})
            if _cached.get("reasoning_content"):
                await q.put({"type": "primary_thinking_token", "panel": panel, "token": _cached["reasoning_content"]})
            await q.put({"type": "primary_done", "panel": panel, "content": _cached.get("content", ""),
                          "reasoning_content": _cached.get("reasoning_content", ""), "elapsed_ms": 0})
        return _cached

    web_call_count = 0
    MAX_WEB_CALLS = 10

    try:
        for _round_idx in range(max_rounds):
            tool_use_map: dict[int, dict] = {}
            finish_reason = None

            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=4000,
                tools=openai_tools,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                if getattr(delta, "reasoning_content", None):
                    token = delta.reasoning_content
                    reasoning_parts.append(token)
                    q = _side_event_queue
                    if q is not None:
                        await q.put({
                            "type": "primary_thinking_token",
                            "panel": panel,
                            "token": token,
                        })

                tc_list = getattr(delta, "tool_calls", None)
                if tc_list:
                    for tc in tc_list:
                        idx = tc.index
                        if idx not in tool_use_map:
                            func_name = tc.function.name if tc.function else "unknown"
                            tool_use_map[idx] = {
                                "id": tc.id or f"call_{idx}",
                                "name": func_name,
                                "arguments_str": "",
                            }
                            q = _side_event_queue
                            if q is not None:
                                await q.put({
                                    "type": "primary_tool_start",
                                    "panel": panel,
                                    "name": func_name,
                                    "label": func_name,
                                })
                        if tc.function and tc.function.arguments:
                            tool_use_map[idx]["arguments_str"] += tc.function.arguments

                if delta.content:
                    token = delta.content
                    content_parts.append(token)
                    q = _side_event_queue
                    if q is not None:
                        await q.put({
                            "type": "primary_text_token",
                            "panel": panel,
                            "token": token,
                        })

                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None

            if finish_reason == "tool_calls" and tool_use_map:
                tool_calls_total += len(tool_use_map)
                assistant_tool_calls: list[dict] = []
                tool_results_msgs: list[dict] = []

                for idx in sorted(tool_use_map.keys()):
                    tm = tool_use_map[idx]
                    try:
                        parsed_args = json.loads(tm["arguments_str"])
                    except json.JSONDecodeError:
                        parsed_args = {}

                    q = _side_event_queue
                    if q is not None:
                        await q.put({
                            "type": "primary_tool_end",
                            "panel": panel,
                            "name": tm["name"],
                            "label": tm["name"],
                            "input": parsed_args,
                        })

                    tool_name = tm["name"]
                    if tool_name in BLOCKED_TOOLS:
                        result_str = json.dumps({
                            "error": f"Инструмент {tool_name} заблокирован для специалиста. "
                                     f"Доступны только read-only инструменты."
                        }, ensure_ascii=False)
                    elif tool_name in ("web_search", "web_fetch"):
                        if web_call_count >= MAX_WEB_CALLS:
                            result_str = json.dumps({
                                "error": f"Лимит веб-вызовов исчерпан ({MAX_WEB_CALLS}/сессию). "
                                         f"Используй уже полученную информацию."
                            }, ensure_ascii=False)
                        else:
                            web_call_count += 1
                            result_str = await _dispatch_with_hooks(tm["name"], parsed_args)
                    else:
                        result_str = await _dispatch_with_hooks(tm["name"], parsed_args)
                    tool_results_msgs.append({
                        "role": "tool",
                        "tool_call_id": tm["id"],
                        "content": result_str,
                    })
                    assistant_tool_calls.append({
                        "id": tm["id"],
                        "type": "function",
                        "function": {
                            "name": tm["name"],
                            "arguments": tm["arguments_str"],
                        },
                    })

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": assistant_tool_calls,
                })
                messages.extend(tool_results_msgs)
                continue

            break

    except asyncio.TimeoutError:
        error = "Timeout after 120s"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc!s}"

    elapsed = (time.monotonic() - start) * 1000
    full_content = "".join(content_parts)
    full_reasoning = "".join(reasoning_parts)

    try:
        from web.benchmarks import get_tracker as _get_btracker, RequestMetrics
        _btracker = _get_btracker()
        _tokens_est = max(len(query) // 3, 1)
        _btracker.track(RequestMetrics(
            request_id=f"{model}:{panel}",
            timestamp=time.time(),
            phase="consult",
            model=model,
            tokens_in=_tokens_est,
            tokens_out=len(full_content) // 3,
            duration_ms=round(elapsed, 1),
            tool_calls_count=tool_calls_total,
            success=error is None,
        ))
    except Exception:
        pass

    if error:
        q = _side_event_queue
        if q is not None:
            await q.put({
                "type": "primary_error",
                "panel": panel,
                "message": error,
            })
        return {
            "model": model, "content": full_content,
            "reasoning_content": full_reasoning,
            "elapsed_ms": round(elapsed, 1), "error": error,
        }

    result = {
        "model": model,
        "content": full_content,
        "reasoning_content": full_reasoning,
        "elapsed_ms": round(elapsed, 1),
    }

    _mcache.set(model, messages, result)

    q = _side_event_queue
    if q is not None:
        await q.put({
            "type": "primary_done",
            "panel": panel,
            "content": full_content,
            "reasoning_content": full_reasoning,
            "elapsed_ms": round(elapsed, 1),
        })

    return result


# ── Streaming handler (tool entry point) ───────────────────────────────

def _build_synthesis_prompt(responses: list[dict]) -> str:
    """Строит шаблон синтеза для Central Judge после получения ответов экспертов."""
    expert_count = len(responses)
    if expert_count == 0:
        return ""

    # Имена экспертов для обращения
    expert_names: list[str] = []
    for r in responses:
        model = r.get("model", "unknown")
        panel = r.get("panel", "?")
        expert_names.append(f"{model} ({panel})")

    experts_list = "\n".join(f"  • {n}" for n in expert_names)

    # Ошибки экспертов
    errors = [r for r in responses if r.get("error")]
    error_block = ""
    if errors:
        error_block = "\n\n⚠ ВНИМАНИЕ: некоторые эксперты вернули ошибки:\n"
        for e in errors:
            error_block += f"  • {e.get('model', '?' )}: {e.get('error', '')}\n"
        error_block += "Если ошибка у обоих экспертов — ответь самостоятельно на основе своего анализа (ШАГ 1)."

    return f"""ОТВЕТЫ ЭКСПЕРТОВ ПОЛУЧЕНЫ ({expert_count} из {expert_count}). ТЕПЕРЬ:

1. ВЫДЕЛИ КОНСЕНСУС — в чём все эксперты согласны. Процитируй конкретные утверждения.

2. ВЫЯВИ ПРОТИВОРЕЧИЯ — где эксперты расходятся. Проверь спорные утверждения через codegraph_explore / read_file / grep. Определи кто прав.

3. НАЙДИ ПРОБЕЛЫ — что ВСЕ эксперты упустили. Добавь свой анализ на основе Шага 1.

4. ВЫДАЙ ИДЕАЛЬНОЕ РЕШЕНИЕ — синтезируй консенсус + разрешённые противоречия + свой анализ в ОДИН ответ. Если нужны правки кода — предложи конкретные edit_file.

5. ПРИМЕНИ решение (edit_file / bash) или ответь пользователю.

Эксперты:
{experts_list}
{error_block}"""


async def handle_query_primary_models(args: dict) -> str:
    """Запрашивает первичные модели параллельно со стримингом в панели.
    Поддерживает 1 или 2 модели (model_right опционален)."""
    query = args.get("query", "")
    model_left = args.get("model_left", "")
    model_right = args.get("model_right", "")

    if not query:
        return json.dumps({"error": "Пустой запрос"}, ensure_ascii=False)

    tasks = []
    panels: list[str] = []

    if model_left:
        tasks.append(_stream_one(query, model_left, "left", tools=_primary_tools.get("left")))
        panels.append("left")
    if model_right:
        tasks.append(_stream_one(query, model_right, "right", tools=_primary_tools.get("right")))
        panels.append("right")

    if not tasks:
        return json.dumps({"error": "Не указаны модели"}, ensure_ascii=False)

    results = await asyncio.gather(*tasks)
    responses = []
    for i, result in enumerate(results):
        result["panel"] = panels[i]
        responses.append(result)

    synthesis = _build_synthesis_prompt(responses)

    return json.dumps({
        "synthesis_prompt": synthesis,
        "responses": responses,
    }, ensure_ascii=False)
