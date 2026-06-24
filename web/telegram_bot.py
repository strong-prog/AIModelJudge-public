"""AIModelJudge — Telegram-бот (aiogram + httpx SSE-клиент).

Подключается к локальному /chat SSE-стриму, пересылает ответы в Telegram,
обрабатывает approve/dangerous-инструменты через inline-кнопки.

Конфиг:
  AMJ_TELEGRAM_TOKEN          — токен бота (обязательно)
  AMJ_TELEGRAM_ALLOWED_USERS  — список user_id через запятую (пусто = все)
  AMJ_WEB_PORT                — порт локального веб-сервера (по умолчанию 9651)

Команды:
  /start, /help, /status, /model, /judge, /cancel, /history, /session

Gateway-контекст:
  - client_session_id (tg_{chat_id}) — непрерывность сессии через POST body
  - X-Stream-Session (stream_session_id) — cancel/approve операции
  - /history, /session — просмотр сессий из общей state.db (web + Telegram)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

logger = logging.getLogger("aimodeljudge.tg")

# ── Конфигурация ──────────────────────────────────────────────────────────

TOKEN = os.getenv("AMJ_TELEGRAM_TOKEN", "")
ALLOWED_USERS: set[int] = set()
_raw = os.getenv("AMJ_TELEGRAM_ALLOWED_USERS", "")
if _raw.strip():
    for uid in _raw.split(","):
        try:
            ALLOWED_USERS.add(int(uid.strip()))
        except ValueError:
            pass

WEB_PORT = int(os.getenv("AMJ_WEB_PORT", "9651"))
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"
_CHAT_ENDPOINT = f"{WEB_URL}/chat"

# Scoped API key for Telegram bot (readonly recommended)
_BOT_API_KEY = os.getenv("AMJ_TELEGRAM_API_KEY", "")

# ── Модели ──────────────────────────────────────────────────────────────
DEFAULT_MODELS: list[str] = ["deepseek-chat"]

# ── Состояние бота ────────────────────────────────────────────────────────

# chat_id → client_session_id (persistent, для continuity через POST body)
_chat_sessions: dict[int, str] = {}
# chat_id → stream_session_id (из X-Stream-Session заголовка ответа, для cancel/approve)
_active_stream_ids: dict[int, str] = {}
# chat_id → {tool_use_id: str, decision: str, event: asyncio.Event}
_pending_approvals: dict[int, dict] = {}
# chat_id → текущий статус (message_id, текст фазы) для индикатора
_chat_status_msgs: dict[int, tuple[int, str]] = {}

# Путь к общей БД сессий (с AMJ_ENV-изоляцией)
_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"
_STATE_DB = _BASE / "state.db"

PHASE_EMOJI = {
    "analyze": "🔍",
    "consult": "💬",
    "synthesize": "🧩",
    "apply": "✅",
    "plan": "📋",
}


def _check_access(chat_id: int) -> bool:
    """Проверяет, разрешён ли доступ этому пользователю."""
    if not ALLOWED_USERS:
        return True
    return chat_id in ALLOWED_USERS


def _lookup_user_by_api_key(api_key: str) -> dict | None:
    """Находит пользователя по API-ключу в state.db."""
    if not _STATE_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(_STATE_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, email, tier, api_key FROM users WHERE api_key = ?",
            (api_key.strip(),),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _get_linked_user(chat_id: int) -> dict | None:
    """Возвращает пользователя, привязанного к этому чату."""
    if not _STATE_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(_STATE_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT u.id, u.email, u.tier, u.api_key
               FROM telegram_links tl
               JOIN users u ON tl.user_id = u.id
               WHERE tl.chat_id = ?""",
            (chat_id,),
        ).fetchone()
        if not row:
            conn.close()
            return None
        user = dict(row)
        # Проверить активную подписку
        sub = conn.execute(
            "SELECT tier, status FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        conn.close()
        if sub:
            user["effective_tier"] = sub["tier"]
            user["subscription_active"] = True
        else:
            user["effective_tier"] = "free"
            user["subscription_active"] = False
        return user
    except Exception:
        return None


def _link_chat_to_user(chat_id: int, user_id: str) -> bool:
    """Привязывает Telegram chat к пользователю."""
    try:
        conn = sqlite3.connect(str(_STATE_DB))
        conn.execute(
            "INSERT OR REPLACE INTO telegram_links (chat_id, user_id, linked_at) VALUES (?, ?, datetime('now'))",
            (chat_id, user_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── Хелперы ───────────────────────────────────────────────────────────────

def _escape_tg(text: str) -> str:
    """Экранирует спецсимволы Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


def _truncate(text: str, max_len: int = 3800) -> str:
    """Обрезает текст до лимита Telegram (4096 с запасом)."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 30] + "\n\n... (сообщение обрезано)"


def _format_tool_input(tool_input: dict) -> str:
    """Форматирует входные данные инструмента для отображения."""
    s = json.dumps(tool_input, indent=2, ensure_ascii=False)
    return _truncate(s, 800)


# ── Обработчики команд ─────────────────────────────────────────────────────

dp = Dispatcher()
bot: Optional[Bot] = None


def _get_bot() -> Bot:
    """Ленивое создание бота (токен валидируется при первом обращении)."""
    global bot
    if bot is None:
        if not TOKEN:
            raise RuntimeError("AMJ_TELEGRAM_TOKEN не задан")
        bot = Bot(token=TOKEN)
    return bot


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not _check_access(message.chat.id):
        return
    await message.answer(
        "🤖 *AIModelJudge — Совет экспертов*\n\n"
        "Я подключаю Central Judge (deepseek\\-v4\\-pro) с командой "
        "экспертов для решения ваших задач\\.\n\n"
        "Просто отправьте вопрос — я передам его архитектору "
        "и верну ответ с результатами анализа\\.\n\n"
        "*Команды:*\n"
        "/start — это сообщение\n"
        "/judge <вопрос> — задать вопрос архитектору\n"
        "/status — текущая модель и сессия\n"
        "/cancel — отменить текущий запрос\n"
        "/model — сменить модель\n"
        "/history — последние сессии\n"
        "/session <id> — просмотр сессии\n"
        "/help — помощь",
        parse_mode="MarkdownV2",
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if not _check_access(message.chat.id):
        return
    await message.answer(
        "*Справка AIModelJudge*\n\n"
        "🔍 *Фаза 1 — Анализ:* архитектор изучает код через CodeGraph\\, memory\\, grep\n"
        "💬 *Фаза 2 — Консультация:* enriched query → side\\-модели\n"
        "🧩 *Фаза 3 — Синтез:* консенсус\\, противоречия\\, идеальное решение\n"
        "✅ *Фаза 4 — Применение:* правки кода\\, тесты\\, финальный ответ\n\n"
        "Для опасных инструментов (bash\\, edit\\_file) бот запросит "
        "подтверждение через кнопки\\.",
        parse_mode="MarkdownV2",
    )


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if not _check_access(message.chat.id):
        return
    session_id = _chat_sessions.get(message.chat.id, "нет активной сессии")
    await message.answer(
        f"📊 *Статус*\n"
        f"• Сессия: `{_escape_tg(session_id)}`\n"
        f"• Модель: DeepSeek V4 Pro \\(Central Judge\\)\n"
        f"• Эксперты: DeepSeek Chat \\+ GPT\\-5\\.4",
        parse_mode="MarkdownV2",
    )


@dp.message(Command("model"))
async def cmd_model(message: types.Message):
    if not _check_access(message.chat.id):
        return
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{WEB_URL}/model/list")
            models = r.json()
        lines = ["*Доступные модели:*"]
        for m in models[:10]:
            name = m.get("label", m.get("key", "?"))
            lines.append(f"• `{_escape_tg(str(name))}`")
        await message.answer("\n".join(lines), parse_mode="MarkdownV2")
    except Exception as exc:
        await message.answer(f"Ошибка: {exc}")


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    """Отменяет активный стрим (через POST /cancel)."""
    if not _check_access(message.chat.id):
        return
    chat_id = message.chat.id
    stream_sid = _active_stream_ids.get(chat_id, "")
    if not stream_sid:
        await message.answer("Нет активного запроса для отмены.")
        return
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{WEB_URL}/cancel",
                headers={
                    "X-Stream-Session": stream_sid,
                    **({"X-AMJ-API-Key": _BOT_API_KEY} if _BOT_API_KEY else {}),
                },
            )
        if r.status_code == 200:
            _active_stream_ids.pop(chat_id, None)
            await message.answer("✅ Запрос отменён.")
        else:
            await message.answer(f"Ошибка отмены: HTTP {r.status_code}")
    except Exception as exc:
        await message.answer(f"Ошибка: {exc}")


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    """Показывает последние сессии (web + Telegram)."""
    if not _check_access(message.chat.id):
        return
    if not _STATE_DB.exists():
        await message.answer("Нет сохранённых сессий.")
        return
    try:
        conn = sqlite3.connect(str(_STATE_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, source, model, started_at, message_count, title "
            "FROM sessions ORDER BY started_at DESC LIMIT 10"
        ).fetchall()
        conn.close()

        if not rows:
            await message.answer("Нет сохранённых сессий.")
            return

        lines = ["*Последние сессии:*"]
        for r in rows:
            sid = r["id"]
            short_id = sid[:20] + ("…" if len(sid) > 20 else "")
            model = r["model"] or "?"
            msgs = r["message_count"] or 0
            source_icon = "🌐" if r["source"] == "web" else "📱" if r["source"] == "telegram" else "🖥"
            title = r["title"] or ""
            escaped_title = _escape_tg(title[:60]) if title else ""
            lines.append(
                f"{source_icon} `{_escape_tg(short_id)}` — {_escape_tg(model)} "
                f"\\({msgs} msg\\) {escaped_title}"
            )
        lines.append("\n*/session <id>* — посмотреть сессию")
        await message.answer("\n".join(lines), parse_mode="MarkdownV2")
    except Exception as exc:
        await message.answer(f"Ошибка загрузки истории: {exc}")


@dp.message(Command("session"))
async def cmd_session(message: types.Message):
    """Просмотр конкретной сессии по ID."""
    if not _check_access(message.chat.id):
        return
    text = message.text or ""
    session_id = text.replace("/session", "").strip()
    if not session_id:
        await message.answer("Укажите ID сессии: `/session api\\-xxx`", parse_mode="MarkdownV2")
        return

    if not _STATE_DB.exists():
        await message.answer("База сессий недоступна.")
        return

    try:
        conn = sqlite3.connect(str(_STATE_DB))
        conn.row_factory = sqlite3.Row
        session = conn.execute(
            "SELECT id, source, model, started_at, message_count, title "
            "FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not session:
            conn.close()
            await message.answer("Сессия не найдена.")
            return
        msgs = conn.execute(
            "SELECT role, content, timestamp FROM messages "
            "WHERE session_id = ? AND active = 1 ORDER BY timestamp LIMIT 20",
            (session_id,),
        ).fetchall()
        conn.close()

        s = dict(session)
        lines = [
            f"*Сессия:* `{_escape_tg(s['id'])}`",
            f"• Модель: {_escape_tg(s['model'] or '?')}",
            f"• Сообщений: {s['message_count']}",
            f"• Источник: {s['source']}",
            "",
            "*Сообщения:*",
        ]
        for m in msgs:
            role = "👤" if m["role"] == "user" else "🤖"
            content = _truncate(m["content"] or "", 300)
            lines.append(f"{role} {_escape_tg(content)}")

        text_out = "\n".join(lines)
        if len(text_out) > 3800:
            for i in range(0, len(text_out), 3800):
                await message.answer(text_out[i:i+3800], parse_mode="MarkdownV2")
        else:
            await message.answer(text_out, parse_mode="MarkdownV2")

        # Предложить продолжить сессию
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🔄 Продолжить эту сессию",
                callback_data=f"session_continue:{session_id}",
            )
        ]])
        await message.answer(
            "Использовать эту сессию для продолжения?",
            reply_markup=kb,
        )
    except Exception as exc:
        await message.answer(f"Ошибка: {exc}")


@dp.callback_query(F.data.startswith("session_continue:"))
async def handle_session_continue(callback: CallbackQuery):
    """Переключить текущую сессию на выбранную."""
    chat_id = callback.message.chat.id if callback.message else 0
    session_id = callback.data.split(":", 1)[1] if callback.data else ""
    if session_id:
        _chat_sessions[chat_id] = session_id
        await callback.answer(f"Сессия переключена")
        await callback.message.edit_text(
            f"✅ Сессия переключена на `{_escape_tg(session_id)}`",
            parse_mode="MarkdownV2",
        )
    else:
        await callback.answer("Ошибка")


@dp.message(Command("link"))
async def cmd_link(message: types.Message):
    """Привязать Telegram к аккаунту AIModelJudge: /link <api_key>"""
    if not _check_access(message.chat.id):
        return
    text = message.text or ""
    api_key = text.replace("/link", "").strip()
    if not api_key:
        await message.answer(
            "Привяжите ваш аккаунт для доступа к моделям:\n"
            "`/link ваш\\_API\\_ключ`\n\n"
            "API\\-ключ можно найти в веб\\-интерфейсе:\n"
            "Настройки → Аккаунт → API\\-ключ",
            parse_mode="MarkdownV2",
        )
        return

    user = _lookup_user_by_api_key(api_key)
    if not user:
        await message.answer("❌ Неверный API\\-ключ\\. Проверьте ключ в веб\\-интерфейсе\\.", parse_mode="MarkdownV2")
        return

    if _link_chat_to_user(message.chat.id, user["id"]):
        await message.answer(
            f"✅ Аккаунт привязан!\n"
            f"• Email: `{_escape_tg(user['email'])}`\n\n"
            f"Используйте /account для просмотра статуса.",
            parse_mode="MarkdownV2",
        )
    else:
        await message.answer("❌ Ошибка привязки\\. Попробуйте позже\\.", parse_mode="MarkdownV2")


@dp.message(Command("account"))
async def cmd_account(message: types.Message):
    """Показать статус аккаунта и лимиты."""
    if not _check_access(message.chat.id):
        return
    chat_id = message.chat.id

    linked = _get_linked_user(chat_id)

    lines = ["*Аккаунт AIModelJudge*"]
    if linked:
        lines.append(f"• Email: `{_escape_tg(linked['email'])}`")
    else:
        lines.append("• Статус: *не привязан*")
    lines.append("\n*/link <api\\_key>* — привязать аккаунт")

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")


@dp.message(Command("judge"))
async def cmd_judge(message: types.Message):
    """Отправить запрос архитектору (убирает /judge из текста)."""
    if not _check_access(message.chat.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    text = message.text or ""
    text = re.sub(r"^/judge\s*", "", text).strip()
    if not text:
        await message.answer("Укажите вопрос после /judge")
        return

    await _process_judge_request(message.chat.id, text, DEFAULT_MODELS)


@dp.message(F.text, ~F.text.startswith("/"))
async def handle_text(message: types.Message):
    """Все текстовые сообщения (не команды) отправляются архитектору."""
    if not _check_access(message.chat.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    if not message.text or not message.text.strip():
        return
    await _process_judge_request(message.chat.id, message.text.strip(), DEFAULT_MODELS)


@dp.callback_query(F.data.startswith("approve:"))
async def handle_approve(callback: CallbackQuery):
    """Обработчик inline-кнопок approve/deny/allow_all."""
    chat_id = callback.message.chat.id if callback.message else 0
    parts = callback.data.split(":", 2) if callback.data else []
    decision = parts[1] if len(parts) > 1 else "deny"
    tool_use_id = parts[2] if len(parts) > 2 else ""

    pending = _pending_approvals.get(chat_id)
    if pending and pending.get("tool_use_id") == tool_use_id:
        pending["decision"] = decision
        pending["event"].set()

    await callback.answer(f"Решение: {decision}")
    # Убираем кнопки из сообщения
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


# ── Основной поток обработки запроса ──────────────────────────────────────

async def _process_judge_request(chat_id: int, user_text: str, models: list[str] | None = None):
    """Отправляет запрос в /chat, стримит ответ в Telegram."""
    if models is None:
        models = DEFAULT_MODELS

    client_session_id = _chat_sessions.get(chat_id)
    if not client_session_id:
        client_session_id = f"tg_{chat_id}"
        _chat_sessions[chat_id] = client_session_id

    # Сообщение-индикатор фазы
    status_msg = await _get_bot().send_message(
        chat_id, f"🔍 *Фаза 1: Анализ*\\.\\.\\.", parse_mode="MarkdownV2"
    )

    response_msg_id: Optional[int] = None
    response_text = ""
    buffer = ""
    current_phase = "analyze"
    error_text: Optional[str] = None
    tool_results: list[str] = []
    stream_session_id: Optional[str] = None  # Из X-Stream-Session заголовка ответа

    async def _update_status(phase: str):
        nonlocal current_phase
        current_phase = phase
        emoji = PHASE_EMOJI.get(phase, "")
        phase_names = {
            "analyze": "Анализ",
            "consult": "Консультация",
            "synthesize": "Синтез",
            "apply": "Применение",
            "plan": "План",
        }
        name = phase_names.get(phase, phase)
        try:
            await status_msg.edit_text(
                f"{emoji} *Фаза: {name}*\\.\\.\\.", parse_mode="MarkdownV2"
            )
        except Exception:
            pass

    async def _flush_buffer():
        nonlocal response_text, buffer, response_msg_id
        if not buffer.strip():
            return
        chunk = buffer.strip()
        response_text += chunk + "\n"
        buffer = ""

        if response_msg_id is None:
            sent = await _get_bot().send_message(
                chat_id, _truncate(chunk), parse_mode="MarkdownV2"
            )
            response_msg_id = sent.message_id
        else:
            full = _truncate(response_text)
            if full != response_text:
                full += "\n\n\\.\\.\\. \\(обрезано\\)"
            try:
                await _get_bot().edit_message_text(
                    full, chat_id=chat_id, message_id=response_msg_id,
                    parse_mode="MarkdownV2",
                )
            except Exception:
                pass

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                _CHAT_ENDPOINT,
                json={
                    "message": user_text,
                    "primary_models": models,
                    "session_id": client_session_id,
                    "source": "telegram",
                },
                headers={
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                    **({"X-AMJ-API-Key": _BOT_API_KEY} if _BOT_API_KEY else {}),
                },
            ) as response:
                if response.status_code != 200:
                    error_text = f"Ошибка сервера: HTTP {response.status_code}"
                    await status_msg.edit_text(f"❌ {error_text}")
                    return

                # Сохраняем X-Stream-Session для cancel/approve
                stream_session_id = response.headers.get("X-Stream-Session", "")
                if stream_session_id:
                    _active_stream_ids[chat_id] = stream_session_id

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type", "")

                    # ── Фазовые переходы ──
                    if etype == "phase":
                        await _update_status(event.get("phase", current_phase))

                    # ── Текст центральной модели ──
                    elif etype == "text_token":
                        token = event.get("token", "")
                        buffer += token
                        if len(buffer) >= 800 or "\n\n" in buffer:
                            await _flush_buffer()

                    # ── Thinking токены (не показываем в TG, только фазу) ──
                    elif etype == "thinking_token":
                        pass

                    # ── Инструменты ──
                    elif etype == "tool_start":
                        tname = event.get("name", "?")
                        tool_results.append(f"🔧 `{_escape_tg(tname)}` запущен\\.\\.\\.")
                        if response_msg_id is None:
                            sent = await _get_bot().send_message(
                                chat_id, tool_results[-1], parse_mode="MarkdownV2"
                            )
                            response_msg_id = sent.message_id
                        else:
                            await _get_bot().send_message(
                                chat_id, tool_results[-1], parse_mode="MarkdownV2"
                            )

                    elif etype == "tool_end":
                        tname = event.get("name", "?")
                        tinput = event.get("input", {})
                        tresult = event.get("result", "")
                        info = (
                            f"🔧 `{_escape_tg(tname)}` выполнен\n"
                            f"Вход: `{_escape_tg(_format_tool_input(tinput))}`\n"
                        )
                        if tresult:
                            short = _truncate(str(tresult), 500)
                            info += f"Результат: `{_escape_tg(short)}`"
                        await _get_bot().send_message(chat_id, info, parse_mode="MarkdownV2")

                    # ── Подтверждение опасных инструментов ──
                    elif etype == "tool_confirm":
                        tool_use_id = event.get("tool_use_id", "")
                        tool_name = event.get("tool_name", "")
                        tool_input = event.get("tool_input", {})

                        ev = asyncio.Event()
                        _pending_approvals[chat_id] = {
                            "tool_use_id": tool_use_id,
                            "decision": "deny",
                            "event": ev,
                        }

                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text="✅ Одобрить",
                                        callback_data=f"approve:allow:{tool_use_id}",
                                    ),
                                    InlineKeyboardButton(
                                        text="❌ Отклонить",
                                        callback_data=f"approve:deny:{tool_use_id}",
                                    ),
                                ],
                                [
                                    InlineKeyboardButton(
                                        text="🔓 Всегда разрешать",
                                        callback_data=f"approve:allow_all:{tool_use_id}",
                                    ),
                                ],
                            ]
                        )

                        warning = (
                            f"⚠️ *Опасный инструмент:* `{_escape_tg(tool_name)}`\n\n"
                            f"```json\n{_format_tool_input(tool_input)}\n```\n\n"
                            f"Требуется подтверждение\\. Нажмите кнопку ниже\\."
                        )
                        await _get_bot().send_message(
                            chat_id, warning, reply_markup=kb, parse_mode="MarkdownV2"
                        )

                        # Ждём решения пользователя (таймаут 120s)
                        try:
                            await asyncio.wait_for(ev.wait(), timeout=120.0)
                        except asyncio.TimeoutError:
                            _pending_approvals[chat_id]["decision"] = "deny"

                        decision = _pending_approvals.pop(chat_id, {}).get(
                            "decision", "deny"
                        )
                        # Отправляем решение на сервер
                        active_sid = stream_session_id or _active_stream_ids.get(chat_id, "")
                        async with httpx.AsyncClient() as c2:
                            await c2.post(
                                f"{WEB_URL}/approve",
                                json={
                                    "tool_use_id": tool_use_id,
                                    "decision": decision,
                                },
                                headers={
                                    "X-Stream-Session": active_sid,
                                    **({"X-AMJ-API-Key": _BOT_API_KEY} if _BOT_API_KEY else {}),
                                },
                            )
                        await _get_bot().send_message(
                            chat_id,
                            f"▶️ Решение: *{decision}* для `{_escape_tg(tool_name)}`",
                            parse_mode="MarkdownV2",
                        )

                    # ── Результат инструмента ──
                    elif etype == "tool_result":
                        tname = event.get("tool_use_id", "")
                        content = event.get("content", "")
                        if content:
                            short = _truncate(str(content), 500)
                            await _get_bot().send_message(
                                chat_id,
                                f"📋 Результат:\n```\n{_escape_tg(short)}\n```",
                                parse_mode="MarkdownV2",
                            )

                    # ── Синтез ──
                    elif etype == "synthesis":
                        phase = event.get("phase", "")
                        token = event.get("token", "")
                        if phase and "start" in phase:
                            phase_label = {
                                "consensus_start": "🤝 Консенсус",
                                "contradictions_start": "⚡ Противоречия",
                                "gaps_start": "🕳 Пробелы",
                                "ideal_solution_start": "💡 Идеальное решение",
                            }.get(phase, phase)
                            await _get_bot().send_message(
                                chat_id, f"*{phase_label}*", parse_mode="MarkdownV2"
                            )
                        if token:
                            buffer += token
                            if len(buffer) >= 800:
                                await _flush_buffer()

                    # ── Ошибка ──
                    elif etype == "error":
                        error_text = event.get("message", "Неизвестная ошибка")
                        await status_msg.edit_text(
                            f"❌ {_escape_tg(error_text)}", parse_mode="MarkdownV2"
                        )

                    # ── Завершение ──
                    elif etype == "done":
                        break

                    # ── Heartbeat (игнорируем) ──
                    elif etype == "streaming_heartbeat":
                        pass

        # Сбросить остатки буфера
        await _flush_buffer()

        # Финальное сообщение
        final_text = response_text or "Готово\\."
        if error_text:
            final_text = f"⚠️ {error_text}\n\n{final_text}"

        try:
            await status_msg.delete()
        except Exception:
            pass

        # Если ответ слишком длинный — отправляем частями
        if len(final_text) > 3800:
            for i in range(0, len(final_text), 3800):
                await _get_bot().send_message(
                    chat_id,
                    final_text[i : i + 3800],
                    parse_mode="MarkdownV2",
                )
        elif response_msg_id:
            try:
                await _get_bot().edit_message_text(
                    _truncate(final_text),
                    chat_id=chat_id,
                    message_id=response_msg_id,
                    parse_mode="MarkdownV2",
                )
            except Exception:
                await _get_bot().send_message(
                    chat_id, _truncate(final_text), parse_mode="MarkdownV2"
                )
        else:
            await _get_bot().send_message(
                chat_id, "✅ Завершено\\. Ответ пуст\\.", parse_mode="MarkdownV2"
            )

    except httpx.ConnectError:
        await status_msg.edit_text(
            "❌ Не могу подключиться к AIModelJudge\\. "
            "Убедитесь\\, что сервер запущен на порту 9651\\.",
            parse_mode="MarkdownV2",
        )
    except httpx.ReadTimeout:
        await status_msg.edit_text(
            "❌ Таймаут ответа \\(>5 минут\\)\\. Попробуйте упростить запрос\\.",
            parse_mode="MarkdownV2",
        )
        try:
            await _check_and_alert_budget(chat_id, "default")
        except Exception:
            pass
    except Exception as exc:
        logger.exception("Ошибка обработки запроса из Telegram")
        try:
            await status_msg.edit_text(
                f"❌ Внутренняя ошибка: {_escape_tg(str(exc)[:200])}",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass
        try:
            await _check_and_alert_budget(chat_id, "default")
        except Exception:
            pass
    else:
        # ── Budget alert after successful completion ──
        try:
            await _check_and_alert_budget(chat_id, "default")
        except Exception:
            pass


# ── Budget Alert ────────────────────────────────────────────────────────────

async def _check_and_alert_budget(chat_id: int, tier: str) -> None:
    """Budget alert — disabled for public release."""
    pass


# ── Жизненный цикл ─────────────────────────────────────────────────────────

async def start_bot():
    """Запускает поллинг Telegram-бота."""
    if not TOKEN:
        logger.warning("AMJ_TELEGRAM_TOKEN не задан — Telegram-бот отключён")
        return
    logger.info("Telegram-бот запущен (allowed_users=%d)", len(ALLOWED_USERS))
    await dp.start_polling(_get_bot())


async def stop_bot():
    """Останавливает бота."""
    if not TOKEN:
        return
    try:
        if bot is not None:
            await bot.session.close()
    except Exception:
        pass
    logger.info("Telegram-бот остановлен")
