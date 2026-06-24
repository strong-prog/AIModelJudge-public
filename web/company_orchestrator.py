"""Company Mode orchestrator — запуск специалистов, сбор ответов, синтез."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Any

from company_mode import (
    SpecialistConfig,
    load_specialist_context,
    SPECIALIST_ROLES,
    check_sandbox,
    get_memory_namespace,
)
from primary_models import (
    _stream_one_with_context,
    set_side_event_queue,
    PRIMARY_TOOL_DEFINITIONS,
)

# ── Architect system prompt for Company Mode ──

ARCHITECT_SYSTEM_PROMPT = """Ты — Архитектор (Architect) в AIModelJudge Company Mode.
Твоя задача: синтезировать ОДИН согласованный ответ из мнений нескольких специалистов компании.

ПРАВИЛА:
1. Выдели консенсус — в чём все специалисты согласны
2. Найди противоречия — где мнения расходятся, и предложи разрешение
3. Определи пробелы — что никто не покрыл
4. Приоритезируй действия: first / next / later
5. Выдай ЕДИНОЕ решение, учитывающее все точки зрения

Формат: markdown с русским языком. Используй заголовки ## для каждой секции."""

# ── Tier limits for Company Mode ──

def get_max_specialists(tier: str) -> int:
    return 4


# ── Specialist events ──


def _specialist_event(event_type: str, specialist: str, **extra) -> dict:
    # Strip "specialist." prefix from panel names
    name = specialist.replace("specialist.", "") if specialist.startswith("specialist.") else specialist
    return {"type": event_type, "specialist": name, "timestamp": time.time(), **extra}


# ── Orchestrator ──


