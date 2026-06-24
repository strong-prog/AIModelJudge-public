"""WebSocket client for hermes-local-agent.

Connects to AIModelJudge server via WebSocket, authenticates with API key,
receives tool execution commands, sends results back.

Features:
- Exponential backoff reconnect (1s → 2s → 4s → ... → 60s max)
- Ping/pong heartbeat
- JSON wire protocol
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import traceback
from pathlib import Path

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from command_executor import execute
from security import needs_confirmation

_log = logging.getLogger("hermes-agent.ws")


class AgentWSClient:
    """Manages a single WebSocket connection to AIModelJudge."""

    def __init__(self, server_url: str, api_key: str, project_root: str) -> None:
        self._url = server_url
        self._api_key = api_key
        self._project_root = Path(project_root).resolve()
        self._should_run = True
        self._ws: ClientConnection | None = None

    async def connect(self) -> None:
        """Connect with exponential backoff reconnect."""
        delay = 1
        max_delay = 60

        while self._should_run:
            try:
                _log.info("Connecting to %s (project=%s)...", self._url, self._project_root)
                async with websockets.connect(
                    self._url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    _log.info("Connected")

                    # Auth
                    await ws.send(json.dumps({
                        "type": "auth",
                        "api_key": self._api_key,
                        "project_root": str(self._project_root),
                    }))
                    resp = json.loads(await ws.recv())

                    if resp.get("type") != "auth_ok":
                        _log.error("Auth failed: %s", resp)
                        await asyncio.sleep(5)
                        continue

                    _log.info("Authenticated as user=%s tier=%s",
                              resp.get("user_id"), resp.get("tier"))

                    # Send status
                    await ws.send(json.dumps({
                        "type": "status",
                        "version": "0.1.0",
                        "project_root": str(self._project_root),
                    }))

                    # Reset delay on successful connection
                    delay = 1

                    # Command loop
                    await self._command_loop(ws)

            except ConnectionClosed as e:
                _log.warning("Disconnected: %s", e)
            except asyncio.CancelledError:
                break
            except Exception:
                _log.warning("Connection error", exc_info=True)

            if not self._should_run:
                break

            _log.info("Reconnecting in %ds...", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

        _log.info("Client stopped")

    async def _command_loop(self, ws: ClientConnection) -> None:
        """Main loop: receive commands, execute, send results."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                _log.warning("Invalid JSON received")
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))
                continue

            if msg_type == "pong":
                continue

            if msg_type == "execute":
                cmd_id = msg["id"]
                tool = msg["tool"]
                params = msg.get("params", {})

                _log.info("Executing %s id=%s params=%s", tool, cmd_id,
                          str(params)[:120])

                # Check if needs approval
                if needs_confirmation(tool):
                    _log.info("Tool %s requires approval — requesting", tool)
                    await ws.send(json.dumps({
                        "type": "approval_required",
                        "id": cmd_id,
                        "tool": tool,
                        "params": params,
                    }))

                # Execute
                result = execute(tool, params, project_root=str(self._project_root))
                success = result.get("status") == "success"

                response = {
                    "type": "result",
                    "id": cmd_id,
                    "status": "success" if success else "error",
                    "data": result.get("data"),
                    "message": result.get("message", ""),
                    "needs_approval": result.get("needs_approval", False),
                }

                await ws.send(json.dumps(response, ensure_ascii=False))
                _log.info("Result id=%s status=%s", cmd_id,
                          "success" if success else "error")

            elif msg_type == "cancel":
                _log.info("Cancel received for id=%s", msg.get("id", "?"))

    def stop(self) -> None:
        self._should_run = False
