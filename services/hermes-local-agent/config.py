"""Configuration loader for hermes-local-agent."""

from __future__ import annotations

import json
import os
from pathlib import Path

_AGENT_HOME = Path.home() / ".hermes-agent"
_CONFIG_FILE = _AGENT_HOME / "config.json"


def get_agent_home() -> Path:
    os.makedirs(_AGENT_HOME, exist_ok=True)
    return _AGENT_HOME


def load_config() -> dict:
    """Load config from ~/.hermes-agent/config.json, env vars override."""
    config: dict = {
        "api_key": os.getenv("AMJ_API_KEY", ""),
        "server_url": os.getenv("AMJ_SERVER_URL", "ws://127.0.0.1:9651/agent/ws"),
        "project_root": os.getenv("AMJ_PROJECT_ROOT", str(Path.cwd())),
    }
    if _CONFIG_FILE.exists():
        try:
            file_config = json.loads(_CONFIG_FILE.read_text())
            for key in ("api_key", "server_url", "project_root"):
                if file_config.get(key) and not config.get(key):
                    config[key] = file_config[key]
        except Exception:
            pass
    return config


def save_config(config: dict) -> None:
    os.makedirs(_AGENT_HOME, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    _CONFIG_FILE.chmod(0o600)
