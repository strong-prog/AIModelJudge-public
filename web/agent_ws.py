"""WebSocket endpoint for local hermes-agent connections.

Wire protocol
-------------
Newline-delimited JSON in both directions. Agent authenticates with
the same X-AMJ-API-Key used by the browser, then receives tool
execution commands and sends back results.

Mounting
--------
    @router.websocket("/agent/ws")
    async def agent_websocket(ws: WebSocket):
        await handle_agent_ws(ws)
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid

from starlette.websockets import WebSocket, WebSocketDisconnect

_log = logging.getLogger("aimodeljudge.agent_ws")

_PING_INTERVAL_S = 30
_PING_TIMEOUT_S = 10
_MAX_PAYLOAD_LEN = 200


async def handle_agent_ws(ws: WebSocket) -> None:
    """Accept one agent WebSocket connection, authenticate, then serve commands."""
    from agent_manager import get_agent_manager

    await ws.accept()
    peer = _ws_peer(ws)
    _disable_nagle(ws)

    user_id: str | None = None
    mgr = get_agent_manager()

    try:
        # ── Auth phase: agent must send API key as first message ──
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
            await ws.close(code=4000, reason="Invalid JSON")
            return

        if msg.get("type") != "auth" or "api_key" not in msg:
            await ws.send_text(json.dumps({"type": "error", "message": "auth required"}))
            await ws.close(code=4001, reason="auth required")
            return

        api_key = str(msg["api_key"]).strip()
        project_root = str(msg.get("project_root", "")).strip()
        try:
            from auth import _get_conn

            conn = _get_conn()
            try:
                row = conn.execute(
                    "SELECT id, email, tier, is_admin, banned FROM users WHERE api_key = ?",
                    (api_key,),
                ).fetchone()
                if not row:
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "Invalid API key"})
                    )
                    await ws.close(code=4002, reason="Invalid API key")
                    return
                if row["banned"]:
                    await ws.send_text(
                        json.dumps({"type": "error", "message": "Account banned"})
                    )
                    await ws.close(code=4003, reason="Account banned")
                    return
                user_id = row["id"]
                tier = row["tier"]
            finally:
                conn.close()
        except Exception as exc:
            _log.warning("Auth lookup failed: %s", exc)
            await ws.send_text(json.dumps({"type": "error", "message": "Auth failed"}))
            await ws.close(code=4004, reason="Auth failed")
            return

        # ── Register connection ──
        mgr.register(user_id, ws, project_root=project_root)
        await ws.send_text(
            json.dumps(
                {
                    "type": "auth_ok",
                    "user_id": user_id,
                    "tier": tier,
                }
            )
        )

        _log.info(
            "Agent connected user=%s peer=%s project=%s",
            user_id,
            peer,
            project_root or "(none)",
        )

        # ── Command loop ──
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=_PING_INTERVAL_S + _PING_TIMEOUT_S)
            except asyncio.TimeoutError:
                # Send ping to check connection
                try:
                    await asyncio.wait_for(
                        ws.send_text(json.dumps({"type": "ping"})),
                        timeout=_PING_TIMEOUT_S,
                    )
                    continue
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                _log.warning("Agent sent invalid JSON user=%s", user_id)
                continue

            msg_type = msg.get("type", "")

            if msg_type == "result":
                cmd_id = msg.get("id", "")
                status = msg.get("status", "error")
                data = msg.get("data")
                error_msg = msg.get("message", "")
                mgr.resolve_pending(
                    user_id,
                    cmd_id,
                    success=(status == "success"),
                    data=data,
                    error=error_msg,
                )

            elif msg_type == "approval_required":
                # Agent requests user approval before executing
                cmd_id = msg.get("id", "")
                tool = msg.get("tool", "")
                tool_input = msg.get("params", {})
                _log.info(
                    "Agent approval required user=%s tool=%s id=%s",
                    user_id,
                    tool,
                    cmd_id,
                )
                # Store for the chat SSE flow to pick up via agent_manager
                mgr.pending_approval(user_id, cmd_id, tool, tool_input)

            elif msg_type == "pong":
                pass  # heartbeat response

            elif msg_type == "status":
                mgr.update_agent_status(
                    user_id,
                    version=msg.get("version", ""),
                    project_root=msg.get("project_root", project_root),
                )

    except WebSocketDisconnect:
        _log.info("Agent disconnected user=%s peer=%s", user_id, peer)
    except Exception:
        _log.warning("Agent connection error user=%s", user_id, exc_info=True)
    finally:
        if user_id:
            mgr.unregister(user_id)
            _log.info("Agent unregistered user=%s", user_id)


def _ws_peer(ws: WebSocket) -> str:
    client = getattr(ws, "client", None)
    if client is None:
        return "unknown"
    host = getattr(client, "host", None) or "unknown"
    port = getattr(client, "port", None)
    return f"{host}:{port}" if port is not None else host


def _disable_nagle(ws: WebSocket) -> None:
    try:
        scope = getattr(ws, "scope", None) or {}
        transport = (scope.get("extensions") or {}).get("transport") or getattr(ws, "transport", None)
        sock = transport.get_extra_info("socket") if transport is not None else None
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:
        pass