class CompanyOrchestrator:

    def __init__(self, tier: str = "business"):
        self.tier = tier
        self.max_specialists = get_max_specialists(tier)

    async def orchestrate(
        self,
        user_query: str,
        specialist_names: list[str],
        user_id: str = "",
        session_id: str = "",
        model_override: str = "",
    ) -> AsyncGenerator[dict, None]:
        """Запускает специалистов параллельно, собирает ответы, отдаёт Архитектору на синтез."""

        # ── Валидация ──
        if len(specialist_names) > self.max_specialists:
            yield {
                "type": "error",
                "message": f"Tier {self.tier} supports max {self.max_specialists} specialist(s). Requested: {len(specialist_names)}",
            }
            return

        valid = [n for n in specialist_names if n in SPECIALIST_ROLES]
        if not valid:
            yield {"type": "error", "message": "No valid specialists requested"}
            return

        # ── Загрузка SpecialistConfig ──
        configs: dict[str, SpecialistConfig] = {}
        errors: list[str] = []
        for name in valid:
            try:
                configs[name] = load_specialist_context(name)
            except (ValueError, FileNotFoundError, OSError) as e:
                errors.append(f"{name}: {e}")

        if errors:
            yield {"type": "error", "message": f"Specialist load errors: {'; '.join(errors)}"}
            if not configs:
                return

        # ── Определение модели ──
        specialist_model = model_override or os.getenv("AMJ_SPECIALIST_MODEL", "deepseek-chat")

        yield {
            "type": "company.status",
            "phase": "starting",
            "specialists": [s.display_name for s in configs.values()],
            "total_count": len(configs),
        }

        # ── Общая очередь событий ──
        event_queue: asyncio.Queue = asyncio.Queue()
        set_side_event_queue(event_queue)

        # ── Параллельный запуск специалистов ──
        specialist_order: list[str] = []
        tasks: list[asyncio.Task] = []
        for name, cfg in configs.items():
            specialist_order.append(name)
            yield _specialist_event("specialist.start", name, role=cfg.role)
            tasks.append(
                asyncio.create_task(
                    _stream_one_with_context(
                        query=user_query,
                        model=specialist_model,
                        panel=f"specialist.{name}",
                        system_prompt=cfg.system_prompt,
                        tools=list(PRIMARY_TOOL_DEFINITIONS) if PRIMARY_TOOL_DEFINITIONS else None,
                        max_rounds=cfg.max_rounds,
                        specialist_config=cfg,
                    )
                )
            )

        # ── Дренаж очереди событий + ожидание gather ──
        gather_task = asyncio.ensure_future(asyncio.gather(*tasks, return_exceptions=True))

        while not gather_task.done():
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                event_type = event.get("type", "")
                panel = event.get("panel", "")

                if event_type == "primary_thinking_token":
                    yield _specialist_event("specialist.thinking", panel, token=event.get("token", ""))
                elif event_type == "primary_text_token":
                    yield _specialist_event("specialist.text_token", panel, token=event.get("token", ""))
                elif event_type == "primary_tool_start":
                    yield _specialist_event("specialist.tool_start", panel,
                                            tool_name=event.get("name", ""),
                                            tool_input=event.get("input"))
                elif event_type == "primary_tool_end":
                    yield _specialist_event("specialist.tool_end", panel,
                                            tool_name=event.get("name", ""),
                                            result=event.get("result"))
                elif event_type == "primary_done":
                    yield _specialist_event("specialist.done", panel,
                                            content=event.get("content", ""),
                                            reasoning_content=event.get("reasoning_content", ""),
                                            elapsed_ms=event.get("elapsed_ms", 0))
                elif event_type == "primary_error":
                    yield _specialist_event("specialist.error", panel,
                                            message=event.get("message", ""))
            except asyncio.TimeoutError:
                pass

        results = gather_task.result()

        # ── Сбор результатов ──
        specialist_results: dict[str, str] = {}
        for i, name in enumerate(specialist_order):
            result = results[i]
            if isinstance(result, Exception):
                specialist_results[name] = f"[ERROR] {result}"
            elif isinstance(result, dict):
                content = result.get("content", "")
                error = result.get("error", "")
                if error:
                    specialist_results[name] = f"[ERROR] {error}"
                else:
                    specialist_results[name] = content
            else:
                specialist_results[name] = "[ERROR] No result"

        # ── Checkpoint ──
        yield {
            "type": "company.checkpoint",
            "phase": "partial_synthesis",
            "specialists_completed": len(configs),
            "message": "Все специалисты завершили анализ. Передаю Архитектору на синтез.",
        }

        # ── Архитектор: синтез ──
        synthesis_prompt = self.build_synthesis_prompt_v2(user_query, specialist_results, configs)
        yield {"type": "company.synthesis", "phase": "starting"}

        architect_model = os.getenv("AMJ_ARCHITECT_MODEL", "deepseek-chat")
        architect_result = await _stream_one_with_context(
            query=synthesis_prompt,
            model=architect_model,
            panel="architect",
            system_prompt=ARCHITECT_SYSTEM_PROMPT,
            tools=list(PRIMARY_TOOL_DEFINITIONS) if PRIMARY_TOOL_DEFINITIONS else None,
            max_rounds=5,
            specialist_config=None,
        )

        # Дренаж оставшихся событий Архитектора
        while not event_queue.empty():
            try:
                event = event_queue.get_nowait()
                event_type = event.get("type", "")
                if event_type == "primary_text_token":
                    yield {"type": "company.synthesis", "phase": "streaming", "token": event.get("token", "")}
                elif event_type == "primary_done":
                    yield {"type": "company.synthesis", "phase": "streaming", "token": event.get("content", "")}
            except asyncio.QueueEmpty:
                break

        arch_content = architect_result.get("content", "") if isinstance(architect_result, dict) else str(architect_result)
        yield {"type": "company.synthesis", "phase": "complete", "content": arch_content}

        # ── Очистка ──
        set_side_event_queue(None)

    @staticmethod
    def build_synthesis_prompt_v2(
        user_query: str,
        specialist_results: dict[str, str],
        configs: dict[str, SpecialistConfig],
    ) -> str:
        """Собирает промпт для Архитектора с кросс-доменным синтезом."""
        parts = []
        parts.append(f"# Запрос пользователя\n{user_query}\n")

        parts.append("# Ответы специалистов\n")
        for name, result in specialist_results.items():
            cfg = configs.get(name)
            display = cfg.display_name if cfg else name
            role = cfg.role if cfg else name
            parts.append(f"## {display} ({role})\n{result}\n")

        parts.append("""# Инструкция для Архитектора

Синтезируй ОДИН ответ, учитывая:

1. **Консенсус** — в чём все специалисты согласны? Выдели общие точки.
2. **Противоречия** — где мнения расходятся? Например:
   - Маркетолог хочет запускать рекламу, а юрист требует compliance-проверку
   - Бухгалтер ограничивает бюджет, а DevOps хочет больше серверов
3. **Пробелы** — на какие вопросы никто не ответил? Что нужно выяснить дополнительно?
4. **Приоритеты** — что делать first / next / later?
5. **Единое решение** — ОДИН синтезированный ответ, который учитывает ВСЕ точки зрения.

Формат ответа:
## Сводка
(2-3 предложения — суть решения)

## Консенсус
- Пункт 1
- Пункт 2

## Противоречия
- Противоречие 1: описание + предлагаемое разрешение
- Противоречие 2: ...

## Пробелы
- Что осталось неясным

## План действий
1. First: ...
2. Next: ...
3. Later: ...

## Риски
- Риск 1
- Риск 2
""")
        return "\n".join(parts)
