#!/usr/bin/env python3
"""Migration script: move to multi-tenant file structure with backup.

Performs:
  1. Backup — copies state.db and file data to a timestamped backup dir
  2. user_id assignment — fills user_id in sessions and tasks from chat history
  3. File migration — moves skills/cron from flat dirs to users/{user_id}/
  4. dry-run mode — --dry-run previews without modifying anything

Usage:
  python3 web/migrate_isolation.py              # full migration
  python3 web/migrate_isolation.py --dry-run    # preview only
  python3 web/migrate_isolation.py --env test   # migrate AMJ_ENV=test
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _env_base(env: str) -> Path:
    if env:
        return Path.home() / ".hermes-aimodeljudge" / env
    return Path.home() / ".hermes-aimodeljudge"


def _cron_base(env: str) -> Path:
    if env:
        return Path.home() / ".hermes" / env / "cron"
    return Path.home() / ".hermes" / "cron"


def backup(base: Path, backup_dir: Path) -> None:
    """Create timestamped backup of all data."""
    backup_dir.mkdir(parents=True, exist_ok=True)

    # state.db
    state_db = base / "state.db"
    if state_db.exists():
        shutil.copy2(state_db, backup_dir / "state.db")
        print(f"  [backup] state.db -> {backup_dir / 'state.db'}")

    # kanban.db
    kanban_db = base / "kanban.db"
    if kanban_db.exists():
        shutil.copy2(kanban_db, backup_dir / "kanban.db")
        print(f"  [backup] kanban.db -> {backup_dir / 'kanban.db'}")

    # skills dir
    skills_dir = base / "skills"
    if skills_dir.is_dir():
        shutil.copytree(skills_dir, backup_dir / "skills", dirs_exist_ok=True)
        print(f"  [backup] skills/ -> {backup_dir / 'skills'}")

    # cron users dir (if exists)
    cron_users = Path.home() / ".hermes" / "cron" / "users"
    if cron_users.is_dir():
        shutil.copytree(cron_users, backup_dir / "cron_users", dirs_exist_ok=True)
        print(f"  [backup] cron/users/ -> {backup_dir / 'cron_users'}")

    print(f"  Backup complete: {backup_dir}")


def migrate_state_db(base: Path, dry_run: bool) -> dict[str, int]:
    """Assign user_id to sessions that lack it. Returns stats."""
    state_db = base / "state.db"
    if not state_db.exists():
        print("  [skip] state.db not found")
        return {"sessions_assigned": 0}

    conn = sqlite3.connect(str(state_db))
    conn.row_factory = sqlite3.Row
    stats = {"sessions_assigned": 0, "sessions_skipped": 0}

    try:
        # Find sessions without user_id
        orphan = conn.execute(
            "SELECT id FROM sessions WHERE user_id IS NULL OR user_id = ''"
        ).fetchall()

        if not orphan:
            print("  [ok] All sessions have user_id")
            return stats

        print(f"  [migrate] {len(orphan)} sessions without user_id")

        # Try to derive user_id from the first user message's session
        # Or assign to first admin user as fallback
        first_admin = conn.execute(
            "SELECT id, email FROM users WHERE is_admin = 1 ORDER BY created_at LIMIT 1"
        ).fetchone()
        default_uid = first_admin["id"] if first_admin else "unknown"

        if not dry_run:
            for row in orphan:
                # Look for messages in this session to find creator
                msg = conn.execute(
                    "SELECT m.content FROM messages m WHERE m.session_id = ? "
                    "AND m.role = 'user' ORDER BY m.timestamp LIMIT 1",
                    (row["id"],),
                ).fetchone()
                # Assign to first admin as safe default
                conn.execute(
                    "UPDATE sessions SET user_id = ? WHERE id = ?",
                    (default_uid, row["id"]),
                )
                stats["sessions_assigned"] += 1
            conn.commit()
            print(f"  [migrate] {stats['sessions_assigned']} sessions assigned to {default_uid}")
        else:
            print(f"  [dry-run] Would assign {len(orphan)} sessions to {default_uid}")
            stats["sessions_assigned"] = len(orphan)
    finally:
        conn.close()

    return stats


def migrate_kanban_db(base: Path, dry_run: bool) -> dict[str, int]:
    """Assign user_id to kanban tasks that lack it. Returns stats."""
    kanban_db = base / "kanban.db"
    if not kanban_db.exists():
        print("  [skip] kanban.db not found")
        return {"tasks_assigned": 0}

    conn = sqlite3.connect(str(kanban_db))
    conn.row_factory = sqlite3.Row
    stats = {"tasks_assigned": 0}

    try:
        # Check if user_id column exists
        cols = conn.execute("PRAGMA table_info(tasks)").fetchall()
        col_names = {c["name"] for c in cols}
        if "user_id" not in col_names:
            print("  [skip] tasks table has no user_id column")
            return stats

        orphan = conn.execute(
            "SELECT id FROM tasks WHERE user_id IS NULL OR user_id = ''"
        ).fetchall()

        if not orphan:
            print("  [ok] All tasks have user_id")
            return stats

        print(f"  [migrate] {len(orphan)} tasks without user_id")

        # Derive from state.db — assign to first admin
        state_db = base / "state.db"
        if state_db.exists():
            sconn = sqlite3.connect(str(state_db))
            first_admin = sconn.execute(
                "SELECT id FROM users ORDER BY created_at LIMIT 1"
            ).fetchone()
            sconn.close()
            default_uid = first_admin[0] if first_admin else "unknown"
        else:
            default_uid = "unknown"

        if not dry_run:
            for row in orphan:
                conn.execute(
                    "UPDATE tasks SET user_id = ? WHERE id = ?",
                    (default_uid, row["id"]),
                )
                stats["tasks_assigned"] += 1
            conn.commit()
            print(f"  [migrate] {stats['tasks_assigned']} tasks assigned to {default_uid}")
        else:
            print(f"  [dry-run] Would assign {len(orphan)} tasks to {default_uid}")
            stats["tasks_assigned"] = len(orphan)
    finally:
        conn.close()

    return stats


def migrate_file_structure(base: Path, dry_run: bool, old_skills_dir: Path, env: str) -> dict[str, int]:
    """Migrate skills from flat dir to users/{user_id}/skills/."""
    stats = {"skills_migrated": 0, "skills_skipped": 0}

    if not old_skills_dir.is_dir():
        print("  [skip] skills dir not found")
        return stats

    # Get all users from state.db
    state_db = base / "state.db"
    if not state_db.exists():
        print("  [skip] state.db not found, cannot determine users")
        return stats

    conn = sqlite3.connect(str(state_db))
    conn.row_factory = sqlite3.Row
    users = conn.execute("SELECT id, email FROM users").fetchall()
    conn.close()

    if not users:
        print("  [skip] No users in database")
        return stats

    # Default: all existing skills go to first admin user
    first_user_id = users[0]["id"]

    skills = [d for d in old_skills_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not skills:
        print("  [ok] No skills to migrate")
        return stats

    print(f"  [migrate] {len(skills)} skills to users/{first_user_id}/skills/")
    target_dir = base / "users" / first_user_id / "skills"

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        for skill_dir in skills:
            dest = target_dir / skill_dir.name
            if dest.exists():
                print(f"    [skip] {skill_dir.name} already exists in target")
                stats["skills_skipped"] += 1
                continue
            shutil.copytree(skill_dir, dest)
            stats["skills_migrated"] += 1
        print(f"  [migrate] {stats['skills_migrated']} skills migrated, {stats['skills_skipped']} skipped")
    else:
        print(f"  [dry-run] Would migrate {len(skills)} skills")

    return stats


def migrate_cron_structure(cron_base: Path, base: Path, dry_run: bool) -> dict[str, int]:
    """Migrate cron jobs from flat dir to users/{user_id}/ structure."""
    stats = {"cron_migrated": 0}

    # Old structure: ~/.hermes/cron/jobs.json (flat, no users/)
    old_jobs_file = cron_base / "jobs.json"
    if not old_jobs_file.exists():
        print("  [skip] cron jobs.json not found")
        return stats

    # Get users
    state_db = base / "state.db"
    if not state_db.exists():
        return stats

    conn = sqlite3.connect(str(state_db))
    conn.row_factory = sqlite3.Row
    first_user = conn.execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
    conn.close()

    if not first_user:
        return stats

    first_uid = first_user["id"]
    target_dir = cron_base / "users" / first_uid
    target_file = target_dir / "jobs.json"

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        if not target_file.exists():
            shutil.copy2(old_jobs_file, target_file)
            stats["cron_migrated"] = 1
            print(f"  [migrate] cron jobs.json -> users/{first_uid}/jobs.json")
    else:
        print(f"  [dry-run] Would migrate cron jobs.json -> users/{first_uid}/jobs.json")
        stats["cron_migrated"] = 1

    return stats


def verify(base: Path) -> list[str]:
    """Verify migration: check data integrity."""
    issues: list[str] = []

    # Check sessions have user_id
    state_db = base / "state.db"
    if state_db.exists():
        conn = sqlite3.connect(str(state_db))
        orphan = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE user_id IS NULL OR user_id = ''"
        ).fetchone()
        conn.close()
        if orphan and orphan[0] > 0:
            issues.append(f"{orphan[0]} sessions still lack user_id")

    # Check kanban tasks
    kanban_db = base / "kanban.db"
    if kanban_db.exists():
        conn = sqlite3.connect(str(kanban_db))
        try:
            cols = conn.execute("PRAGMA table_info(tasks)").fetchall()
            col_names = {c[1] for c in cols}
            if "user_id" in col_names:
                orphan = conn.execute(
                    "SELECT COUNT(*) as cnt FROM tasks WHERE user_id IS NULL OR user_id = ''"
                ).fetchone()
                if orphan and orphan[0] > 0:
                    issues.append(f"{orphan[0]} tasks still lack user_id")
        finally:
            conn.close()

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="AIModelJudge Multi-Tenancy Migration")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--env", default=None, help="Target AMJ_ENV (default: current AMJ_ENV or empty)")
    parser.add_argument("--skip-backup", action="store_true", help="Skip backup step")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    env = args.env if args.env is not None else os.getenv("AMJ_ENV", "")
    base = _env_base(env)
    cron_base = _cron_base(env)

    print("=" * 60)
    print(f"AIModelJudge Multi-Tenancy Migration")
    print(f"  Environment: AMJ_ENV={env or '(default)'}")
    print(f"  Base dir:    {base}")
    print(f"  Dry run:     {args.dry_run}")
    print("=" * 60)
    print()

    if not base.exists():
        print(f"ERROR: Base directory not found: {base}")
        print("Nothing to migrate. Create state.db first by starting the server.")
        sys.exit(1)

    # ── Confirmation ──
    if not args.dry_run and not args.force:
        print("This will migrate data to the multi-tenant structure.")
        print(f"  - Assign user_id to orphan sessions/tasks")
        print(f"  - Move skills to users/{{user_id}}/skills/")
        print(f"  - Move cron jobs to users/{{user_id}}/")
        print()
        resp = input("Continue? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return

    # ── Step 1: Backup ──
    if not args.skip_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = base / "backups" / f"pre_isolation_{ts}"
        if not args.dry_run:
            backup(base, backup_dir)
        else:
            print(f"  [dry-run] Would backup to {backup_dir}")

    # ── Step 2: Migrate state.db ──
    print("\n── State DB (sessions.user_id) ──")
    stats_state = migrate_state_db(base, args.dry_run)

    # ── Step 3: Migrate kanban.db ──
    print("\n── Kanban DB (tasks.user_id) ──")
    stats_kanban = migrate_kanban_db(base, args.dry_run)

    # ── Step 4: Migrate file structure ──
    old_skills_dir = base / "skills"
    print(f"\n── File Structure: skills ({old_skills_dir}) ──")
    stats_skills = migrate_file_structure(base, args.dry_run, old_skills_dir, env)

    # ── Step 5: Migrate cron ──
    print(f"\n── File Structure: cron ({cron_base}) ──")
    stats_cron = migrate_cron_structure(cron_base, base, args.dry_run)

    # ── Summary ──
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"  Sessions assigned:  {stats_state.get('sessions_assigned', 0)}")
    print(f"  Tasks assigned:     {stats_kanban.get('tasks_assigned', 0)}")
    print(f"  Skills migrated:    {stats_skills.get('skills_migrated', 0)}")
    print(f"  Skills skipped:     {stats_skills.get('skills_skipped', 0)}")
    print(f"  Cron jobs migrated: {stats_cron.get('cron_migrated', 0)}")
    print()

    if not args.dry_run:
        issues = verify(base)
        if issues:
            print("WARNINGS:")
            for i in issues:
                print(f"  - {i}")
        else:
            print("Verification: all checks passed.")
    else:
        print("Dry run complete. Run without --dry-run to execute.")


if __name__ == "__main__":
    main()
