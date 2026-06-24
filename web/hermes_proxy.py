"""Локальный Web Agent — aiohttp SSE-прокси до смарт-роутера :8084.

Смарт-роутер сам решает, отправить запрос в Hermes (DeepSeek) или aiproxy (GPT),
на основе поля model (из get_active_model()).
"""

from __future__ import annotations

import asyncio
import json

import aiohttp

from services.shared.model_router import get_active_model


async def stream_hermes_tokens(
    messages: list[dict],
    *,
    cancel_event: asyncio.Event,
    hermes_url: str,
    hermes_key: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
):
    """Генератор: выдаёт отдельные content-токены из SSE-потока смарт-роутера."""
    async with aiohttp.ClientSession() as session:
        model = get_active_model()
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        # Hermes (deepseek) поддерживает max_completion_tokens,
        # внешние API через aiproxy — не передаём параметр токенов,
        # пусть сам decides (aiproxy конвертирует и ломает совместимость)
        if "deepseek" in model.lower():
            body["max_completion_tokens"] = max_tokens
        try:
            async with session.post(
                hermes_url,
                json=body,
                headers={
                    "Authorization": f"Bearer {hermes_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    yield f"[Роутер вернул {resp.status}: {text[:200]}]"
                    return

                async for line in resp.content:
                    if cancel_event.is_set():
                        break
                    try:
                        line_str = line.decode("utf-8", errors="replace").strip()
                    except Exception:
                        continue
                    if not line_str or not line_str.startswith("data:"):
                        continue
                    data_str = line_str[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except aiohttp.ClientError as exc:
            yield f"[Ошибка соединения с роутером: {exc}]"
        except TimeoutError:
            yield "[Таймаут — роутер не ответил за 300с]"
