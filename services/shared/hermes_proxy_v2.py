"""Локальный Web Agent — aiohttp SSE-прокси до /v1/messages (Anthropic) и /v1/chat/completions (OpenAI).

Поддерживает два бэкенда:
- Anthropic /v1/messages — thinking + tool_use + text блоки (основной)
- OpenAI /v1/chat/completions — text + tool_calls (fallback, без thinking)

Автоопределение: если /v1/messages возвращает 404, переключается на OpenAI-формат.

Формат событий на выходе:
    {"type": "message.started", "message": {"id": "...", "role": "assistant", "model": "..."}}
    {"type": "thinking_start"}
    {"type": "thinking_token", "token": "..."}
    {"type": "thinking_end"}
    {"type": "tool_start", "name": "...", "input": {}}
    {"type": "tool_token", "token": "..."}
    {"type": "tool_end", "name": "..."}
    {"type": "text_start"}
    {"type": "text_token", "token": "..."}
    {"type": "text_end"}
    {"type": "message.completed", "message": {"id": "...", "stop_reason": "..."}}
    {"type": "done", "stop_reason": "...", "usage": {...}}
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import aiohttp

# Известные имена инструментов и их человекочитаемые описания
TOOL_LABELS: dict[str, str] = {
    "read_file": "Читаю файл",
    "write_file": "Записываю файл",
    "edit_file": "Редактирую файл",
    "bash": "Выполняю команду",
    "glob": "Ищу файлы",
    "grep": "Ищу в коде",
    "web_search": "Ищу в интернете",
    "web_fetch": "Загружаю страницу",
    "codegraph_explore": "Анализирую код (codegraph)",
    "codegraph_search": "Ищу символ (codegraph)",
    "codegraph_node": "Читаю символ (codegraph)",
    "codegraph_callers": "Ищу вызовы (codegraph)",
    "memory_recall": "Ищу в памяти (memory-mcp)",
    "memory_remember": "Сохраняю в память (memory-mcp)",
    "task": "Создаю задачу",
    "agent": "Запускаю подагента",
}



def _tool_label(name: str) -> str:
    """Человекочитаемое описание инструмента."""
    return TOOL_LABELS.get(name, f"Вызываю {name}")


def _extract_tool_path(name: str, input_data: dict | None) -> str | None:
    """Извлечь путь к файлу из аргументов инструмента, если есть."""
    if not input_data:
        return None
    for key in ("file_path", "path", "file", "symbol", "pattern", "query"):
        val = input_data.get(key)
        if isinstance(val, str) and val:
            # Обрезаем до читаемой длины
            return val if len(val) <= 80 else "..." + val[-77:]
    return None


def _extract_tool_error(result_str: str) -> str | None:
    """Извлечь сообщение об ошибке из JSON-результата инструмента."""
    if not result_str:
        return None
    try:
        result = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(result, dict):
        return None
    # Явная ошибка
    if result.get("success") is False:
        return result.get("error") or "Неизвестная ошибка"
    # Поле error даже при success: true может содержать предупреждение — не считаем ошибкой
    if result.get("error") and result.get("success") is not True:
        return result["error"]
    return None


def _extract_kanban_event(tool_name: str, result_str: str) -> dict | None:
    """Извлечь канбан-событие из результата инструмента, если это канбан-инструмент."""
    if tool_name not in ("create_task", "move_task", "update_task"):
        return None
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    if tool_name == "create_task":
        return {
            "type": "kanban_task_created",
            "task_id": data.get("task_id", ""),
            "column": data.get("column", ""),
            "title": data.get("title", ""),
            "description": data.get("description", ""),
        }
    elif tool_name == "move_task":
        return {
            "type": "kanban_task_moved",
            "task_id": data.get("task_id", ""),
            "from_column": data.get("from_column", ""),
            "to_column": data.get("to_column", ""),
        }
    elif tool_name == "update_task":
        return {
            "type": "kanban_task_updated",
            "task_id": data.get("task_id", ""),
            "status": data.get("status", ""),
            "result": data.get("result", ""),
            "diff_added": data.get("diff_added", 0),
            "diff_removed": data.get("diff_removed", 0),
        }
    return None


def _build_plan_event() -> dict:
    """Построить ACP plan-событие из текущего состояния KanbanStore."""
    from services.shared.tool_executor import _kanban
    entries = _kanban.get_plan_snapshot()
    return {"type": "plan", "entries": entries}


# ── Token budget ─────────────────────────────────────────────────────────

_MAX_CONTEXT_TOKENS = 64_000
_TAIL_TOKENS = 20_000


def _estimate_message_tokens(msg: dict) -> int:
    content = str(msg.get("content", ""))
    return max(len(content) // 4, 1)


def _total_tokens(messages: list[dict]) -> int:
    return sum(_estimate_message_tokens(m) for m in messages)


def _trim_to_budget(messages: list[dict]) -> list[dict]:
    if not messages:
        return messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    user_msg = None
    if non_system and non_system[-1].get("role") == "user":
        user_msg = non_system.pop()
    tail: list[dict] = []
    tail_tokens = 0
    for m in reversed(non_system):
        t = _estimate_message_tokens(m)
        if tail_tokens + t > _TAIL_TOKENS:
            break
        tail.insert(0, m)
        tail_tokens += t
    result = system_msgs + tail
    if user_msg:
        result.append(user_msg)
    return result


def _deduplicate_instructions(system_prompt: str) -> str:
    import re
    lines = system_prompt.split("\n")
    seen_headers: set[str] = set()
    result: list[str] = []
    header_pattern = re.compile(r"^#{1,4}\s+.{3,}")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = header_pattern.match(line)
        if m:
            header_key = line.strip().lower()
            if header_key in seen_headers:
                i += 1
                while i < len(lines):
                    if header_pattern.match(lines[i]) or lines[i].strip() == "":
                        break
                    i += 1
                continue
            seen_headers.add(header_key)
        result.append(line)
        i += 1
    return "\n".join(result)


async def stream_hermes_events(
    messages: list[dict],
    *,
    cancel_event: asyncio.Event,
    hermes_messages_url: str,
    hermes_key: str,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    tools: list[dict] | None = None,
):
    """Генератор структурированных событий из Anthropic SSE-потока /v1/messages.

    Args:
        messages: Список сообщений в формате [{"role":"user","content":"..."}].
        cancel_event: Событие для остановки стриминга.
        hermes_messages_url: Полный URL до /v1/messages (напр. http://127.0.0.1:8084/v1/messages).
        hermes_key: API-ключ.
        temperature: Температура генерации.
        max_tokens: Максимальное число токенов ответа.
        tools: Список определений инструментов в Anthropic-формате.

    Yields:
        dict: Структурированное событие с полем type.
    """
    current_block_type: str | None = None
    _thinking_block_idx: int = -1  # count thinking blocks to split reasoning/answer
    tool_name: str | None = None
    tool_input_accumulator: str = ""
    total_usage: dict = {}

    async with aiohttp.ClientSession() as session:
        body: dict = {
            "model": "deepseek-v4-pro",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        try:
            async with session.post(
                hermes_messages_url,
                json=body,
                headers={
                    "Authorization": f"Bearer {hermes_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    yield {
                        "type": "error",
                        "message": f"Роутер вернул {resp.status}: {text[:300]}",
                    }
                    return

                content_type = resp.headers.get("Content-Type", "")

                # ── Нестриминговый ответ (полный JSON) ──
                if "application/json" in content_type:
                    full_text = await resp.text()
                    try:
                        full_msg = json.loads(full_text)
                    except json.JSONDecodeError:
                        yield {"type": "error", "message": f"Invalid JSON response: {full_text[:300]}"}
                        return

                    total_usage = full_msg.get("usage", {})
                    _current_message_id = full_msg.get("id", "")
                    yield {
                        "type": "message.started",
                        "message": {
                            "id": _current_message_id,
                            "role": full_msg.get("role", "assistant"),
                            "model": full_msg.get("model", ""),
                        },
                    }
                    _thinking_block_idx = -1
                    for block in full_msg.get("content", []):
                        block_type = block.get("type", "")
                        if block_type == "thinking":
                            _thinking_block_idx += 1
                            # First thinking block = reasoning → ThinkingBlock.
                            # Subsequent blocks = answer mapped from
                            # reasoning_content by DeepSeek → main chat.
                            if _thinking_block_idx == 0:
                                yield {"type": "thinking_start"}
                                thinking_text = block.get("thinking", "")
                                if thinking_text:
                                    yield {"type": "thinking_token", "token": thinking_text}
                                yield {"type": "thinking_end"}
                                yield {"type": "reasoning.available"}
                            else:
                                yield {"type": "text_start"}
                                thinking_text = block.get("thinking", "")
                                if thinking_text:
                                    yield {"type": "text_token", "token": thinking_text}
                                yield {"type": "text_end"}
                        elif block_type == "text":
                            yield {"type": "text_start"}
                            text = block.get("text", "")
                            if text:
                                yield {"type": "text_token", "token": text}
                            yield {"type": "text_end"}
                        elif block_type == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            yield {
                                "type": "tool_start",
                                "name": tool_name,
                                "label": _tool_label(tool_name),
                                "path": _extract_tool_path(tool_name, tool_input),
                            }
                            yield {
                                "type": "tool_token",
                                "token": json.dumps(tool_input, ensure_ascii=False),
                            }
                            yield {"type": "tool_end", "name": tool_name}

                    stop_reason = full_msg.get("stop_reason", "end_turn")
                    yield {"type": "done", "stop_reason": stop_reason, "usage": total_usage}
                    return

                # ── Стриминговый ответ (SSE) ──
                line_buffer = ""

                async for raw_line in resp.content:
                    if cancel_event.is_set():
                        yield {"type": "done", "stop_reason": "cancelled", "usage": total_usage}
                        return

                    try:
                        line_str = raw_line.decode("utf-8", errors="replace")
                    except Exception:
                        continue

                    line_buffer += line_str

                    # Обрабатываем полные строки
                    while "\n" in line_buffer:
                        line, line_buffer = line_buffer.split("\n", 1)
                        line = line.strip()

                        # Пропускаем строки event: (используем data: напрямую)
                        if not line or line.startswith("event:"):
                            continue

                        if not line.startswith("data:"):
                            continue

                        data_str = line[5:].strip()
                        if not data_str:
                            continue

                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        # --- message_start ---
                        if event_type == "message_start":
                            msg = event.get("message", {})
                            total_usage = msg.get("usage", {})
                            _current_message_id = msg.get("id", "")
                            yield {
                                "type": "message.started",
                                "message": {
                                    "id": _current_message_id,
                                    "role": msg.get("role", "assistant"),
                                    "model": msg.get("model", ""),
                                },
                            }
                            continue

                        # --- ping ---
                        if event_type == "ping":
                            continue

                        # --- content_block_start ---
                        if event_type == "content_block_start":
                            block = event.get("content_block", {})
                            block_type = block.get("type", "")
                            current_block_type = block_type

                            if block_type == "thinking":
                                _thinking_block_idx += 1
                                # First thinking block = reasoning (→ ThinkingBlock).
                                # Subsequent blocks = answer mapped from
                                # reasoning_content by DeepSeek (→ main chat).
                                if _thinking_block_idx == 0:
                                    yield {"type": "thinking_start"}
                                    thinking_text = block.get("thinking", "")
                                    if thinking_text:
                                        yield {"type": "thinking_token", "token": thinking_text}
                                else:
                                    yield {"type": "text_start"}
                                    thinking_text = block.get("thinking", "")
                                    if thinking_text:
                                        yield {"type": "text_token", "token": thinking_text}

                            elif block_type == "text":
                                yield {"type": "text_start"}

                            elif block_type == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                tool_input_accumulator = ""
                                yield {
                                    "type": "tool_start",
                                    "name": tool_name,
                                    "label": _tool_label(tool_name),
                                    "path": _extract_tool_path(tool_name, tool_input),
                                }
                                # Если input уже заполнен в block (не partial)
                                if tool_input:
                                    yield {
                                        "type": "tool_token",
                                        "token": json.dumps(tool_input, ensure_ascii=False),
                                    }

                            continue

                        # --- content_block_delta ---
                        if event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            delta_type = delta.get("type", "")

                            if delta_type == "thinking_delta":
                                thinking = delta.get("thinking", "")
                                if thinking:
                                    if _thinking_block_idx == 0:
                                        yield {"type": "thinking_token", "token": thinking}
                                    else:
                                        yield {"type": "text_token", "token": thinking}

                            elif delta_type == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield {"type": "text_token", "token": text}

                            elif delta_type == "input_json_delta":
                                partial = delta.get("partial_json", "")
                                tool_input_accumulator += partial
                                yield {"type": "tool_token", "token": partial}

                            continue

                        # --- content_block_stop ---
                        if event_type == "content_block_stop":
                            if current_block_type == "thinking":
                                if _thinking_block_idx == 0:
                                    yield {"type": "thinking_end"}
                                    yield {"type": "reasoning.available"}
                                else:
                                    yield {"type": "text_end"}
                            elif current_block_type == "text":
                                yield {"type": "text_end"}
                            elif current_block_type == "tool_use":
                                # Парсим накопленный JSON для пути
                                try:
                                    parsed_input = json.loads(tool_input_accumulator)
                                except json.JSONDecodeError:
                                    parsed_input = {}
                                yield {
                                    "type": "tool_end",
                                    "name": tool_name or "unknown",
                                    "label": _tool_label(tool_name or ""),
                                    "path": _extract_tool_path(tool_name or "", parsed_input),
                                    "input": parsed_input,
                                }
                                tool_name = None
                                tool_input_accumulator = ""

                            current_block_type = None
                            continue

                        # --- message_delta ---
                        if event_type == "message_delta":
                            delta = event.get("delta", {})
                            usage = event.get("usage", {})
                            if usage:
                                total_usage = usage
                            yield {
                                "type": "done",
                                "stop_reason": delta.get("stop_reason", "end_turn"),
                                "usage": total_usage,
                            }
                            continue

                        # --- message_stop ---
                        if event_type == "message_stop":
                            continue

        except aiohttp.ClientError as exc:
            yield {"type": "error", "message": f"Ошибка соединения с роутером: {exc}"}
        except TimeoutError:
            yield {"type": "error", "message": "Таймаут — роутер не ответил за 600с"}


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


def _stop_reason_from_openai(finish_reason: str | None) -> str:
    """OpenAI finish_reason → stop_reason."""
    if finish_reason == "tool_calls":
        return "tool_use"
    if finish_reason == "stop":
        return "end_turn"
    if finish_reason == "length":
        return "max_tokens"
    return finish_reason or "end_turn"


async def _stream_openai_events(
    messages: list[dict],
    *,
    cancel_event: asyncio.Event,
    hermes_chat_url: str,
    hermes_key: str,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    tools: list[dict] | None = None,
):
    """Генератор событий из OpenAI SSE-потока /v1/chat/completions.

    Транслирует OpenAI-формат в те же структурированные события,
    что и stream_hermes_events (thinking/text/tool/done).
    DeepSeek передаёт рассуждения в delta.reasoning_content — извлекаем как thinking.
    """
    openai_tools = _translate_tools_to_openai(tools)
    current_block_type: str | None = None  # "thinking" | "text" | "tool_use"
    tool_use_map: dict[int, dict] = {}  # index → {id, name, arguments_str}
    total_usage: dict = {}
    all_reasoning_content: list[str] = []  # raw reasoning_content for echo-back

    def _close_current(to_type: str | None):
        """Закрыть текущий блок если он не совпадает с to_type. Возвращает событие или None."""
        nonlocal current_block_type
        if current_block_type is None or current_block_type == to_type:
            return None
        event = (
            {"type": "thinking_end"}
            if current_block_type == "thinking"
            else {"type": "text_end"}
        )
        current_block_type = None
        return event

    async with aiohttp.ClientSession() as session:
        body: dict = {
            "model": "deepseek-v4-pro",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if openai_tools:
            body["tools"] = openai_tools

        try:
            async with session.post(
                hermes_chat_url,
                json=body,
                headers={
                    "Authorization": f"Bearer {hermes_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    yield {
                        "type": "error",
                        "message": f"Роутер вернул {resp.status}: {text[:300]}",
                    }
                    return

                _current_message_id = f"msg_{uuid.uuid4().hex[:12]}"
                yield {
                    "type": "message.started",
                    "message": {
                        "id": _current_message_id,
                        "role": "assistant",
                        "model": "deepseek-v4-pro",
                    },
                }

                line_buffer = ""

                async for raw_line in resp.content:
                    if cancel_event.is_set():
                        yield {"type": "done", "stop_reason": "cancelled", "usage": total_usage}
                        return

                    try:
                        line_str = raw_line.decode("utf-8", errors="replace")
                    except Exception:
                        continue

                    line_buffer += line_str

                    while "\n" in line_buffer:
                        line, line_buffer = line_buffer.split("\n", 1)
                        line = line.strip()

                        if not line or not line.startswith("data:"):
                            continue

                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue

                        choice = choices[0]
                        delta = choice.get("delta", {})
                        finish_reason = choice.get("finish_reason")

                        # --- usage (в последнем чанке) ---
                        usage = chunk.get("usage")
                        if usage:
                            total_usage = usage

                        # --- reasoning_content (DeepSeek) — emit as text_token.
                        # DeepSeek models may put the entire response (reasoning
                        # + answer) in reasoning_content, with delta.content
                        # staying empty.  Treating it as thinking_token would
                        # hide the answer in a collapsed block.  Emit it as
                        # text so it surfaces in the main chat area.
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            all_reasoning_content.append(reasoning)
                            if current_block_type != "text":
                                close_evt = _close_current("text")
                                if close_evt:
                                    yield close_evt
                                current_block_type = "text"
                                yield {"type": "text_start"}
                            yield {"type": "text_token", "token": reasoning}
                            continue

                        # --- tool_calls ---
                        tc_list = delta.get("tool_calls")
                        if tc_list:
                            for tc in tc_list:
                                idx = tc.get("index", 0)
                                if idx not in tool_use_map:
                                    func = tc.get("function", {})
                                    t_name = func.get("name", "unknown")
                                    tool_use_map[idx] = {
                                        "id": tc.get("id", f"call_{idx}"),
                                        "name": t_name,
                                        "arguments_str": "",
                                    }
                                    # Закрыть thinking/text перед tool_start
                                    if current_block_type != "tool_use":
                                        close_evt = _close_current("tool_use")
                                        if close_evt:
                                            yield close_evt
                                        current_block_type = "tool_use"
                                    yield {
                                        "type": "tool_start",
                                        "name": t_name,
                                        "label": _tool_label(t_name),
                                        "path": None,
                                    }
                                # Аргументы могут приходить частями
                                func = tc.get("function", {})
                                args_part = func.get("arguments", "")
                                if args_part:
                                    tool_use_map[idx]["arguments_str"] += args_part
                                    yield {"type": "tool_token", "token": args_part}
                            continue

                        # --- text ---
                        content = delta.get("content")
                        if content:
                            if current_block_type != "text":
                                close_evt = _close_current("text")
                                if close_evt:
                                    yield close_evt
                                current_block_type = "text"
                                yield {"type": "text_start"}
                            yield {"type": "text_token", "token": content}
                            continue

                        # --- finish_reason (конец ответа) ---
                        if finish_reason:
                            if current_block_type == "tool_use":
                                # Отправляем tool_end для каждого инструмента
                                for idx in sorted(tool_use_map.keys()):
                                    tm = tool_use_map[idx]
                                    try:
                                        parsed_input = json.loads(tm["arguments_str"])
                                    except json.JSONDecodeError:
                                        parsed_input = {}
                                    yield {
                                        "type": "tool_end",
                                        "name": tm["name"],
                                        "label": _tool_label(tm["name"]),
                                        "path": _extract_tool_path(tm["name"], parsed_input),
                                        "input": parsed_input,
                                    }
                            elif current_block_type == "thinking":
                                yield {"type": "thinking_end"}
                                yield {"type": "reasoning.available"}
                            elif current_block_type == "text":
                                yield {"type": "text_end"}

                            current_block_type = None
                            yield {
                                "type": "done",
                                "stop_reason": _stop_reason_from_openai(finish_reason),
                                "usage": total_usage,
                                "reasoning_content": "".join(all_reasoning_content),
                            }
                            continue

        except aiohttp.ClientError as exc:
            yield {"type": "error", "message": f"Ошибка соединения с роутером: {exc}"}
        except TimeoutError:
            yield {"type": "error", "message": "Таймаут — роутер не ответил за 600с"}


def _build_usage_payload(accumulated: dict, rounds: list[dict]) -> dict:
    """Собрать usage с расчётом стоимости для фронтенда."""
    total_input = (
        accumulated.get("input_tokens", 0)
        + accumulated.get("cache_read_input_tokens", 0)
        + accumulated.get("cache_creation_input_tokens", 0)
    )
    total_output = accumulated.get("output_tokens", 0)
    total_tokens = total_input + total_output
    cost_usd = 0.0
    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_tokens,
        "cost_usd": round(cost_usd, 6),
        "cost_rub": 0.0,
        "rounds": rounds,
    }


async def agentic_stream(
    system_prompt: str,
    user_message: str,
    *,
    cancel_event: asyncio.Event,
    hermes_messages_url: str,
    hermes_key: str,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    max_rounds: int = 25,
    tools: list[dict] | None = None,
    session_id: str = "",
    approval_registry: dict | None = None,
    hermes_chat_url: str | None = None,
    side_event_queue: asyncio.Queue | None = None,
    extra_tool_handlers: dict | None = None,
    history: list[dict] | None = None,
    user_id: str | None = None,
):
    """Agentic loop: отправляет запрос, выполняет tool_use, продолжает до end_turn.

    Если user_id передан, tool calls маршрутизируются на локальный агент
    пользователя (Dev Mode) вместо выполнения на сервере.

    Все раунды стримятся в одну SSE-сессию. Фронтенд получает события:
    thinking → tool_start/tool_end → done(stop_reason=tool_use)
    → round_start → thinking → text → done(stop_reason=end_turn)

    Автоопределение бэкенда: сначала пробует Anthropic /v1/messages.
    Если возвращает 404 — переключается на OpenAI /v1/chat/completions.

    Args:
        system_prompt: Системный промт.
        user_message: Сообщение пользователя.
        cancel_event: Событие для остановки всего цикла.
        hermes_messages_url: URL /v1/messages (Anthropic).
        hermes_key: API-ключ.
        temperature: Температура генерации.
        max_tokens: Максимум токенов на один вызов API.
        max_rounds: Максимальное число раундов tool_use.
        tools: Определения инструментов (None = без инструментов).
        hermes_chat_url: URL /v1/chat/completions (OpenAI fallback).
            Если не задан, автоопределение не работает — только Anthropic.
        history: История предыдущих сообщений (user/assistant).
            Вставляется между system_prompt и user_message.
    """
    from services.shared.tool_executor import DANGEROUS_TOOLS, _kanban, dispatch

    _kanban.set_session(session_id)

    messages: list[dict] = [
        {"role": "system", "content": _deduplicate_instructions(system_prompt)}
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    # Context window enforcement: trim if over token budget
    if _total_tokens(messages) > _MAX_CONTEXT_TOKENS:
        messages = _trim_to_budget(messages)

    accumulated_usage: dict[str, int] = {}
    rounds_usage: list[dict] = []
    backend: str = "anthropic"  # "anthropic" | "openai"
    backend_probed = False
    _current_message_id = ""  # reset each message boundary

    for round_idx in range(max_rounds):
        if cancel_event.is_set():
            yield {
                "type": "done",
                "stop_reason": "cancelled",
                "usage": _build_usage_payload(accumulated_usage, rounds_usage),
            }
            return

        if round_idx > 0:
            yield {"type": "round_start", "round": round_idx}

        # Аккумуляторы для одного ответа модели
        assistant_content_blocks: list[dict] = []
        current_thinking: str = ""
        thinking_signature: str = ""
        tool_use_blocks: list[dict] = []
        final_stop_reason: str = "end_turn"
        final_usage: dict = {}
        openai_reasoning: str = ""  # reasoning_content для round-trip в OpenAI-бэкенд

        # Выбираем стример в зависимости от бэкенда
        if backend == "anthropic":
            event_stream = stream_hermes_events(
                messages=messages,
                cancel_event=cancel_event,
                hermes_messages_url=hermes_messages_url,
                hermes_key=hermes_key,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
        else:
            event_stream = _stream_openai_events(
                messages=messages,
                cancel_event=cancel_event,
                hermes_chat_url=hermes_chat_url or hermes_messages_url.replace(
                    "/v1/messages", "/v1/chat/completions"
                ),
                hermes_key=hermes_key,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )

        async for event in event_stream:
            # Автоопределение бэкенда: 404 → пробуем OpenAI
            if event["type"] == "error" and not backend_probed and hermes_chat_url:
                err_msg = event.get("message", "")
                # Только для 404 пробуем переключиться
                if "404" in err_msg:
                    backend = "openai"
                    backend_probed = True
                    # Очищаем аккумуляторы раунда и пробуем заново
                    assistant_content_blocks.clear()
                    current_thinking = ""
                    openai_reasoning = ""
                    tool_use_blocks.clear()
                    openai_fallback_url = hermes_chat_url or hermes_messages_url.replace(
                        "/v1/messages", "/v1/chat/completions"
                    )
                    async for retry_event in _stream_openai_events(
                        messages=messages,
                        cancel_event=cancel_event,
                        hermes_chat_url=openai_fallback_url,
                        hermes_key=hermes_key,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        tools=tools,
                    ):
                        if retry_event["type"] == "done":
                            final_stop_reason = retry_event.get("stop_reason", "end_turn")
                            final_usage = retry_event.get("usage", {})
                            rc = retry_event.get("reasoning_content", "")
                            if rc:
                                openai_reasoning = rc
                            for k in ("input_tokens", "output_tokens",
                                       "cache_read_input_tokens", "cache_creation_input_tokens"):
                                v = final_usage.get(k, 0)
                                if v:
                                    accumulated_usage[k] = accumulated_usage.get(k, 0) + v
                            rounds_usage.append({
                                "input_tokens": final_usage.get("input_tokens", 0),
                                "output_tokens": final_usage.get("output_tokens", 0),
                                "cache_read": final_usage.get("cache_read_input_tokens", 0),
                            })
                            # Hermes SDK: usage_update — живой счётчик токенов + кеша
                            yield {
                                "type": "usage_update",
                                "input_tokens": accumulated_usage.get("input_tokens", 0),
                                "output_tokens": accumulated_usage.get("output_tokens", 0),
                                "cache_read": accumulated_usage.get("cache_read_input_tokens", 0),
                                "cache_creation": accumulated_usage.get("cache_creation_input_tokens", 0),
                            }
                            continue
                        if retry_event["type"] == "error":
                            yield retry_event
                            yield {
                                "type": "done", "stop_reason": "error",
                                "usage": _build_usage_payload(accumulated_usage, rounds_usage),
                            }
                            return
                        yield retry_event
                        if retry_event["type"] == "thinking_token":
                            current_thinking += retry_event.get("token", "")
                            openai_reasoning += retry_event.get("token", "")
                        elif retry_event["type"] == "text_token":
                            # Capture text_token for reasoning echo-back in multi-turn
                            openai_reasoning += retry_event.get("token", "")
                        elif retry_event["type"] == "thinking_end":
                            if current_thinking:
                                assistant_content_blocks.append({
                                    "type": "thinking",
                                    "thinking": current_thinking,
                                    "signature": "",
                                })
                                current_thinking = ""
                        elif retry_event["type"] == "tool_end":
                            tool_use_blocks.append({
                                "type": "tool_use",
                                "id": f"toolu_{round_idx:02d}_{len(tool_use_blocks):02d}",
                                "name": retry_event.get("name", "unknown"),
                                "input": retry_event.get("input", {}),
                            })
                    backend_probed = True
                    # Продолжаем обработку после retry (переход к tool execution)
                    break
                else:
                    # Не 404 — отдаём ошибку как есть
                    yield event
                    yield {
                        "type": "done", "stop_reason": "error",
                        "usage": _build_usage_payload(accumulated_usage, rounds_usage),
                    }
                    return

            # Не пробрасываем done из внутреннего генератора —
            # agentic_stream сам решает когда и какой done отправить
            if event["type"] == "done":
                final_stop_reason = event.get("stop_reason", "end_turn")
                final_usage = event.get("usage", {})
                # Extract reasoning_content for DeepSeek echo-back in multi-turn
                rc = event.get("reasoning_content", "")
                if rc:
                    openai_reasoning = rc
                # Аккумулируем usage по всем раундам
                for k in (
                    "input_tokens", "output_tokens",
                    "cache_read_input_tokens", "cache_creation_input_tokens",
                ):
                    v = final_usage.get(k, 0)
                    if v:
                        accumulated_usage[k] = accumulated_usage.get(k, 0) + v
                rounds_usage.append({
                    "input_tokens": final_usage.get("input_tokens", 0),
                    "output_tokens": final_usage.get("output_tokens", 0),
                    "cache_read": final_usage.get("cache_read_input_tokens", 0),
                })
                # Hermes SDK: usage_update — живой счётчик токенов + кеша
                yield {
                    "type": "usage_update",
                    "input_tokens": accumulated_usage.get("input_tokens", 0),
                    "output_tokens": accumulated_usage.get("output_tokens", 0),
                    "cache_read": accumulated_usage.get("cache_read_input_tokens", 0),
                    "cache_creation": accumulated_usage.get("cache_creation_input_tokens", 0),
                }
                continue

            if event["type"] == "error":
                # Отдаём ошибку и завершаем с накопленным usage
                yield event
                yield {
                    "type": "done",
                    "stop_reason": "error",
                    "usage": _build_usage_payload(accumulated_usage, rounds_usage),
                }
                return

            yield event

            if event["type"] == "thinking_token":
                current_thinking += event.get("token", "")
                openai_reasoning += event.get("token", "")

            elif event["type"] == "thinking_end":
                if current_thinking:
                    assistant_content_blocks.append({
                        "type": "thinking",
                        "thinking": current_thinking,
                        "signature": thinking_signature,
                    })
                    current_thinking = ""

            elif event["type"] == "tool_end":
                name = event.get("name", "unknown")
                parsed_input = event.get("input", {})
                tool_use_blocks.append({
                    "type": "tool_use",
                    "id": f"toolu_{round_idx:02d}_{len(tool_use_blocks):02d}",
                    "name": name,
                    "input": parsed_input,
                })

        # Собираем текстовые блоки (если были text_token, нужно их учесть)
        # Текст не может быть восстановлен из отдельных токенов здесь,
        # но модель обычно не смешивает text и tool_use в одном ответе.
        # Если stop_reason = tool_use, текст в assistant_content_blocks не нужен.

        # Добавляем assistant-сообщение (формат зависит от бэкенда)
        if backend == "openai":
            assistant_msg: dict = {"role": "assistant"}
            # DeepSeek требует reasoning_content обратно в следующем запросе
            if openai_reasoning:
                assistant_msg["reasoning_content"] = openai_reasoning
                openai_reasoning = ""
            if tool_use_blocks:
                assistant_msg["content"] = None
                assistant_msg["tool_calls"] = [
                    {
                        "id": tb["id"],
                        "type": "function",
                        "function": {
                            "name": tb["name"],
                            "arguments": json.dumps(tb["input"], ensure_ascii=False),
                        },
                    }
                    for tb in tool_use_blocks
                ]
            else:
                assistant_msg["content"] = ""
            messages.append(assistant_msg)
        elif assistant_content_blocks or tool_use_blocks:
            # Anthropic-формат: контент-блоки с thinking и tool_use
            assistant_content_blocks.extend(tool_use_blocks)
            messages.append({
                "role": "assistant",
                "content": assistant_content_blocks,
            })

        # ── Hermes SDK: message.completed — закрываем границу сообщения ──
        yield {"type": "message.completed", "message": {"id": _current_message_id, "stop_reason": final_stop_reason}}

        # Если нет tool_use — финальный ответ, завершаем
        if final_stop_reason != "tool_use" or not tool_use_blocks:
            # Drain remaining side events before final done
            if side_event_queue is not None:
                while not side_event_queue.empty():
                    try:
                        yield side_event_queue.get_nowait()
                        side_event_queue.task_done()
                    except asyncio.QueueEmpty:
                        break
            yield {
                "type": "done",
                "stop_reason": final_stop_reason,
                "usage": _build_usage_payload(accumulated_usage, rounds_usage),
            }
            return

        # Сигнал фронтенду: инструменты будут выполнены
        yield {
            "type": "done",
            "stop_reason": "tool_use",
            "usage": final_usage,
        }

        # Выполняем инструменты (с подтверждением для опасных)
        tool_results: list[dict] = []
        auto_approve = False  # Сбрасывается каждый раунд
        session_approvals = (
            approval_registry.setdefault(session_id, {})
            if approval_registry and session_id
            else {}
        )

        for tb in tool_use_blocks:
            tool_id = tb["id"]
            tool_name = tb["name"]
            tool_input = tb["input"]

            if tool_name in DANGEROUS_TOOLS and not auto_approve:
                # Запрашиваем подтверждение у пользователя
                yield {
                    "type": "tool_confirm",
                    "tool_use_id": tool_id,
                    "name": tool_name,
                    "label": _tool_label(tool_name),
                    "input": tool_input,
                }
                # Hermes SDK: approval.request — формальный запрос подтверждения
                yield {
                    "type": "approval.request",
                    "toolUseId": tool_id,
                    "toolName": tool_name,
                    "input": tool_input,
                    "message": f"Инструмент {_tool_label(tool_name)} требует подтверждения",
                }

                if session_approvals is not None:
                    event = asyncio.Event()
                    session_approvals[tool_id] = event
                    approval_task = asyncio.create_task(event.wait())
                    cancel_task = asyncio.create_task(cancel_event.wait())
                    done, _ = await asyncio.wait(
                        [approval_task, cancel_task],
                        timeout=120,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancel_event.is_set():
                        session_approvals.pop(tool_id, None)
                        yield {
                            "type": "done",
                            "stop_reason": "cancelled",
                            "usage": _build_usage_payload(accumulated_usage, rounds_usage),
                        }
                        return
                    if not done:
                        # Таймаут — авто-отказ
                        session_approvals.pop(tool_id, None)
                        decision = "deny"
                    else:
                        decision = getattr(event, "decision", "deny")
                    session_approvals.pop(tool_id, None)
                else:
                    # Нет approval_registry — auto-deny в режиме без подтверждения
                    decision = "deny"

                if decision == "deny":
                    result_str = json.dumps(
                        {"error": "Выполнение отклонено пользователем"},
                        ensure_ascii=False,
                    )
                    tool_results.append({
                        "tool_use_id": tool_id,
                        "name": tool_name,
                        "result": result_str,
                    })
                    yield {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "name": tool_name,
                        "label": _tool_label(tool_name),
                        "result": result_str,
                        "duration_ms": 0,
                        "error": "Выполнение отклонено пользователем",
                    }
                    yield {
                        "type": "tool.failed",
                        "toolUseId": tool_id,
                        "toolName": tool_name,
                        "output": result_str,
                        "durationMs": 0,
                        "error": "Выполнение отклонено пользователем",
                    }
                    continue
                elif decision == "allow_all":
                    auto_approve = True

            # Выполняем инструмент
            yield {
                "type": "tool_executing",
                "tool_use_id": tool_id,
                "name": tool_name,
                "label": _tool_label(tool_name),
            }
            # Hermes SDK: tool.started
            yield {
                "type": "tool.started",
                "toolUseId": tool_id,
                "toolName": tool_name,
                "input": tool_input,
            }

            # Subagent events for agent tools + kanban auto-tracking
            is_agent = tool_name == "agent"
            if is_agent:
                task_desc = tool_input.get("task", "")
                # Auto-create kanban card in "subagent" column (before subagent_start so frontend can update it)
                yield {
                    "type": "kanban_task_created",
                    "task_id": tool_id,
                    "column": "subagent",
                    "title": task_desc[:80] if task_desc else "Субагент",
                    "description": tool_input.get("cwd", ""),
                }
                yield {
                    "type": "subagent_start",
                    "tool_use_id": tool_id,
                    "task": task_desc,
                    "cwd": tool_input.get("cwd", ""),
                }

            # PreToolUse hook — блокирующая валидация (2s, fail-open)
            try:
                from hooks import invoke_pre_tool_use, fire_post_tool_use as _fire_ptu  # type: ignore[import-untyped]
                hook_result = await invoke_pre_tool_use(tool_name=tool_name, args=dict(tool_input), session_id=session_id)
                if hook_result is not None and hook_result.action == "block":
                    result_str = json.dumps(
                        {"error": f"Инструмент заблокирован: {hook_result.message}"},
                        ensure_ascii=False,
                    )
                    duration_ms = 0
                else:
                    if hook_result is not None and hook_result.modified_args:
                        tool_input = hook_result.modified_args
                    t_start = time.monotonic()
                    result_str = await dispatch(tool_name, tool_input, extra_handlers=extra_tool_handlers, user_id=user_id)
                    duration_ms = int((time.monotonic() - t_start) * 1000)
                    _fire_ptu(tool_name=tool_name, args=tool_input, result=result_str, duration_ms=duration_ms, session_id=session_id)
            except ImportError:
                t_start = time.monotonic()
                result_str = await dispatch(tool_name, tool_input, extra_handlers=extra_tool_handlers, user_id=user_id)
                duration_ms = int((time.monotonic() - t_start) * 1000)

            # Prompt Guard — scan tool results for injection
            if result_str and len(result_str) > 50:
                try:
                    from web.prompt_guard import scan_tool_result as _scan_tr
                    if not _scan_tr(tool_name, result_str):
                        result_str = json.dumps({
                            "error": "Tool result blocked by Prompt Guard: содержит признаки prompt injection",
                            "tool": tool_name,
                        }, ensure_ascii=False)
                except ImportError:
                    pass

            if is_agent:
                error = _extract_tool_error(result_str)
                status = "error" if error else "completed"
                # Parse result for diff stats if available
                result_data = {}
                try:
                    result_data = json.loads(result_str)
                except (json.JSONDecodeError, TypeError):
                    pass
                yield {
                    "type": "subagent_end",
                    "tool_use_id": tool_id,
                    "task": tool_input.get("task", ""),
                    "result": result_str,
                    "duration_ms": duration_ms,
                    "error": error,
                }
                # Auto-update kanban card
                yield {
                    "type": "kanban_task_updated",
                    "task_id": tool_id,
                    "status": status,
                    "result": result_data.get("output", "")[:200] if isinstance(result_data, dict) else "",
                    "diff_added": result_data.get("diff_added", 0) if isinstance(result_data, dict) else 0,
                    "diff_removed": result_data.get("diff_removed", 0) if isinstance(result_data, dict) else 0,
                }

            # Kanban events for kanban tools + ACP plan snapshot
            kanban_event = _extract_kanban_event(tool_name, result_str)
            if kanban_event:
                yield kanban_event
                yield _build_plan_event()

            # Определяем ошибку по JSON-результату
            error = _extract_tool_error(result_str)

            tool_results.append({
                "tool_use_id": tool_id,
                "name": tool_name,
                "result": result_str,
            })

            yield {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "name": tool_name,
                "label": _tool_label(tool_name),
                "result": result_str,
                "path": _extract_tool_path(tool_name, tool_input),
                "duration_ms": duration_ms,
                "error": error,
            }
            # Hermes SDK: tool.completed / tool.failed
            yield {
                "type": "tool.failed" if error else "tool.completed",
                "toolUseId": tool_id,
                "toolName": tool_name,
                "output": result_str,
                "durationMs": duration_ms,
                "error": error,
            }

            # Drain side events produced by the tool (e.g. primary model streaming)
            if side_event_queue is not None:
                while not side_event_queue.empty():
                    try:
                        yield side_event_queue.get_nowait()
                        side_event_queue.task_done()
                    except asyncio.QueueEmpty:
                        break

        # Добавляем tool_result в историю
        if tool_results:
            if backend == "openai":
                for tr in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": tr["result"],
                    })
            else:
                result_blocks: list[dict] = []
                for tr in tool_results:
                    result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tr["tool_use_id"],
                        "content": tr["result"],
                    })
                messages.append({"role": "user", "content": result_blocks})

    # Исчерпали max_rounds
    if side_event_queue is not None:
        while not side_event_queue.empty():
            try:
                yield side_event_queue.get_nowait()
                side_event_queue.task_done()
            except asyncio.QueueEmpty:
                break
    yield {
        "type": "done",
        "stop_reason": "max_rounds",
        "usage": _build_usage_payload(accumulated_usage, rounds_usage),
    }
