"""Secrets Vault — encrypted at-rest storage for API keys, tokens, passwords.

Fernet (AES-128-CBC + HMAC-SHA256) encryption with SQLite backend.
Vault-first, env-fallback: resolved secrets are written to os.environ
so existing os.getenv() callers work unchanged.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

from cryptography.fernet import Fernet

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"

_VAULT_PATH = Path(os.getenv("AMJ_VAULT_PATH", str(_BASE / "vault.db")))
_MASTER_KEY_PATH = _BASE / "master.key"

logger = logging.getLogger("aimodeljudge.vault")


class SecretsVault:
    """Encrypted secrets storage (Fernet + SQLite).

    Singleton — use get_secrets_vault(). Never logs secret values.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._unlocked = False
        self._fernet: Fernet | None = None
        self._conn: sqlite3.Connection | None = None
        self._unlock()

    def _resolve_master_key(self) -> bytes | None:
        env_key = os.getenv("AMJ_MASTER_KEY", "")
        if env_key:
            return env_key.encode()

        if _MASTER_KEY_PATH.exists():
            try:
                return _MASTER_KEY_PATH.read_bytes()
            except OSError:
                pass

        new_key = Fernet.generate_key()
        try:
            _BASE.mkdir(parents=True, exist_ok=True)
            _MASTER_KEY_PATH.write_bytes(new_key)
            os.chmod(_MASTER_KEY_PATH, 0o600)
        except OSError:
            pass
        return new_key

    def _unlock(self) -> None:
        try:
            master_key = self._resolve_master_key()
            if master_key is None:
                logger.warning("Vault: no master key available, vault disabled")
                return

            self._fernet = Fernet(master_key)

            _BASE.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(_VAULT_PATH), check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS secrets ("
                "  name TEXT PRIMARY KEY,"
                "  value BLOB NOT NULL,"
                "  updated_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ")"
            )
            self._conn.commit()

            # Verify encryption works with a no-op probe
            probe = self._fernet.encrypt(b"vault-probe")
            self._fernet.decrypt(probe)

            self._unlocked = True
            try:
                os.chmod(_VAULT_PATH, 0o600)
            except OSError:
                pass
            logger.info("Vault unlocked (%d secrets)", self._count_secrets())
        except Exception as e:
            logger.warning(
                "Vault initialization failed: %s — vault disabled, falling back to env vars", e
            )
            self._unlocked = False

    def _count_secrets(self) -> int:
        try:
            return self._conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0]
        except Exception:
            return 0

    def is_unlocked(self) -> bool:
        return self._unlocked

    def get_secret(self, name: str) -> str | None:
        if not self._unlocked or self._fernet is None or self._conn is None:
            return None
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT value FROM secrets WHERE name = ?", (name,)
                ).fetchone()
                if row is None:
                    return None
                return self._fernet.decrypt(row[0]).decode("utf-8")
            except Exception:
                logger.error("Failed to decrypt secret '%s'", name)
                return None

    def set_secret(self, name: str, value: str) -> bool:
        if not self._unlocked or self._fernet is None or self._conn is None:
            logger.warning("Vault locked, cannot store secret '%s'", name)
            return False
        with self._lock:
            try:
                encrypted = self._fernet.encrypt(value.encode("utf-8"))
                self._conn.execute(
                    "INSERT OR REPLACE INTO secrets (name, value, updated_at) "
                    "VALUES (?, ?, datetime('now'))",
                    (name, encrypted),
                )
                self._conn.commit()
                logger.info("Secret '%s' stored in vault", name)
                return True
            except Exception as e:
                logger.error("Failed to store secret '%s': %s", name, e)
                return False

    def delete_secret(self, name: str) -> bool:
        if not self._unlocked or self._conn is None:
            return False
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM secrets WHERE name = ?", (name,))
                self._conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info("Secret '%s' deleted from vault", name)
                return deleted
            except Exception as e:
                logger.error("Failed to delete secret '%s': %s", name, e)
                return False

    def list_secrets(self) -> list[str]:
        if not self._unlocked or self._conn is None:
            return []
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT name FROM secrets ORDER BY name"
                ).fetchall()
                return [r[0] for r in rows]
            except Exception:
                return []

    def rotate_master_key(self, new_key_bytes: bytes | None = None) -> bool:
        if not self._unlocked or self._fernet is None or self._conn is None:
            logger.warning("Vault locked, cannot rotate master key")
            return False

        new_key = new_key_bytes or Fernet.generate_key()
        new_fernet = Fernet(new_key)

        with self._lock:
            try:
                rows = self._conn.execute("SELECT name, value FROM secrets").fetchall()

                if _MASTER_KEY_PATH.exists():
                    _MASTER_KEY_PATH.replace(_MASTER_KEY_PATH.with_suffix(".key.old"))

                for name, encrypted_value in rows:
                    plaintext = self._fernet.decrypt(encrypted_value)
                    new_encrypted = new_fernet.encrypt(plaintext)
                    self._conn.execute(
                        "UPDATE secrets SET value = ?, updated_at = datetime('now') "
                        "WHERE name = ?",
                        (new_encrypted, name),
                    )

                self._conn.commit()
                _MASTER_KEY_PATH.write_bytes(new_key)
                os.chmod(_MASTER_KEY_PATH, 0o600)

                self._fernet = new_fernet
                logger.info("Master key rotated (%d secrets re-encrypted)", len(rows))
                return True
            except Exception as e:
                logger.error("Master key rotation failed: %s", e)
                return False

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._unlocked = False

    def __repr__(self) -> str:
        return f"<SecretsVault unlocked={self._unlocked}>"


_vault: SecretsVault | None = None


def get_secrets_vault() -> SecretsVault:
    global _vault
    if _vault is None:
        _vault = SecretsVault()
    return _vault


def get_secret_or_env(name: str, env_var: str, default: str = "") -> str:
    """Resolve a secret: vault → env → default. Writes resolved value to os.environ."""
    vault = get_secrets_vault()
    value = vault.get_secret(name) if vault.is_unlocked() else None
    if value is not None:
        os.environ[env_var] = value
        return value
    return os.getenv(env_var, default)
