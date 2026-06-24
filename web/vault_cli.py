"""Vault CLI — manage encrypted secrets.

Usage:
  PYTHONPATH=$PWD:$PWD/web python web/vault_cli.py set <name> <value>
  PYTHONPATH=$PWD:$PWD/web python web/vault_cli.py get <name>
  PYTHONPATH=$PWD:$PWD/web python web/vault_cli.py list
  PYTHONPATH=$PWD:$PWD/web python web/vault_cli.py delete <name>
  PYTHONPATH=$PWD:$PWD/web python web/vault_cli.py rotate-master-key
  PYTHONPATH=$PWD:$PWD/web python web/vault_cli.py import-from-env
"""

from __future__ import annotations

import os
import sys

# Ensure web/ is importable when run from project root
_web_dir = os.path.dirname(os.path.abspath(__file__))
if _web_dir not in sys.path:
    sys.path.insert(0, _web_dir)

from secrets_vault import get_secrets_vault

_ENV_VARS = [
    # AI Provider API keys
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "AMJ_SIDE_PROXY_KEY",
    # Core secrets
    "AMJ_AUDIT_SECRET",
    "AMJ_API_KEY",
    "AMJ_TELEGRAM_TOKEN",
]


def cmd_set(name: str, value: str) -> None:
    vault = get_secrets_vault()
    if not vault.is_unlocked():
        print("ERROR: Vault is locked. Set AMJ_MASTER_KEY to unlock.")
        sys.exit(1)
    if vault.set_secret(name, value):
        print(f"OK: '{name}' stored")
    else:
        print(f"ERROR: Failed to store '{name}'")
        sys.exit(1)


def cmd_get(name: str) -> None:
    vault = get_secrets_vault()
    if not vault.is_unlocked():
        print("ERROR: Vault is locked. Set AMJ_MASTER_KEY to unlock.")
        sys.exit(1)
    value = vault.get_secret(name)
    if value is None:
        print(f"NOT FOUND: '{name}'")
        sys.exit(1)
    print(value)


def cmd_list() -> None:
    vault = get_secrets_vault()
    if not vault.is_unlocked():
        print("ERROR: Vault is locked. Set AMJ_MASTER_KEY to unlock.")
        sys.exit(1)
    names = vault.list_secrets()
    if not names:
        print("(empty)")
        return
    for n in names:
        print(n)


def cmd_delete(name: str) -> None:
    vault = get_secrets_vault()
    if not vault.is_unlocked():
        print("ERROR: Vault is locked. Set AMJ_MASTER_KEY to unlock.")
        sys.exit(1)
    if vault.delete_secret(name):
        print(f"OK: '{name}' deleted")
    else:
        print(f"NOT FOUND: '{name}'")
        sys.exit(1)


def cmd_rotate_master_key() -> None:
    vault = get_secrets_vault()
    if not vault.is_unlocked():
        print("ERROR: Vault is locked. Set AMJ_MASTER_KEY to unlock.")
        sys.exit(1)
    if vault.rotate_master_key():
        print("OK: Master key rotated, all secrets re-encrypted")
    else:
        print("ERROR: Rotation failed")
        sys.exit(1)


def cmd_import_from_env() -> None:
    vault = get_secrets_vault()
    if not vault.is_unlocked():
        print("ERROR: Vault is locked. Set AMJ_MASTER_KEY to unlock.")
        sys.exit(1)
    imported = 0
    skipped = 0
    for var in _ENV_VARS:
        value = os.getenv(var, "")
        if value:
            if vault.set_secret(var, value):
                print(f"  imported: {var}")
                imported += 1
            else:
                print(f"  FAILED:   {var}")
        else:
            skipped += 1
    print(f"\nDone: {imported} imported, {skipped} skipped (empty), {len(_ENV_VARS)} total")


def print_usage() -> None:
    print(__doc__)


def main() -> None:
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "set":
        if len(sys.argv) != 4:
            print("Usage: vault_cli.py set <name> <value>")
            sys.exit(1)
        cmd_set(sys.argv[2], sys.argv[3])
    elif cmd == "get":
        if len(sys.argv) != 3:
            print("Usage: vault_cli.py get <name>")
            sys.exit(1)
        cmd_get(sys.argv[2])
    elif cmd == "list":
        cmd_list()
    elif cmd == "delete":
        if len(sys.argv) != 3:
            print("Usage: vault_cli.py delete <name>")
            sys.exit(1)
        cmd_delete(sys.argv[2])
    elif cmd == "rotate-master-key":
        cmd_rotate_master_key()
    elif cmd == "import-from-env":
        cmd_import_from_env()
    else:
        print(f"Unknown command: {cmd}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
