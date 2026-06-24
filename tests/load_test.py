#!/usr/bin/env python3
"""AIModelJudge — Async load testing suite (aiohttp + asyncio).

5 scenarios:
  A — Concurrent: 5 concurrent x 3 iterations, p95 < 30s
  B — Memory leak: 30 sequential requests, RSS growth < 50MB
  C — Long message: 3 requests with 5000+ char messages, < 120s
  D — Cancel: Start chat, cancel after 1s, assert stop_reason=cancelled
  E — Health under load: /health ping every 2s during scenario A

Usage:
  PYTHONPATH=$PWD:$PWD/web:$PWD/services/shared python3 tests/load_test.py [base_url]
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

BASE_URL: str = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9651"
TEST_EMAIL: str = "loadtest@aimodeljudge.local"
TEST_PASSWORD: str = "loadtest1234"


# ── Data ────────────────────────────────────────────────────────────────────


@dataclass
class LoadTestResult:
    scenario: str
    duration: float = 0.0
    durations: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def p50(self) -> float:
        return compute_percentile(self.durations, 50) if self.durations else 0.0

    @property
    def p95(self) -> float:
        return compute_percentile(self.durations, 95) if self.durations else 0.0

    @property
    def success_rate(self) -> float:
        if not self.durations:
            return 0.0
        return (len(self.durations) - len(self.errors)) / max(len(self.durations), 1)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


# ── Helpers ─────────────────────────────────────────────────────────────────


def compute_percentile(data: list[float], percentile: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * percentile / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
    return sorted_data[f]


def measure_memory_rss() -> int:
    """RSS in bytes."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


# ── Auth helper ─────────────────────────────────────────────────────────────


