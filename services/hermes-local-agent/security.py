"""Command whitelist and security checks for hermes-local-agent.

All file paths are validated against the project root (scope).
Shell commands are checked against allowed/confirm/block patterns.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# ── Commands allowed without confirmation ──
SAFE_COMMANDS = frozenset({
    "read_file", "read_file_raw", "list_dir",
    "glob", "grep", "search",
    "git_status", "git_diff", "git_log", "git_show", "git_branch",
})

# ── Commands that require user confirmation ──
CONFIRM_COMMANDS = frozenset({
    "write_file", "edit_file", "patch_replace",
    "bash", "shell",
    "git_commit", "git_add", "git_push",
    "run_test", "run_linter",
    "pip_install", "npm_install", "go_get",
    "delete_file", "move_file",
})

# ── Patterns that are ALWAYS blocked (even within confirmed commands) ──
BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f\s*|[^\s]*r.*f\s+)/"),
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"sudo\s"),
    re.compile(r"mkfs\."),
    re.compile(r"dd\s+if="),
    re.compile(r">\s*/dev/"),
    re.compile(r"chmod\s+777"),
    re.compile(r"curl\s+.*\|\s*(ba)?sh"),
    re.compile(r"wget\s+.*\|\s*(ba)?sh"),
    re.compile(r"/dev/null.*>/"),
    re.compile(r"fork\s+bomb|:\(\)\s*\{"),
    re.compile(r"chown\s+-R\s+/"),
]

# ── Network utilities blocked in shell ──
BLOCKED_NETWORK_COMMANDS = frozenset({
    "curl", "wget", "nc", "ncat", "netcat", "telnet",
    "ssh", "scp", "sftp", "ftp", "rsync", "socat",
    "nmap", "tcpdump", "tshark", "dig", "nslookup",
})


def validate_scope(project_root: str, target_path: str) -> Path:
    """Resolve path and ensure it stays within project_root. Raises ValueError."""
    root = Path(project_root).resolve()
    target = (root / target_path).resolve()
    if not str(target).startswith(str(root) + os.sep) and target != root:
        raise ValueError(f"Path '{target_path}' is outside project root '{root}'")
    return target


def check_command(tool: str, params: dict) -> str | None:
    """Check if a command is safe. Returns error message or None if allowed."""
    # Block dangerous shell patterns
    if tool == "bash":
        cmd = str(params.get("command", params.get("cmd", "")))
        for pattern in BLOCKED_PATTERNS:
            if pattern.search(cmd):
                return f"Blocked: dangerous pattern in command: {cmd[:80]}"
        # Check network commands
        for nc in BLOCKED_NETWORK_COMMANDS:
            if nc in cmd.split():
                return f"Blocked: network utility '{nc}' not allowed"
    return None


def needs_confirmation(tool: str) -> bool:
    """Return True if this tool requires user confirmation before execution."""
    return tool in CONFIRM_COMMANDS


def is_safe(tool: str) -> bool:
    """Return True if this tool is always safe (no confirmation needed)."""
    return tool in SAFE_COMMANDS
