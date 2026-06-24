"""HermesMCPClient — асинхронный клиент к hermes-mcp (localhost:8765).

Поддерживает sync/async режимы для долгих задач (>30s).
Используется Central Judge как инструмент hermes_ask.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

_log = logging.getLogger("aimodeljudge.mcp_client")

MCP_BASE = "http://127.0.0.1:8765"
REQUEST_TIMEOUT = 45.0  # sync mode default
ASYNC_POLL_INTERVAL = 2.0  # seconds between status checks
ASYNC_MAX_WAIT = 180.0  # max seconds for async jobs

# Ориентировочный порог сложности для auto-async (длина промпта)
ASYNC_COMPLEXITY_THRESHOLD = 500


@dataclass
class MCPResponse:
    ok: bool
    content: str
    job_id: str = ""
    status: str = ""
    error: str = ""


@dataclass
class MCPJobStatus:
    job_id: str
    status: str  # queued | running | completed | failed
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


class HermesMCPClient:
    """Streamable HTTP клиент к hermes-mcp серверу."""

    def __init__(self, base_url: str = MCP_BASE, timeout: float = REQUEST_TIMEOUT):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    # ── public API ─────────────────────────────────────────────────────

    async def hermes_ask(
        self,
        prompt: str,
        async_mode: bool | None = None,
        session_id: str | None = None,
    ) -> MCPResponse:
        """Отправить запрос hermes-mcp.

        Args:
            prompt: Текст запроса.
            async_mode: True — вернуть job_id сразу, False — ждать результат.
                        None — автоопределение по длине промпта.
            session_id: Идентификатор сессии для контекста.
        """
        if async_mode is None:
            async_mode = len(prompt) > ASYNC_COMPLEXITY_THRESHOLD

        body: dict[str, Any] = {"prompt": prompt, "async": async_mode}
        if session_id:
            body["session_id"] = session_id

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base}/ask",
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            _log.warning("hermes-mcp /ask failed: %s", exc)
            return MCPResponse(ok=False, content="", error=str(exc))
        except json.JSONDecodeError:
            return MCPResponse(ok=False, content="", error="Invalid JSON from hermes-mcp")

        # Async mode — возвращаем job_id для последующей проверки
        if async_mode:
            job_id = data.get("job_id", "")
            if job_id:
                return MCPResponse(
                    ok=True,
                    content=f"Задача отправлена асинхронно. job_id={job_id}",
                    job_id=job_id,
                    status="queued",
                )
            return MCPResponse(ok=False, content="", error="No job_id in async response")

        return MCPResponse(
            ok=True,
            content=data.get("content", data.get("result", str(data))),
            status="completed",
        )

    async def hermes_check(self, job_id: str) -> MCPJobStatus:
        """Проверить статус асинхронного задания."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._base}/jobs/{job_id}",
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            _log.warning("hermes-mcp /jobs/%s failed: %s", job_id, exc)
            return MCPJobStatus(job_id=job_id, status="unknown", error=str(exc))
        except json.JSONDecodeError:
            return MCPJobStatus(job_id=job_id, status="unknown", error="Invalid JSON")

        return MCPJobStatus(
            job_id=job_id,
            status=data.get("status", "unknown"),
            result=data.get("result", ""),
            error=data.get("error", ""),
            created_at=data.get("created_at", 0),
            updated_at=data.get("updated_at", 0),
        )

    async def hermes_cancel(self, job_id: str) -> bool:
        """Отменить асинхронное задание."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._base}/jobs/{job_id}/cancel",
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return True
        except httpx.HTTPError as exc:
            _log.warning("hermes-mcp cancel %s failed: %s", job_id, exc)
            return False

    async def hermes_ask_and_wait(
        self,
        prompt: str,
        session_id: str | None = None,
        poll_interval: float = ASYNC_POLL_INTERVAL,
        max_wait: float = ASYNC_MAX_WAIT,
    ) -> MCPResponse:
        """Отправить асинхронно и ждать результата (опрос циклом).

        Используется для задач, которые могут занять >30s.
        """
        resp = await self.hermes_ask(prompt, async_mode=True, session_id=session_id)
        if not resp.ok or not resp.job_id:
            resp.ok = False
            resp.error = resp.error or "Failed to create async job"
            return resp

        started = time.monotonic()
        while (time.monotonic() - started) < max_wait:
            await asyncio.sleep(poll_interval)
            status = await self.hermes_check(resp.job_id)

            if status.status == "completed":
                return MCPResponse(
                    ok=True,
                    content=status.result,
                    job_id=resp.job_id,
                    status="completed",
                )
            if status.status == "failed":
                return MCPResponse(
                    ok=False,
                    content="",
                    job_id=resp.job_id,
                    status="failed",
                    error=status.error or "Job failed",
                )
            if status.status == "unknown":
                return MCPResponse(
                    ok=False,
                    content="",
                    job_id=resp.job_id,
                    error="Job status unknown (server may be down)",
                )

        # Timeout — пытаемся отменить
        await self.hermes_cancel(resp.job_id)
        return MCPResponse(
            ok=False,
            content="",
            job_id=resp.job_id,
            error=f"Async job timed out after {max_wait}s",
        )

    async def health(self) -> bool:
        """Проверить доступность hermes-mcp."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base}/health")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


# ── Singleton ──────────────────────────────────────────────────────────

_client: HermesMCPClient | None = None


def get_mcp_client() -> HermesMCPClient:
    global _client
    if _client is None:
        _client = HermesMCPClient()
    return _client