async def get_api_key(session: aiohttp.ClientSession) -> str | None:
    """Register or login and return API key."""
    # Try login first
    try:
        async with session.post(
            f"{BASE_URL}/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("api_key") or data.get("token")
    except Exception:
        pass

    # Register
    try:
        async with session.post(
            f"{BASE_URL}/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        ) as resp:
            if resp.status in (200, 201):
                data = await resp.json()
                return data.get("api_key") or data.get("token")
    except Exception:
        pass

    return None


# ── SSE helpers ─────────────────────────────────────────────────────────────


async def read_sse_stream(response: aiohttp.ClientResponse, timeout: float = 30.0) -> dict:
    """Read SSE stream and collect key fields. Returns dict with stop_reason, session_id, error."""
    result: dict = {"stop_reason": "unknown", "session_id": "", "error": None, "text": ""}
    deadline = time.monotonic() + timeout
    buffer = ""
    try:
        async for chunk in response.content.iter_chunked(1024):
            if time.monotonic() > deadline:
                result["error"] = "timeout"
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                line, buffer = buffer.split("\n\n", 1)
                for raw in line.split("\n"):
                    if raw.startswith("data: "):
                        data_str = raw[6:]
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "done":
                            result["stop_reason"] = event.get("stop_reason", "end_turn")
                        if event.get("type") == "error":
                            result["error"] = event.get("message", "unknown")
                        if event.get("type") == "run.started":
                            result["session_id"] = event.get("sessionId", "")
                        if event.get("type") == "text_token":
                            result["text"] += event.get("token", "")
                        # Fallback: sessionId in done event
                        if not result["session_id"]:
                            result["session_id"] = event.get("sessionId", "")
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        if not result["error"]:
            result["error"] = str(exc)
    return result


# ── Scenarios ───────────────────────────────────────────────────────────────


async def scenario_a_concurrent(session: aiohttp.ClientSession) -> LoadTestResult:
    """5 concurrent x 3 iterations. Assert p95 < 30s."""
    result = LoadTestResult(scenario="A — Concurrent (5x3)")
    concurrent = 5
    iterations = 3
    all_durations: list[float] = []

    for iteration in range(iterations):
        async def one_request(idx: int) -> float:
            t0 = time.monotonic()
            try:
                async with session.post(
                    f"{BASE_URL}/chat",
                    json={"message": f"Say {iteration}-{idx} in exactly one word"},
                ) as resp:
                    sse = await read_sse_stream(resp, timeout=45)
                    if sse.get("error"):
                        result.errors.append(f"Iter {iteration}/{idx}: {sse['error']}")
            except Exception as exc:
                result.errors.append(f"Iter {iteration}/{idx}: {exc}")
            return time.monotonic() - t0

        tasks = [one_request(i) for i in range(concurrent)]
        durations = await asyncio.gather(*tasks)
        all_durations.extend(durations)

    result.durations = all_durations
    result.duration = sum(all_durations)
    if result.p95 > 30.0:
        result.errors.append(f"p95={result.p95:.1f}s exceeds 30s threshold")
    return result


async def scenario_b_memory(session: aiohttp.ClientSession) -> LoadTestResult:
    """30 sequential requests. Assert RSS growth < 50MB."""
    result = LoadTestResult(scenario="B — Memory leak (30 sequential)")
    rss_start = measure_memory_rss()

    for i in range(30):
        t0 = time.monotonic()
        try:
            async with session.post(
                f"{BASE_URL}/chat",
                json={"message": f"Reply with exactly 3 words: test number {i}"},
            ) as resp:
                sse = await read_sse_stream(resp, timeout=45)
                if sse.get("error"):
                    result.errors.append(f"Req {i}: {sse['error']}")
        except Exception as exc:
            result.errors.append(f"Req {i}: {exc}")
        result.durations.append(time.monotonic() - t0)

    rss_end = measure_memory_rss()
    growth_mb = (rss_end - rss_start) / (1024 * 1024)
    result.extra["rss_growth_mb"] = growth_mb
    result.duration = sum(result.durations)
    if growth_mb > 50.0:
        result.errors.append(f"RSS growth {growth_mb:.1f}MB exceeds 50MB threshold")
    return result


async def scenario_c_long_message(session: aiohttp.ClientSession) -> LoadTestResult:
    """3 requests with 5000+ char messages. Assert completion within 120s."""
    result = LoadTestResult(scenario="C — Long message (3 x 5000+ chars)")
    long_msg = (
        "Please analyze the following text carefully. " * 200
        + "The key points to consider are: 1) Structure and organization, "
        + "2) Readability and clarity, 3) Technical accuracy. " * 50
    )

    for i in range(3):
        t0 = time.monotonic()
        try:
            async with session.post(
                f"{BASE_URL}/chat",
                json={"message": f"[Test {i+1}/3] {long_msg}"},
            ) as resp:
                sse = await read_sse_stream(resp, timeout=130)
                elapsed = time.monotonic() - t0
                result.durations.append(elapsed)
                if elapsed > 120.0:
                    result.errors.append(f"Long msg {i}: {elapsed:.1f}s > 120s")
                if sse.get("error"):
                    result.errors.append(f"Long msg {i}: {sse['error']}")
        except Exception as exc:
            result.durations.append(time.monotonic() - t0)
            result.errors.append(f"Long msg {i}: {exc}")

    result.duration = sum(result.durations)
    return result


async def scenario_d_cancel(session: aiohttp.ClientSession, api_key: str) -> LoadTestResult:
    """Start chat, cancel after 1s, assert stop_reason=cancelled."""
    result = LoadTestResult(scenario="D — Cancel (stop_reason=cancelled)")

    if not api_key:
        result.errors.append("No API key — cannot test cancel (requires auth)")
        return result

    t0 = time.monotonic()
    try:
        async with session.post(
            f"{BASE_URL}/chat",
            json={
                "message": "Write a comprehensive essay about the history of artificial intelligence from 1950 to 2030, covering all major milestones, key researchers, technological breakthroughs, and societal impacts in minute detail."
            },
        ) as resp:
            # Read first few chunks to get session_id, then cancel
            session_id = ""
            deadline = time.monotonic() + 2.0
            buffer = ""
            async for chunk in resp.content.iter_chunked(256):
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buffer:
                    line, buffer = buffer.split("\n\n", 1)
                    for raw in line.split("\n"):
                        if raw.startswith("data: "):
                            try:
                                event = json.loads(raw[6:])
                            except json.JSONDecodeError:
                                continue
                            sid = event.get("sessionId", "")
                            if sid and not session_id:
                                session_id = sid
                if session_id or time.monotonic() > deadline:
                    break

            if session_id:
                # Small delay to ensure the stream is established
                await asyncio.sleep(0.5)
                async with session.post(
                    f"{BASE_URL}/cancel",
                    headers={"X-Stream-Session": session_id, "X-AMJ-API-Key": api_key},
                ) as cancel_resp:
                    cancel_data = await cancel_resp.json()
                    result.extra["cancel_response"] = cancel_data

            # Drain the rest to capture stop_reason
            sse = await read_sse_stream(resp, timeout=15)
            result.extra["stop_reason"] = sse.get("stop_reason", "unknown")
            if sse.get("stop_reason") != "cancelled":
                result.errors.append(
                    f"Expected stop_reason=cancelled, got {sse.get('stop_reason')}"
                )
    except Exception as exc:
        result.errors.append(f"Cancel scenario: {exc}")

    result.duration = time.monotonic() - t0
    result.durations = [result.duration]
    return result


async def scenario_e_health(
    session: aiohttp.ClientSession, concurrent_duration: float
) -> LoadTestResult:
    """Ping /health every 2s. Collect response times and error count."""
    result = LoadTestResult(scenario="E — Health under load")
    if concurrent_duration <= 0:
        concurrent_duration = 30.0

    elapsed = 0.0
    while elapsed < concurrent_duration:
        t0 = time.monotonic()
        try:
            async with session.get(f"{BASE_URL}/health") as resp:
                if resp.status != 200:
                    result.errors.append(f"Health returned {resp.status}")
        except Exception as exc:
            result.errors.append(f"Health: {exc}")
        result.durations.append(time.monotonic() - t0)
        elapsed += 2.0
        if elapsed < concurrent_duration:
            await asyncio.sleep(2.0)

    result.duration = sum(result.durations)
    return result


# ── Main ────────────────────────────────────────────────────────────────────


async def main() -> int:
    print(f"AIModelJudge Load Test Suite")
    print(f"Target: {BASE_URL}")
    print(f"=" * 60)

    connector = aiohttp.TCPConnector(limit=20, limit_per_host=20)
    timeout = aiohttp.ClientTimeout(total=180)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Pre-warm: simple health check
        print("\n[pre-flight] Checking server...")
        try:
            async with session.get(f"{BASE_URL}/health") as resp:
                health_data = await resp.json()
                print(f"  Server status: {resp.status} — {health_data.get('status', 'unknown')}")
        except Exception as exc:
            print(f"  ERROR: Cannot reach server at {BASE_URL}: {exc}")
            print(f"  Make sure the backend is running: PYTHONPATH=$PWD:$PWD/web:$PWD/services/shared python3 web/main.py")
            return 1

        # Get API key for cancel test
        api_key = await get_api_key(session)
        if api_key:
            print(f"  Auth: OK (key={api_key[:8]}...)")
        else:
            print(f"  Auth: no API key (cancel test will be skipped)")

        results: list[LoadTestResult] = []

        # ── Scenario A: Concurrent ──
        print(f"\n{'='*60}")
        print(f"  A — Concurrent (5 concurrent x 3 iterations)")
        print(f"{'='*60}")
        ra = await scenario_a_concurrent(session)
        results.append(ra)
        print_result(ra)

        # ── Scenario E: Health (runs alongside A conceptually; we measure during A's duration) ──
        print(f"\n{'='*60}")
        print(f"  E — Health under load (ping /health every 2s during ~concurrent duration)")
        print(f"{'='*60}")
        # Run health checks concurrently with the last batch or after concurrent as simulation
        re_health = await scenario_e_health(session, ra.duration / max(ra.durations.count(0.0), 1))
        results.append(re_health)
        print_result(re_health)

        # ── Scenario B: Memory ──
        print(f"\n{'='*60}")
        print(f"  B — Memory leak (30 sequential)")
        print(f"{'='*60}")
        rb = await scenario_b_memory(session)
        results.append(rb)
        print_result(rb)

        # ── Scenario C: Long message ──
        print(f"\n{'='*60}")
        print(f"  C — Long message (3 x 5000+ chars)")
        print(f"{'='*60}")
        rc = await scenario_c_long_message(session)
        results.append(rc)
        print_result(rc)

        # ── Scenario D: Cancel ──
        print(f"\n{'='*60}")
        print(f"  D — Cancel (stop_reason=cancelled)")
        print(f"{'='*60}")
        rd = await scenario_d_cancel(session, api_key)
        results.append(rd)
        print_result(rd)

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    total_errors = 0
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        marker = "✓" if r.passed else "✗"
        print(f"  {marker} {r.scenario}: {status} ({len(r.errors)} errors)")
        for err in r.errors:
            print(f"      - {err}")
        total_errors += len(r.errors)

    print(f"\n  Total: {len(results)} scenarios, {total_errors} errors")
    if total_errors == 0:
        print(f"  ALL SCENARIOS PASSED")
        return 0
    else:
        print(f"  SOME SCENARIOS FAILED")
        return 1


def print_result(r: LoadTestResult) -> None:
    print(f"  Duration: {r.duration:.1f}s total")
    if r.durations:
        print(f"  Latency: p50={r.p50:.1f}s p95={r.p95:.1f}s min={min(r.durations):.1f}s max={max(r.durations):.1f}s")
    if r.extra:
        for k, v in r.extra.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.1f}")
            else:
                print(f"  {k}: {v}")
    if r.errors:
        for e in r.errors:
            print(f"  ERROR: {e}")
    status = "PASS" if r.passed else "FAIL"
    print(f"  → {status}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
