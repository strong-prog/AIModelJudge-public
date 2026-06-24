"""AIModelJudge — BenchmarkTracker: сбор метрик по запросам.

Хранение: ~/.hermes-aimodeljudge/benchmarks.jsonl (append-only).
Метрики: токены, время ответа, success rate, tool calls, фазы.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"
_BENCHMARKS_PATH = _BASE / "benchmarks.jsonl"


@dataclass
class RequestMetrics:
    request_id: str
    timestamp: float
    phase: str
    model: str
    tokens_in: int
    tokens_out: int
    duration_ms: float
    tool_calls_count: int
    success: bool
    tokens_per_phase: dict = field(default_factory=dict)  # {"inquire": 0, "consult": 0, ...}
    cache_hit: bool = False


class BenchmarkTracker:
    def __init__(self, path: Path | None = None):
        self._path = path or _BENCHMARKS_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def track(self, m: RequestMetrics) -> None:
        rec = asdict(m)
        rec["timestamp"] = m.timestamp  # float, not str
        with open(self._path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def stats(self, days: int = 7) -> dict:
        cutoff = time.time() - days * 86400
        records = self._load_recent(cutoff)
        if not records:
            return {
                "total": 0,
                "avg_duration_ms": 0,
                "p50_duration_ms": 0,
                "p95_duration_ms": 0,
                "avg_tokens": 0,
                "success_rate": 0.0,
                "by_model": {},
                "by_phase": {},
                "daily": [],
            }

        durations = sorted(r["duration_ms"] for r in records)
        n = len(durations)
        p50 = durations[int(n * 0.50)] if n > 0 else 0
        p95 = durations[int(n * 0.95)] if n > 1 else durations[-1]

        by_model: dict[str, dict] = {}
        by_phase: dict[str, dict] = {}
        daily: dict[str, dict] = {}

        for r in records:
            model = r.get("model", "?")
            phase = r.get("phase", "?")
            day = r.get("timestamp", "")
            if isinstance(day, (int, float)):
                day = time.strftime("%Y-%m-%d", time.localtime(day))
            elif "T" in str(day):
                day = str(day)[:10]

            for bucket, key, entry in [
                (by_model, model, r),
                (by_phase, phase, r),
                (daily, day, r),
            ]:
                if key not in bucket:
                    bucket[key] = {"count": 0, "total_duration_ms": 0, "total_tokens": 0, "successes": 0}
                bucket[key]["count"] += 1
                bucket[key]["total_duration_ms"] += entry.get("duration_ms", 0)
                bucket[key]["total_tokens"] += entry.get("tokens_in", 0) + entry.get("tokens_out", 0)
                if entry.get("success"):
                    bucket[key]["successes"] += 1

        for bucket in (by_model, by_phase, daily):
            for v in bucket.values():
                v["avg_duration_ms"] = round(v["total_duration_ms"] / v["count"], 1)
                v["avg_tokens"] = round(v["total_tokens"] / v["count"])
                v["success_rate"] = round(v["successes"] / v["count"], 3)

        daily_sorted = [
            {"day": d, **v} for d, v in sorted(daily.items(), reverse=True)
        ]

        return {
            "total": n,
            "avg_duration_ms": round(sum(durations) / n, 1),
            "p50_duration_ms": p50,
            "p95_duration_ms": p95,
            "avg_tokens": round(
                sum(r.get("tokens_in", 0) + r.get("tokens_out", 0) for r in records) / n
            ),
            "success_rate": round(
                sum(1 for r in records if r.get("success")) / n, 3
            ),
            "by_model": {k: v for k, v in sorted(by_model.items(), key=lambda x: -x[1]["count"])},
            "by_phase": by_phase,
            "daily": daily_sorted[:days],
        }

    def recent(self, limit: int = 50) -> list[dict]:
        cutoff = time.time() - 7 * 86400  # always last 7 days for recent
        records = self._load_recent(cutoff)
        return records[-limit:][::-1]

    def _load_recent(self, cutoff: float) -> list[dict]:
        records: list[dict] = []
        if not self._path.exists():
            return records
        try:
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        ts = r.get("timestamp")
                        if isinstance(ts, (int, float)) and ts > cutoff:
                            records.append(r)
                        elif isinstance(ts, str):
                            try:
                                if float(ts) > cutoff:
                                    records.append(r)
                            except ValueError:
                                records.append(r)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return records


_tracker = BenchmarkTracker()


def get_tracker() -> BenchmarkTracker:
    return _tracker
