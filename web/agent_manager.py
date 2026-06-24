"""Agent Manager — manages local agent WebSocket connections.

Routes tool calls from agentic_stream → local agent and back.
Provides singleton access via get_agent_manager().
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

_log = logging.getLogger("aimodeljudge.agent_manager")

_EXECUTE_TIMEOUT_S = 60


class AgentManager:
    """Per-user WebSocket connection registry and tool-call router."""

    def __init__(self) -> None:
        self._connections: dict[str, Any] = {}  # user_id → WebSocket
        self._pending: dict[str, asyncio.Future] = {}  # cmd_id → Future[result]
        self._pending_user: dict[str, str] = {}  # cmd_id → user_id
        self._agent_info: dict[str, dict] = {}  # user_id → {version, project_root, connected_at}

    # ── Connection lifecycle ──────────────────────────────────────

    def register(self, user_id: str, ws: Any, *, project_root: str = "") -> None:
        """Register a new agent WebSocket for a user. Closes any prior connection."""
        old = self._connections.get(user_id)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self._connections[user_id] = ws
        self._agent_info[user_id] = {
            "version": "",
            "project_root": project_root,
            "connected_at": __import__("time").time(),
        }
        # Resolve any stale pending futures for this user
        stale_ids = [cid for cid, uid in list(self._pending_user.items()) if uid == user_id]
        for cid in stale_ids:
            fut = self._pending.pop(cid, None)
            if fut and not fut.done():
                fut.set_exception(ConnectionError("Agent reconnected — command cancelled"))
            self._pending_user.pop(cid, None)

    def unregister(self, user_id: str) -> None:
        """Remove agent connection. Resolve all pending futures with error."""
        ws = self._connections.pop(user_id, None)
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._agent_info.pop(user_id, None)
        # Fail all pending commands for this user
        stale_ids = [cid for cid, uid in list(self._pending_user.items()) if uid == user_id]
        for cid in stale_ids:
            fut = self._pending.pop(cid, None)
            if fut and not fut.done():
                fut.set_exception(ConnectionError("Agent disconnected"))
            self._pending_user.pop(cid, None)

    def is_connected(self, user_id: str) -> bool:
        ws = self._connections.get(user_id)
        if ws is None:
            return False
        try:
            # Check if the underlying starlette WS is still open
            # starlette sets client_state on close; check via private attr
            state = getattr(ws, "client_state", None)
            if state is not None and hasattr(state, "value"):
                return state.value != "disconnected"  # type: ignore[union-attr]
            return True  # can't introspect — assume alive
        except Exception:
            return False

    def get_agent_info(self, user_id: str) -> dict | None:
        return self._agent_info.get(user_id)

    # ── Tool execution ─────────────────────────────────────────────

    async def execute(self, user_id: str, tool: str, params: dict) -> dict:
        """Send a tool execution command to the agent and wait for result.

        Returns a dict with {"status": "success"|"error", "data": ..., "message": ...}
        """
        ws = self._connections.get(user_id)
        if ws is None:
            return {"status": "error", "message": "Agent not connected"}
        if not self.is_connected(user_id):
            self.unregister(user_id)
            return {"status": "error", "message": "Agent disconnected"}

        cmd_id = f"cmd_{uuid.uuid4().hex[:8]}"
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = fut
        self._pending_user[cmd_id] = user_id

        # Build the command message
        requires_approval = tool in _CONFIRM_TOOLS
        msg = {
            "type": "execute",
            "id": cmd_id,
            "tool": tool,
            "params": params,
            "requires_approval": requires_approval,
        }

        try:
            await ws.send_text(__import__("json").dumps(msg, ensure_ascii=False))
        except Exception:
            self._pending.pop(cmd_id, None)
            self._pending_user.pop(cmd_id, None)
            self.unregister(user_id)
            return {"status": "error", "message": "Failed to send command to agent"}

        try:
            result = await asyncio.wait_for(fut, timeout=_EXECUTE_TIMEOUT_S)
            return result
        except asyncio.TimeoutError:
            return {"status": "error", "message": f"Agent command timed out ({_EXECUTE_TIMEOUT_S}s)"}
        finally:
            self._pending.pop(cmd_id, None)
            self._pending_user.pop(cmd_id, None)

    def resolve_pending(self, user_id: str, cmd_id: str, *, success: bool, data: Any = None, error: str = "") -> None:
        """Called when agent sends a 'result' message."""
        fut = self._pending.get(cmd_id)
        if fut is None or fut.done():
            self._pending_user.pop(cmd_id, None)
            return
        expected_user = self._pending_user.get(cmd_id)
        if expected_user != user_id:
            return
        fut.set_result(
            {
                "status": "success" if success else "error",
                "data": data,
                "message": error,
            }
        )

    def pending_approval(self, user_id: str, cmd_id: str, tool: str, tool_input: dict) -> None:
        """Store an approval request from the agent for the chat SSE flow."""
        # Approval requests are surfaced through the pending registry;
        # the SSE chat loop picks them up when it sees the pending future
        # with a special 'approval_pending' marker
        pass

    def update_agent_status(self, user_id: str, *, version: str = "", project_root: str = "") -> None:
        info = self._agent_info.get(user_id)
        if info is not None:
            if version:
                info["version"] = version
            if project_root:
                info["project_root"] = project_root

    def close_all(self) -> None:
        """Close all agent connections. Called at server shutdown."""
        for user_id, ws in list(self._connections.items()):
            try:
                ws.close()
            except Exception:
                pass
        self._connections.clear()
        self._agent_info.clear()
        # Fail all pending
        for cid, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(ConnectionError("Server shutting down"))
        self._pending.clear()
        self._pending_user.clear()


# ── Tools that require user confirmation ──
_CONFIRM_TOOLS = frozenset({"write_file", "edit_file", "bash", "delete_file", "git_commit"})

# ── Singleton ──────────────────────────────────────────────────────

_agent_manager: AgentManager | None = None


def get_agent_manager() -> AgentManager:
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
    return _agent_manager


def has_agent_manager() -> bool:
    return _agent_manager is not None
