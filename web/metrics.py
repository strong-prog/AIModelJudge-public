"""Prometheus-compatible metrics endpoint (pure Python, no dependencies).

Предоставляет /metrics в формате Prometheus text exposition format.
Легковесная имплементация Counter / Gauge / Histogram без внешних библиотек.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger("aimodeljudge.metrics")


@dataclass
class _Sample:
    """One labelled sample within a metric."""
    labels: dict[str, str]
    value: float
    timestamp_ms: int


class Counter:
    """Monotonically increasing counter (Prometheus Counter)."""

    def __init__(self, name: str, help_text: str, label_names: Optional[list[str]] = None):
        self.name = name
        self.help = help_text
        self._type = "counter"
        self._label_names = label_names or []
        self._values: dict[tuple, float] = defaultdict(float)

    def inc(self, amount: float = 1.0, **labels: str):
        key = tuple(labels.get(k, "") for k in self._label_names)
        self._values[key] += amount

    def get(self, **labels: str) -> float:
        key = tuple(labels.get(k, "") for k in self._label_names)
        return self._values.get(key, 0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self._type}"]
        for key, val in self._values.items():
            label_pairs = ",".join(f'{k}="{v}"' for k, v in zip(self._label_names, key))
            label_str = f"{{{label_pairs}}}" if label_pairs else ""
            lines.append(f"{self.name}{label_str} {val}")
        return lines


class Gauge:
    """Point-in-time gauge metric (Prometheus Gauge)."""

    def __init__(self, name: str, help_text: str, label_names: Optional[list[str]] = None):
        self.name = name
        self.help = help_text
        self._type = "gauge"
        self._label_names = label_names or []
        self._values: dict[tuple, float] = defaultdict(float)

    def set(self, value: float, **labels: str):
        key = tuple(labels.get(k, "") for k in self._label_names)
        self._values[key] = value

    def inc(self, amount: float = 1.0, **labels: str):
        key = tuple(labels.get(k, "") for k in self._label_names)
        self._values[key] += amount

    def dec(self, amount: float = 1.0, **labels: str):
        key = tuple(labels.get(k, "") for k in self._label_names)
        self._values[key] -= amount

    def get(self, **labels: str) -> float:
        key = tuple(labels.get(k, "") for k in self._label_names)
        return self._values.get(key, 0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self._type}"]
        for key, val in self._values.items():
            label_pairs = ",".join(f'{k}="{v}"' for k, v in zip(self._label_names, key))
            label_str = f"{{{label_pairs}}}" if label_pairs else ""
            lines.append(f"{self.name}{label_str} {val}")
        return lines


class Histogram:
    """Prometheus Histogram (cumulative buckets + sum + count)."""

    def __init__(self, name: str, help_text: str, buckets: Optional[list[float]] = None):
        self.name = name
        self.help = help_text
        self._type = "histogram"
        self._buckets = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
        self._bucket_counts: dict[str, int] = defaultdict(int)
        self._sum: float = 0.0
        self._count: int = 0

    def observe(self, value: float):
        self._sum += value
        self._count += 1
        bucket_name = "+Inf"
        for b in self._buckets:
            if value <= b:
                bucket_name = str(b)
                break
        self._bucket_counts[bucket_name] += 1

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self._type}"]
        # Cumulative bucket counts
        cum = 0
        for b in self._buckets:
            cum += self._bucket_counts.get(str(b), 0)
            lines.append(f'{self.name}_bucket{{le="{b}"}} {cum}')
        cum += self._bucket_counts.get("+Inf", 0)
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {cum}')
        lines.append(f"{self.name}_sum {self._sum}")
        lines.append(f"{self.name}_count {self._count}")
        return lines


# ── Application metrics ──

_chat_requests = Counter(
    "amj_chat_requests_total",
    "Total chat requests processed",
    ["tier", "status"],
)
_chat_duration = Histogram(
    "amj_chat_duration_seconds",
    "Chat request duration in seconds",
)
_tool_executions = Counter(
    "amj_tool_executions_total",
    "Tool executions by tool name",
    ["tool"],
)
_tool_errors = Counter(
    "amj_tool_errors_total",
    "Tool execution errors",
    ["tool", "error_type"],
)
_active_sessions = Gauge(
    "amj_active_sessions",
    "Number of active SSE sessions",
)
_cache_hits = Counter(
    "amj_model_cache_hits_total",
    "Model cache hits",
)
_cache_misses = Counter(
    "amj_model_cache_misses_total",
    "Model cache misses",
)
_sandbox_blocks = Counter(
    "amj_sandbox_blocks_total",
    "Sandbox blocked commands",
    ["reason"],
)
_prompt_guard_blocks = Counter(
    "amj_prompt_guard_blocks_total",
    "Prompt Guard injection blocks",
    ["category"],
)
_prompt_guard_warns = Counter(
    "amj_prompt_guard_warnings_total",
    "Prompt Guard injection warnings",
    ["category"],
)
_api_keys_active = Gauge(
    "amj_api_keys_active",
    "Number of active API keys",
)
_start_time = time.time()
_app_info = Gauge(
    "amj_app_info",
    "Application version info",
)


def _init_app_info():
    """Установить метрику приложения."""
    _app_info.set(1.0)


_init_app_info()

# ── Public API ──


def record_chat_request(tier: str, status: str):
    _chat_requests.inc(tier=tier, status=status)


def record_chat_duration(seconds: float):
    _chat_duration.observe(seconds)


def record_tool_execution(tool: str):
    _tool_executions.inc(tool=tool)


def record_tool_error(tool: str, error_type: str):
    _tool_errors.inc(tool=tool, error_type=error_type)


def record_sandbox_block(reason: str):
    _sandbox_blocks.inc(reason=reason[:60])


def record_prompt_guard_block(category: str):
    _prompt_guard_blocks.inc(category=category)


def record_prompt_guard_warn(category: str):
    _prompt_guard_warns.inc(category=category)


def set_active_sessions(count: int):
    _active_sessions.set(float(count))


def set_api_keys_active(count: int):
    _api_keys_active.set(float(count))


def record_cache_hit():
    _cache_hits.inc()


def record_cache_miss():
    _cache_misses.inc()


def set_system_memory():
    """Обновить системные метрики (вызывается при /metrics scrape)."""
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        Gauge("amj_system_memory_maxrss_bytes", "Max RSS memory").set(
            float(usage.ru_maxrss * (1024 if os.name == "posix" else 1))
        )
    except Exception:
        pass


# ── Render ──

_ALL_METRICS: list[Counter | Gauge | Histogram] = [
    _chat_requests, _chat_duration, _tool_executions, _tool_errors,
    _active_sessions, _cache_hits, _cache_misses,
    _sandbox_blocks, _prompt_guard_blocks, _prompt_guard_warns,
    _api_keys_active, _app_info,
]


def render_metrics() -> str:
    """Генерирует Prometheus text exposition format."""
    set_system_memory()
    lines = []
    for m in _ALL_METRICS:
        lines.extend(m.render())
        lines.append("")
    return "\n".join(lines)
