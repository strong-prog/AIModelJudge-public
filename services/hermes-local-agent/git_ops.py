"""Git operations for hermes-local-agent."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(project_root: str, args: list[str], timeout: int = 30) -> dict:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr.strip() or "git command failed"}
        return {"status": "success", "data": result.stdout}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "git command timed out"}
    except FileNotFoundError:
        return {"status": "error", "message": "git not installed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def git_status(project_root: str) -> dict:
    return _run_git(project_root, ["status", "--short"])


def git_diff(project_root: str, *, staged: bool = False) -> dict:
    args = ["diff"]
    if staged:
        args.append("--staged")
    return _run_git(project_root, args)


def git_log(project_root: str, *, n: int = 10) -> dict:
    return _run_git(project_root, ["log", "--oneline", f"-n{n}"])


def git_show(project_root: str, ref: str = "HEAD") -> dict:
    return _run_git(project_root, ["show", ref])


def git_branch(project_root: str) -> dict:
    return _run_git(project_root, ["branch", "--list"])
