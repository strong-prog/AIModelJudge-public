"""File operations for hermes-local-agent — read, write, edit, list, glob, grep."""

from __future__ import annotations

import glob as glob_mod
import os
import re
import subprocess
from pathlib import Path

from security import validate_scope


def read_file(project_root: str, path: str, *, offset: int = 0, limit: int = 2000) -> dict:
    """Read a file with optional offset/limit. Returns {status, content, ...}."""
    try:
        full = validate_scope(project_root, path)
        if not full.is_file():
            return {"status": "error", "message": f"Not a file: {path}"}
        lines = full.read_text().splitlines()
        total = len(lines)
        if offset:
            lines = lines[offset:]
        if limit:
            lines = lines[:limit]
        return {
            "status": "success",
            "data": "".join(f"{i+1}\t{l}\n" for i, l in enumerate(lines, offset)),
            "total_lines": total,
            "returned_lines": len(lines),
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def write_file(project_root: str, path: str, content: str) -> dict:
    """Write content to a file, creating parent directories."""
    try:
        full = validate_scope(project_root, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return {"status": "success", "data": f"Written {len(content)} bytes to {path}"}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def edit_file(project_root: str, path: str, old_string: str, new_string: str, *, replace_all: bool = False) -> dict:
    """Find and replace text in a file."""
    try:
        full = validate_scope(project_root, path)
        if not full.is_file():
            return {"status": "error", "message": f"File not found: {path}"}
        content = full.read_text()
        count = content.count(old_string)
        if count == 0:
            return {"status": "error", "message": f"String not found in {path}"}
        if not replace_all and count > 1:
            return {"status": "error", "message": f"Found {count} occurrences — use replace_all=true or be more specific"}
        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
        full.write_text(new_content)
        return {"status": "success", "data": f"Replaced {count if replace_all else 1} occurrence(s) in {path}"}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_dir(project_root: str, path: str = ".") -> dict:
    """List directory contents."""
    try:
        full = validate_scope(project_root, path)
        if not full.is_dir():
            return {"status": "error", "message": f"Not a directory: {path}"}
        entries = []
        for entry in sorted(full.iterdir()):
            etype = "dir" if entry.is_dir() else "file"
            size = entry.stat().st_size if entry.is_file() else 0
            entries.append(f"{etype}\t{entry.name}\t{size}")
        return {"status": "success", "data": "\n".join(entries)}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


def glob_files(project_root: str, pattern: str) -> dict:
    """Glob files matching a pattern."""
    try:
        root = Path(project_root).resolve()
        results = glob_mod.glob(pattern, root_dir=root, recursive=True)
        results = results[:100]  # cap
        return {"status": "success", "data": "\n".join(results)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def grep(project_root: str, pattern: str, *, path: str = ".", glob: str = "", output_mode: str = "content", limit: int = 50) -> dict:
    """Search content using ripgrep."""
    try:
        root = Path(project_root).resolve()
        cmd = ["rg", "--line-number", "--no-heading"]
        if glob:
            cmd.extend(["--glob", glob])
        cmd.extend(["--", pattern, str(root / path)])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=root)
        lines = result.stdout.splitlines()[:limit]
        return {"status": "success", "data": "\n".join(lines), "count": len(lines)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "grep timed out"}
    except FileNotFoundError:
        # ripgrep not installed — fallback to python search
        return _py_grep(project_root, pattern, path, limit)
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _py_grep(project_root: str, pattern: str, path: str, limit: int) -> dict:
    try:
        root = Path(project_root).resolve()
        pat = re.compile(pattern)
        results = []
        for f in (root / path).rglob("*"):
            if f.is_file() and f.suffix in (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".yaml", ".yml", ".toml", ".json", ".md", ".txt", ".cfg", ".ini"):
                try:
                    for i, line in enumerate(f.read_text().splitlines(), 1):
                        if pat.search(line):
                            results.append(f"{f.relative_to(root)}:{i}: {line[:200]}")
                            if len(results) >= limit:
                                return {"status": "success", "data": "\n".join(results)}
                except Exception:
                    pass
        return {"status": "success", "data": "\n".join(results)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
