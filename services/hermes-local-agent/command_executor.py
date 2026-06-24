"""Command executor — dispatches tool calls to the right handler.

Routes tool names (matching AIModelJudge's TOOL_DEFINITIONS set)
to local handler functions. Handles bash/shell with security checks.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

from audit import log_action
from file_ops import read_file, write_file, edit_file, list_dir, glob_files, grep
from git_ops import git_status, git_diff, git_log, git_show, git_branch
from security import check_command, is_safe, needs_confirmation, validate_scope


def execute(tool: str, params: dict, *, project_root: str) -> dict:
    """Execute a tool call locally. Returns {status, data, message, needs_approval}."""
    start = time.time()
    result: dict

    try:
        if tool == "read_file":
            result = read_file(project_root, str(params.get("path", "")),
                               offset=params.get("offset", 0),
                               limit=params.get("limit", 2000))

        elif tool == "read_file_raw":
            result = read_file(project_root, str(params.get("path", "")),
                               offset=0, limit=999999)

        elif tool == "write_file":
            result = write_file(project_root, str(params.get("path", "")),
                                str(params.get("content", "")))

        elif tool == "edit_file":
            result = edit_file(project_root,
                               str(params.get("path", "")),
                               str(params.get("old_string", "")),
                               str(params.get("new_string", "")),
                               replace_all=bool(params.get("replace_all", False)))

        elif tool == "delete_file":
            path = validate_scope(project_root, str(params.get("path", "")))
            if path.is_file():
                path.unlink()
                result = {"status": "success", "data": f"Deleted {params['path']}"}
            else:
                result = {"status": "error", "message": f"File not found: {params.get('path')}"}

        elif tool == "list_dir":
            result = list_dir(project_root, str(params.get("path", ".")))

        elif tool == "glob":
            result = glob_files(project_root, str(params.get("pattern", "")))

        elif tool == "grep":
            result = grep(project_root, str(params.get("pattern", "")),
                          path=str(params.get("path", ".")),
                          glob=str(params.get("glob", "")),
                          limit=params.get("limit", 50))

        elif tool == "bash":
            cmd = str(params.get("command", params.get("cmd", "")))
            result = _run_bash(project_root, cmd)

        elif tool == "git_status":
            result = git_status(project_root)
        elif tool == "git_diff":
            result = git_diff(project_root, staged=bool(params.get("staged", False)))
        elif tool == "git_log":
            result = git_log(project_root, n=params.get("n", 10))
        elif tool == "git_show":
            result = git_show(project_root, ref=str(params.get("ref", "HEAD")))
        elif tool == "git_branch":
            result = git_branch(project_root)

        else:
            result = {"status": "error", "message": f"Unknown tool: {tool}"}

    except Exception as exc:
        result = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}

    duration_ms = (time.time() - start) * 1000
    status = result.get("status", "error")
    log_action(tool, params, status=status,
               data=result.get("data", ""),
               error=result.get("message", ""),
               duration_ms=duration_ms)

    # Attach approval info
    if status == "success" and needs_confirmation(tool):
        result["needs_approval"] = True

    return result


def _run_bash(project_root: str, command: str, timeout: int = 60) -> dict:
    """Execute a shell command within project scope."""
    # Security check
    error = check_command("bash", {"command": command})
    if error:
        return {"status": "error", "message": error}

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            return {
                "status": "error",
                "message": f"Exit code {result.returncode}",
                "data": output.strip() or "(no output)",
            }
        return {"status": "success", "data": output.strip()}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Command timed out ({timeout}s)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
