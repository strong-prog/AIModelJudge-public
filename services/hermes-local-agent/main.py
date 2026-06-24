"""hermes-local-agent — main entry point.

Connects to AIModelJudge server via WebSocket and executes tool calls
on the developer's local machine.

Usage:
    hermes-local-agent --project-root /path/to/project
    hermes-local-agent --api-key amj_xxx --server-url ws://host:9651/agent/ws

Environment:
    AMJ_API_KEY           API key from AIModelJudge
    AMJ_SERVER_URL        WebSocket URL (default: ws://127.0.0.1:9651/agent/ws)
    AMJ_PROJECT_ROOT      Project directory (default: cwd)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

from config import load_config, save_config
from ws_client import AgentWSClient


def setup_logging() -> logging.Logger:
    log = logging.getLogger("hermes-agent")
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.handlers.clear()
    log.addHandler(handler)
    return log


async def main_async() -> None:
    log = setup_logging()

    parser = argparse.ArgumentParser(description="hermes-local-agent")
    parser.add_argument("--api-key", help="AIModelJudge API key")
    parser.add_argument("--server-url", help="WebSocket server URL")
    parser.add_argument("--project-root", help="Project root directory")
    parser.add_argument("--install", action="store_true",
                        help="Prompt for config and save to ~/.hermes-agent/")
    args = parser.parse_args()

    if args.install:
        return _interactive_install()

    config = load_config()
    api_key = args.api_key or config["api_key"]
    server_url = args.server_url or config["server_url"]
    project_root = args.project_root or config["project_root"]

    if not api_key:
        log.error("API key is required. Set AMJ_API_KEY env var or use --api-key")
        log.error("Run with --install to configure interactively")
        sys.exit(1)

    if not project_root:
        log.error("Project root is required. Use --project-root or cd to project")
        sys.exit(1)

    log.info("hermes-local-agent v0.1.0")
    log.info("Server: %s", server_url)
    log.info("Project: %s", project_root)

    client = AgentWSClient(server_url, api_key, project_root)

    # Handle SIGTERM/SIGINT
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, client.stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: client.stop())

    await client.connect()


def _interactive_install() -> None:
    """Interactive configuration setup."""
    print("hermes-local-agent — установка")
    print("=" * 40)
    api_key = input("API-ключ AIModelJudge: ").strip()
    server_url = input("URL сервера [ws://127.0.0.1:9651/agent/ws]: ").strip()
    if not server_url:
        server_url = "ws://127.0.0.1:9651/agent/ws"
    project_root = input(f"Корень проекта [{os.getcwd()}]: ").strip()
    if not project_root:
        project_root = os.getcwd()

    config = {
        "api_key": api_key,
        "server_url": server_url,
        "project_root": project_root,
    }
    save_config(config)
    print(f"Конфиг сохранён в ~/.hermes-agent/config.json")
    print("Запуск: hermes-local-agent")


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
