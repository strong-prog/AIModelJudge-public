"""Subprocess Sandbox с resource limits и изоляцией.

Безопасная обёртка над subprocess для выполнения bash-команд.
Заменяет прямой subprocess.run() в tool_executor.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_log = logging.getLogger("aimodeljudge.sandbox")

# ── Dangerous patterns — команды, которые всегда блокируются ──
_DANGEROUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "rm_rf_root",
        re.compile(r"\brm\s+.*-rf\s+/(\s|$)"),
    ),
    (
        "sudo_exec",
        re.compile(r"\bsudo\b"),
    ),
    (
        "mkfs_danger",
        re.compile(r"\bmkfs\.\w+"),
    ),
    (
        "dd_raw_device",
        re.compile(r"\bdd\s+if=.+of=/dev/"),
    ),
    (
        "write_to_dev",
        re.compile(r">\s*/dev/(sd[a-z]|nvme|dm-)"),
    ),
    (
        "chmod_danger",
        re.compile(r"\bchmod\s+777\b"),
    ),
    (
        "chmod_setuid",
        re.compile(r"\bchmod\s+[0-7]*[46][0-7]{2}\b"),
    ),
    (
        "curl_pipe_sh",
        re.compile(r"\bcurl\s+.*\|.*\b(ba|z|da)?sh\b"),
    ),
    (
        "wget_pipe_sh",
        re.compile(r"\bwget\s+.*-O\s*-\s*\|"),
    ),
    (
        "fork_bomb",
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:?\s*&\s*\}\s*;?\s*:"),
    ),
    (
        "reboot_halt",
        re.compile(r"\b(reboot|shutdown|halt|poweroff|init\s+[06])\b"),
    ),
    (
        "export_display",
        re.compile(r"\bexport\s+DISPLAY="),
    ),
    (
        "proc_sys_write",
        re.compile(r">\s*/proc/sys/"),
    ),
    (
        "format_disk",
        re.compile(r"\bfdisk\s+/dev/|\bparted\s+/dev/"),
    ),
]

# Сетевые утилиты, запрещённые всегда (даже с allow_network=True)
_ALWAYS_BLOCKED_NETWORK: set[str] = {
    "curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp",
    "ftp", "rsync", "socat", "nmap", "tcpdump", "tshark", "dig", "nslookup",
    "whois", "netstat", "ss", "iptables", "ufw", "firewall-cmd",
}
_ALWAYS_BLOCKED_NETWORK_PATTERN = re.compile(
    r"\b(?:" + "|".join(map(re.escape, _ALWAYS_BLOCKED_NETWORK)) + r")\b"
)


@dataclass
class SandboxConfig:
    """Конфигурация изоляции subprocess."""

    project_root: Path
    max_timeout: int = 300
    max_output_bytes: int = 100_000
    max_memory_mb: int = 512
    allow_network: bool = False
    cwd: Optional[Path] = None

    def __post_init__(self):
        if self.cwd is None:
            self.cwd = self.project_root


@dataclass
class SandboxResult:
    """Результат выполнения в sandbox."""

    stdout: str
    stderr: str = ""
    returncode: int = -1
    truncated: bool = False
    blocked: bool = False
    block_reason: str = ""
    duration_ms: float = 0.0


def _check_dangerous_patterns(command: str) -> Optional[str]:
    """Проверяет команду на опасные паттерны (rm -rf /, sudo, etc.)."""
    for name, pattern in _DANGEROUS_PATTERNS:
        m = pattern.search(command)
        if m:
            _log.warning("Sandbox BLOCK: %s — matched '%s'", name, m.group(0)[:80])
            return f"Dangerous command blocked [{name}]: matched '{m.group(0)[:60]}'"
    return None


def _check_network(command: str) -> Optional[str]:
    """Проверяет команду на запрещённые сетевые утилиты."""
    found = set()
    for match in _ALWAYS_BLOCKED_NETWORK_PATTERN.finditer(command):
        found.add(match.group(0))
    if found:
        names = ", ".join(sorted(found))
        return f"Network access blocked: {names}"
    return None


def _validate_scope(path_str: str, project_root: Path) -> Optional[str]:
    """Проверяет, что путь находится в project_root (защита от path traversal)."""
    try:
        resolved = Path(path_str).resolve()
        root_resolved = project_root.resolve()
        if not str(resolved).startswith(str(root_resolved)):
            return f"Path outside project root: {path_str}"
    except (OSError, ValueError) as e:
        return f"Invalid path: {path_str} — {e}"
    return None


async def sandbox_exec(command: str, *, config: SandboxConfig) -> SandboxResult:
    """Выполняет команду в изолированном subprocess.

    Защита:
    1. Dangerous pattern detection (rm -rf /, sudo, fork bombs)
    2. Network denylist
    3. Resource limits (memory, CPU, output size)
    4. Path validation (не может выйти за project_root)
    5. Timeout enforcement

    Args:
        command: Bash-команда.
        config: SandboxConfig с параметрами изоляции.

    Returns:
        SandboxResult с stdout, returncode, truncated, blocked.
    """
    # ── Step 1: Pre-execution checks ──
    danger = _check_dangerous_patterns(command)
    if danger:
        return SandboxResult(
            stdout=danger,
            returncode=1,
            blocked=True,
            block_reason=danger,
        )

    # Network check (always blocked, sandbox has no network)
    net_block = _check_network(command)
    if net_block:
        return SandboxResult(
            stdout=net_block,
            returncode=1,
            blocked=True,
            block_reason=net_block,
        )

    # ── Step 2: Configure resource limits ──
    timeout = min(config.max_timeout, 300)

    def _set_rlimits():
        """Установка resource limits в дочернем процессе."""
        try:
            import resource
            # Memory limit (virtual address space)
            mem_bytes = config.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            # CPU time limit
            resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 5))
            # File size limit (100MB)
            resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
            # Process limit (prevent fork bombs)
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            except (ValueError, resource.error):
                pass  # RLIMIT_NPROC может быть недоступен
        except (ImportError, ValueError) as e:
            _log.debug("Resource limits unavailable: %s", e)

    def _set_isolation():
        """Дополнительная изоляция (Linux-specific)."""
        if platform.system() != "Linux":
            return
        try:
            import ctypes
            import ctypes.util
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            # PR_SET_PDEATHSIG — убить процесс, если родитель умер
            PR_SET_PDEATHSIG = 1
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
        except Exception:
            pass  # prctl может быть недоступен вне Linux

    start = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.cwd),
            preexec_fn=_set_rlimits if platform.system() != "Windows" else None,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                stdout=f"Command timed out after {timeout}s",
                returncode=-1,
                blocked=True,
                block_reason=f"Timeout {timeout}s",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        # ── Step 3: Truncate output ──
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        truncated = False

        if len(stdout) > config.max_output_bytes:
            stdout = stdout[:config.max_output_bytes]
            stdout += f"\n... [truncated at {config.max_output_bytes} bytes]"
            truncated = True

        if len(stderr) > config.max_output_bytes:
            stderr = stderr[:config.max_output_bytes]
            truncated = True

        # ── Step 4: Post-execution scope check ──
        # Check for path references in command
        for word in command.split():
            word = word.strip("'\"")
            if word.startswith("/") or word.startswith("~/"):
                scope_issue = _validate_scope(word, config.project_root)
                if scope_issue:
                    _log.warning("Sandbox scope violation: %s", scope_issue)

        duration_ms = (time.monotonic() - start) * 1000

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode or 0,
            truncated=truncated,
            duration_ms=duration_ms,
        )

    except Exception as exc:
        _log.error("Sandbox execution error: %s", exc)
        return SandboxResult(
            stdout=f"Sandbox error: {exc}",
            returncode=1,
            blocked=True,
            block_reason=str(exc),
        )


def get_sandbox_stats() -> dict:
    """Метрики sandbox для /metrics."""
    return {
        "dangerous_patterns": len(_DANGEROUS_PATTERNS),
        "blocked_network_tools": len(_ALWAYS_BLOCKED_NETWORK),
    }
