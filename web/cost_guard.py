"""AIModelJudge Cost Guard — защита от перерасхода API.

Лимиты запросов, дневной бюджет, model gating, подсчёт токенов.
Все данные: SQLite (monthly_request_counts, api_usage_log) + in-memory (daily spend).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("aimodeljudge.cost_guard")

# ── State DB path ──
_STATE_DB = Path.home() / ".hermes-aimodeljudge" / "state.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_STATE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ══════════════════════════════════════════════════════════════════════
# Tier Cost Config
# ══════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class TierCostConfig:
    monthly_requests: int       # 0 = unlimited
    daily_budget_usd: float     # 0 = unlimited
    allowed_models: str         # "flash" | "any"
    max_input_tokens: int       # 0 = no limit
    max_tools: int              # 0 = no limit
    timeout_s: int


COST_LIMITS: dict[str, TierCostConfig] = {
    "default": TierCostConfig(0, 0, "any", 0, 0, 120),
}


def check_model_allowed_for_tier(model_name: str, tier: str) -> bool:
    """True для всех моделей (default tier)."""
    return True


# ══════════════════════════════════════════════════════════════════════
# Monthly Request Counter (SQLite)
# ══════════════════════════════════════════════════════════════════════


class MonthlyRequestCounter:
    """Счётчик запросов в месяц. Ключ: (user_id, YYYY-MM). Авто-сброс при новом месяце."""

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS monthly_request_counts (
        user_id TEXT NOT NULL,
        year_month TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, year_month)
    );
    """

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        try:
            conn = _get_conn()
            conn.execute(self.TABLE_DDL)
            conn.commit()
            conn.close()
        except sqlite3.OperationalError:
            pass

    def check_and_increment(self, user_id: str, tier: str) -> tuple[bool, int, int]:
        """Возвращает (allowed, current_count, limit). Если allowed — счётчик увеличивается."""
        config = COST_LIMITS.get(tier, COST_LIMITS["default"])
        limit = config.monthly_requests
        if limit == 0:
            return True, 0, 0  # enterprise — безлимит

        now = time.strftime("%Y-%m")
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT request_count FROM monthly_request_counts "
                "WHERE user_id = ? AND year_month = ?",
                (user_id, now),
            ).fetchone()
            current = row["request_count"] if row else 0

            if current >= limit:
                conn.close()
                return False, current, limit

            new_count = current + 1
            conn.execute(
                "INSERT INTO monthly_request_counts (user_id, year_month, request_count) "
                "VALUES (?, ?, 1) ON CONFLICT(user_id, year_month) "
                "DO UPDATE SET request_count = request_count + 1",
                (user_id, now),
            )
            conn.commit()
            conn.close()
            return True, new_count, limit
        except Exception:
            conn.close()
            raise

    def get_count(self, user_id: str) -> int:
        now = time.strftime("%Y-%m")
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT request_count FROM monthly_request_counts "
                "WHERE user_id = ? AND year_month = ?",
                (user_id, now),
            ).fetchone()
            return row["request_count"] if row else 0
        finally:
            conn.close()


_monthly_counter = MonthlyRequestCounter()


def get_monthly_counter() -> MonthlyRequestCounter:
    return _monthly_counter


# ══════════════════════════════════════════════════════════════════════
# Daily Spend Tracker (in-memory, thread-safe)
# ══════════════════════════════════════════════════════════════════════


class DailySpendTracker:
    """In-memory трекер дневных расходов. Сбрасывается в полночь."""

    def __init__(self):
        self._lock = threading.Lock()
        self._spend: dict[str, float] = {}

    def add_spend(self, user_id: str, cost_usd: float) -> float:
        with self._lock:
            current = self._spend.get(user_id, 0.0)
            self._spend[user_id] = current + cost_usd
            return self._spend[user_id]

    def get_spend(self, user_id: str) -> float:
        with self._lock:
            return self._spend.get(user_id, 0.0)

    def check_budget(self, user_id: str, tier: str, estimated_cost: float = 0.0) -> tuple[bool, float, float]:
        """(allowed, current_spend, budget_limit). estimated_cost добавляется к текущему."""
        config = COST_LIMITS.get(tier, COST_LIMITS["default"])
        budget = config.daily_budget_usd
        if budget == 0:
            return True, self.get_spend(user_id), float("inf")
        current = self.get_spend(user_id)
        return (current + estimated_cost) <= budget, current, budget

    def reset_all(self):
        with self._lock:
            self._spend.clear()

    @property
    def all_spend(self) -> dict[str, float]:
        with self._lock:
            return dict(self._spend)


_daily_tracker = DailySpendTracker()


def get_daily_spend_tracker() -> DailySpendTracker:
    return _daily_tracker


# ══════════════════════════════════════════════════════════════════════
# API Usage Logging
# ══════════════════════════════════════════════════════════════════════


def _ensure_usage_log_table():
    try:
        conn = _get_conn()
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
    except sqlite3.OperationalError:
        pass


def log_api_usage(
    user_id: str,
    session_id: str,
    model_name: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    tier: str = "default",
) -> float:
    """Логирует использование API. Возвращает estimated_cost_usd."""
    _ensure_usage_log_table()

    # Оценка стоимости через usage_pricing
    cost = _estimate_cost(model_name, input_tokens, output_tokens)

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO api_usage_log "
            "(user_id, session_id, model_name, input_tokens, output_tokens, "
            "estimated_cost_usd, timestamp, tier) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
            (user_id, session_id, model_name, input_tokens, output_tokens, cost, tier),
        )
        conn.commit()
    finally:
        conn.close()

    # Обновляем in-memory трекер
    tracker = get_daily_spend_tracker()
    tracker.add_spend(user_id, cost)

    # Audit log
    try:
        from web.audit import log_audit
        log_audit(
            user_id, "api_cost", "usage",
            f"model={model_name} in={input_tokens} out={output_tokens} cost=${cost:.6f}",
            result="success",
        )
    except Exception:
        pass

    return cost


# Approximate pricing — removed for public release
_MODEL_PRICING: dict[str, tuple[float, float]] = {}


def _estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost based on model pricing table — simplified for public release."""
    return 0.0


def get_usage_log(user_id: str, days: int = 1) -> list[dict]:
    """Последние записи использования API для пользователя."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM api_usage_log WHERE user_id = ? "
            "AND timestamp >= datetime('now', ?) ORDER BY timestamp DESC LIMIT 200",
            (user_id, f"-{days} days"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# Request Complexity Check
# ══════════════════════════════════════════════════════════════════════


def estimate_token_count(text: str) -> int:
    """Грубая оценка токенов: ~4 символа на токен. ±25% для English/code."""
    return max(1, len(text) // 4)


def check_request_complexity(
    user_message: str,
    tool_count: int,
    tier: str,
) -> tuple[bool, str]:
    """(allowed, error_message). Проверяет лимиты на входные токены и количество инструментов."""
    config = COST_LIMITS.get(tier, COST_LIMITS["default"])

    if config.max_input_tokens > 0:
        estimated = estimate_token_count(user_message)
        if estimated > config.max_input_tokens:
            return False, (
                f"Входное сообщение слишком длинное (~{estimated} токенов). "
                f"Лимит: {config.max_input_tokens} токенов. "
                "Разбейте запрос на части или укажите конкретный файл."
            )

    if config.max_tools > 0 and tool_count > config.max_tools:
        return False, (
            f"Слишком много инструментов в запросе ({tool_count}). "
            f"Лимит: {config.max_tools}. Упростите запрос."
        )

    return True, ""
