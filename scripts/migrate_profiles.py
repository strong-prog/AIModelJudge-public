#!/usr/bin/env python3
"""Migrate profile data from old format to new DB schema .

Old format: ~/.hermes-aimodeljudge/active_profile.json — {"profile": "aimodeljudge", ...}
New format: SQLite profiles table with user_id, models, tools, ha_enabled, etc.

This script:
1. Reads old active_profile.json (if exists)
2. For each user without a default profile, creates one
3. Verifies all users have at least one profile

Usage:
  python3 scripts/migrate_profiles.py
  python3 scripts/migrate_profiles.py --dry-run
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

_STATE_DB = Path.home() / ".hermes-aimodeljudge" / "state.db"
_OLD_PROFILE = Path.home() / ".hermes-aimodeljudge" / "active_profile.json"
_ENV = os.getenv("AMJ_ENV", "")

if _ENV:
    _STATE_DB = Path.home() / ".hermes-aimodeljudge" / _ENV / "state.db"


def _conn():
    c = sqlite3.connect(str(_STATE_DB))
    c.row_factory = sqlite3.Row
    return c


def read_old_profile() -> dict | None:
    """Read old active_profile.json if it exists."""
    if not _OLD_PROFILE.exists():
        return None
    try:
        return json.loads(_OLD_PROFILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def migrate(dry_run: bool = False) -> int:
    """Run migration. Returns number of profiles created."""
    old = read_old_profile()
    old_profile_name = old.get("profile", "default") if old else None

    conn = _conn()
    try:
        # Find users without any profile
        rows = conn.execute("""
            SELECT u.id, u.email FROM users u
            LEFT JOIN profiles p ON p.user_id = u.id
            WHERE p.id IS NULL
        """).fetchall()

        created = 0
        for row in rows:
            user_id = row["id"]
            email = row["email"]
            profile_id = f"prf_{uuid.uuid4().hex[:8]}"
            name = old_profile_name or "Мой первый профиль"
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

            if dry_run:
                print(f"[DRY RUN] Would create profile '{name}' ({profile_id}) for {email}")
                created += 1
                continue

            conn.execute("""
                INSERT INTO profiles (id, user_id, name, description, models, tools, ha_enabled, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (profile_id, user_id, name, "Default profile", "[]", "[]", 0, now, now))
            print(f"[OK] Created profile '{name}' ({profile_id}) for {email}")
            created += 1

        if dry_run:
            print(f"\n[DRY RUN] Would create {created} profiles")
        else:
            conn.commit()
            print(f"\n[DONE] Created {created} profiles")

        # Verify
        total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
        users_with_profiles = conn.execute(
            "SELECT COUNT(DISTINCT u.id) as cnt FROM users u JOIN profiles p ON p.user_id = u.id"
        ).fetchone()["cnt"]
        missing = total_users - users_with_profiles

        if missing > 0:
            print(f"[WARN] {missing} users still have no profiles")
        else:
            print(f"[OK] All {total_users} users have at least one profile")

        return created
    finally:
        conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(f"State DB: {_STATE_DB}")
    print(f"Old profile file: {'exists' if _OLD_PROFILE.exists() else 'not found'}")
    print()
    migrate(dry_run=dry)
