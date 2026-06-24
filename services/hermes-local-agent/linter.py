"""Linter integration for hermes-local-agent."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_linter(project_root: str, *, path: str = ".") -> dict:
    """Run appropriate linter based on project type."""
    root = Path(project_root)

    # Try Python
    target = root / path
    if list(target.rglob("*.py")) if target.is_dir() else target.suffix == ".py":
        try:
            result = subprocess.run(
                ["python3", "-m", "flake8", str(target), "--max-line-length=120"],
                cwd=root, capture_output=True, text=True, timeout=60,
            )
            return {"status": "success" if result.returncode == 0 else "warning",
                    "data": result.stdout.strip() or "No issues found"}
        except FileNotFoundError:
            pass

    # Try ESLint
    if (root / ".eslintrc.json").exists() or (root / ".eslintrc.js").exists():
        try:
            result = subprocess.run(
                ["npx", "eslint", str(target)],
                cwd=root, capture_output=True, text=True, timeout=60,
            )
            return {"status": "success" if result.returncode == 0 else "warning",
                    "data": result.stdout.strip() or "No issues found"}
        except FileNotFoundError:
            pass

    return {"status": "error", "message": "No linter found. Install flake8 or eslint."}
