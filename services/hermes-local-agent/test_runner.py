"""Test runner for hermes-local-agent. Detects and runs project tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_tests(project_root: str, *, framework: str = "auto") -> dict:
    """Detect test framework and run tests. Returns {status, data, ...}."""
    root = Path(project_root)

    if framework == "auto":
        framework = _detect_framework(root)

    try:
        if framework == "pytest":
            result = subprocess.run(
                ["python3", "-m", "pytest", "-x", "--tb=short"],
                cwd=root, capture_output=True, text=True, timeout=120,
            )
        elif framework == "npm":
            result = subprocess.run(
                ["npm", "test", "--", "--passWithNoTests"],
                cwd=root, capture_output=True, text=True, timeout=120,
            )
        elif framework == "go":
            result = subprocess.run(
                ["go", "test", "./..."],
                cwd=root, capture_output=True, text=True, timeout=120,
            )
        else:
            return {"status": "error", "message": f"No test framework detected in {project_root}"}

        success = result.returncode == 0
        output = result.stdout + "\n" + result.stderr if result.stderr else result.stdout
        return {
            "status": "success" if success else "error",
            "data": output.strip()[:8000],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Tests timed out (120s)"}
    except FileNotFoundError as e:
        return {"status": "error", "message": f"Command not found: {e}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _detect_framework(root: Path) -> str:
    if (root / "conftest.py").exists() or (root / "tests").is_dir() or (root / "test").is_dir():
        return "pytest"
    if (root / "package.json").exists():
        return "npm"
    if (root / "go.mod").exists():
        return "go"
    return "none"
