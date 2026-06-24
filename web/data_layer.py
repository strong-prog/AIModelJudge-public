"""Centralised data layer — all CRUD auto-filtered by user_id.

Replaces raw _state_conn / _kanban_conn calls scattered across routes.py.
Every function takes user_id as the first argument and scopes data
to that user. File-based data (skills, cron) lives under
~/.hermes-aimodeljudge/{env}/users/{user_id}/.

Admin override: pass admin_override=True to bypass user_id filters.
All admin accesses are logged to audit.jsonl.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

# ── Environment ────────────────────────────────────────────────────────────────
_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
    _CRON_DIR = Path.home() / ".hermes" / _ENV / "cron"
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"
    _CRON_DIR = Path.home() / ".hermes" / "cron"

# ── DB paths ───────────────────────────────────────────────────────────────────
_STATE_DB = _BASE / "state.db"
_KANBAN_DB = _BASE / "kanban.db"

# ── Audit log ──────────────────────────────────────────────────────────────────
_AUDIT_LOG = _BASE / "logs" / "audit.jsonl"


def _user_base(user_id: str) -> Path:
    return _BASE / "users" / user_id


def _state_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_STATE_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _kanban_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_KANBAN_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _log_admin_access(admin_user_id: str, action: str, detail: str, target_user_id: str = "") -> None:
    """Log admin access to audit trail."""
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": __import__('datetime').datetime.now(datetime_timezone_utc).isoformat(),
            "user_id": admin_user_id,
            "action": f"admin.{action}",
            "category": "admin_data_access",
            "detail": detail,
            "target_user_id": target_user_id,
        }
        with open(_AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# Import datetime.timezone for audit log
from datetime import timezone as datetime_timezone_utc


# ═══════════════════════════════════════════════════════════════════════════════
# Sessions
# ═══════════════════════════════════════════════════════════════════════════════

_VALID_SESSION_SOURCES = frozenset({"web", "telegram", "mcp", "api"})


def create_session(
    user_id: str,
    source: str = "web",
    model: str = "",
    title: str = "",
    system_prompt: str = "",
    model_config: str = "",
    cwd: str = "",
    parent_session_id: str | None = None,
) -> str:
    if source not in _VALID_SESSION_SOURCES:
        raise ValueError(f"source must be one of {_VALID_SESSION_SOURCES}")
    session_id = f"ses_{uuid.uuid4().hex[:12]}"
    now = time.time()
    conn = _state_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (id, source, user_id, model, title, system_prompt, "
            "model_config, cwd, parent_session_id, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, source, user_id, model, title, system_prompt,
             model_config, cwd, parent_session_id, now),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def list_sessions(user_id: str, limit: int = 20, offset: int = 0, admin_override: bool = False, admin_user_id: str = "") -> list[dict]:
    conn = _state_conn()
    try:
        if admin_override:
            rows = conn.execute(
                "SELECT id, source, model, user_id, started_at, message_count, title "
                "FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (min(limit, 50), offset),
            ).fetchall()
            _log_admin_access(admin_user_id, "list_sessions", f"limit={limit} offset={offset}")
        else:
            rows = conn.execute(
                "SELECT id, source, model, started_at, message_count, title "
                "FROM sessions WHERE user_id = ? "
                "ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (user_id, min(limit, 50), offset),
            ).fetchall()
        sessions = [dict(r) for r in rows]
        for s in sessions:
            msg = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                "ORDER BY timestamp LIMIT 1",
                (s["id"],),
            ).fetchone()
            s["preview"] = msg["content"] if msg else ""
    finally:
        conn.close()
    return sessions


def search_sessions(user_id: str, query: str, limit: int = 20, admin_override: bool = False, admin_user_id: str = "") -> list[dict]:
    if not query or not query.strip():
        return []
    conn = _state_conn()
    try:
        safe_q = query.replace('"', '""')
        if admin_override:
            rows = conn.execute(
                "SELECT DISTINCT s.id, s.source, s.model, s.started_at, s.message_count, s.title "
                "FROM messages_fts fts "
                "JOIN messages m ON fts.rowid = m.id "
                "JOIN sessions s ON m.session_id = s.id "
                "WHERE messages_fts MATCH ? "
                "ORDER BY s.started_at DESC LIMIT ?",
                (f'"{safe_q}"', min(limit, 50)),
            ).fetchall()
            _log_admin_access(admin_user_id, "search_sessions", f"q={query}")
        else:
            rows = conn.execute(
                "SELECT DISTINCT s.id, s.source, s.model, s.started_at, s.message_count, s.title "
                "FROM messages_fts fts "
                "JOIN messages m ON fts.rowid = m.id "
                "JOIN sessions s ON m.session_id = s.id "
                "WHERE messages_fts MATCH ? AND s.user_id = ? "
                "ORDER BY s.started_at DESC LIMIT ?",
                (f'"{safe_q}"', user_id, min(limit, 50)),
            ).fetchall()
        sessions: list[dict] = []
        seen: set[str] = set()
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            d = dict(r)
            msg = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                "ORDER BY timestamp LIMIT 1",
                (d["id"],),
            ).fetchone()
            d["preview"] = msg["content"] if msg else ""
            sessions.append(d)
    finally:
        conn.close()
    return sessions


def get_session(user_id: str, session_id: str, admin_override: bool = False, admin_user_id: str = "") -> dict | None:
    conn = _state_conn()
    try:
        if admin_override:
            session = conn.execute(
                "SELECT id, source, model, started_at, message_count, title "
                "FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            _log_admin_access(admin_user_id, "get_session", f"session={session_id}")
        else:
            session = conn.execute(
                "SELECT id, source, model, started_at, message_count, title "
                "FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        if not session:
            return None
        messages = conn.execute(
            "SELECT id, role, content, timestamp FROM messages "
            "WHERE session_id = ? AND active = 1 ORDER BY timestamp",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "session": dict(session),
        "messages": [dict(m) for m in messages],
    }


def update_session_title(user_id: str, session_id: str, title: str) -> bool:
    conn = _state_conn()
    try:
        cur = conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ? AND user_id = ?",
            (title, session_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def archive_session(user_id: str, session_id: str) -> bool:
    conn = _state_conn()
    try:
        cur = conn.execute(
            "UPDATE sessions SET archived = 1 WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Kanban
# ═══════════════════════════════════════════════════════════════════════════════

_VALID_KANBAN_STATUSES = frozenset({
    "backlog", "todo", "pending", "in_progress", "in-progress",
    "review", "done", "completed", "cancelled",
})


def list_tasks(user_id: str, status_filter: str = "") -> list[dict]:
    conn = _kanban_conn()
    try:
        if status_filter:
            rows = conn.execute(
                "SELECT id, title, body, assignee, status, priority, created_at, "
                "completed_at, result FROM tasks WHERE user_id = ? AND status = ? "
                "ORDER BY priority DESC, created_at DESC",
                (user_id, status_filter),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, body, assignee, status, priority, created_at, "
                "completed_at, result FROM tasks WHERE user_id = ? "
                "ORDER BY priority DESC, created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_task(
    user_id: str,
    title: str,
    body: str = "",
    status: str = "pending",
    priority: int = 0,
    assignee: str = "",
) -> str:
    if status not in _VALID_KANBAN_STATUSES:
        raise ValueError(f"status must be one of {_VALID_KANBAN_STATUSES}")
    task_id = str(uuid.uuid4())[:8]
    now = int(time.time())
    conn = _kanban_conn()
    try:
        conn.execute(
            "INSERT INTO tasks (id, title, body, status, priority, created_at, "
            "workspace_kind, user_id, assignee) VALUES (?, ?, ?, ?, ?, ?, 'scratch', ?, ?)",
            (task_id, title, body, status, priority, now, user_id, assignee),
        )
        conn.commit()
    finally:
        conn.close()
    return task_id


def update_task(user_id: str, task_id: str, **fields) -> bool:
    allowed = {"status", "title", "body", "priority", "assignee", "result"}
    updates: list[str] = []
    params: list = []
    for key in allowed:
        if key in fields:
            val = fields[key]
            if key == "status" and val not in _VALID_KANBAN_STATUSES:
                continue
            updates.append(f"{key} = ?")
            params.append(val)
    if not updates:
        return False
    if fields.get("status") == "completed":
        updates.append("completed_at = ?")
        params.append(int(time.time()))
    params.extend([task_id, user_id])
    conn = _kanban_conn()
    try:
        cur = conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_task(user_id: str, task_id: str) -> bool:
    conn = _kanban_conn()
    try:
        cur = conn.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Skills (file-based, per-user isolation)
# ═══════════════════════════════════════════════════════════════════════════════

def _skills_dir(user_id: str) -> Path:
    return _user_base(user_id) / "skills"


def list_skills(user_id: str) -> list[dict]:
    """List user-created skills from their personal directory."""
    base = _skills_dir(user_id)
    if not base.is_dir():
        return []
    skills: list[dict] = []
    for skill_dir in sorted(base.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        name = skill_dir.name
        # Extract frontmatter description
        desc = ""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().split("\n"):
                    line = line.strip()
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip('"')
                        break
        skills.append({
            "name": name,
            "description": desc,
            "path": str(skill_md),
            "source": "user",
        })
    return skills


def get_skill_content(user_id: str, skill_name: str) -> str | None:
    skill_md = _skills_dir(user_id) / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return None
    return skill_md.read_text(encoding="utf-8")


def create_skill(user_id: str, name: str, description: str, content: str, tools: list[str] | None = None) -> Path:
    skill_dir = _skills_dir(user_id) / name
    if skill_dir.is_dir():
        raise FileExistsError(f"Skill '{name}' already exists")
    skill_dir.mkdir(parents=True, exist_ok=False)

    frontmatter = f"---\nname: {name}\ndescription: {description}\n"
    if tools:
        frontmatter += f"tools: [{', '.join(tools)}]\n"
    frontmatter += "---\n\n"
    full = frontmatter + content

    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(full, encoding="utf-8")
    return skill_md


def delete_skill(user_id: str, skill_name: str) -> bool:
    skill_dir = _skills_dir(user_id) / skill_name
    if not skill_dir.is_dir():
        return False
    import shutil
    shutil.rmtree(skill_dir)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Cron (file-based, per-user isolation)
# ═══════════════════════════════════════════════════════════════════════════════

_CRON_LOCKS: dict[str, threading.Lock] = {}
_CRON_LOCK_GUARD = threading.Lock()


def _get_cron_lock(user_id: str) -> threading.Lock:
    with _CRON_LOCK_GUARD:
        if user_id not in _CRON_LOCKS:
            _CRON_LOCKS[user_id] = threading.Lock()
        return _CRON_LOCKS[user_id]


def _cron_file(user_id: str) -> Path:
    return _CRON_DIR / "users" / user_id / "jobs.json"


def _load_cron(user_id: str) -> dict:
    fp = _cron_file(user_id)
    if not fp.exists():
        return {"jobs": [], "updated_at": ""}
    return json.loads(fp.read_text(encoding="utf-8"))


def _save_cron(user_id: str, data: dict) -> None:
    fp = _cron_file(user_id)
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(fp) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(fp))
    fp.parent.chmod(0o700)
    fp.chmod(0o600)


def list_cron(user_id: str) -> list[dict]:
    with _get_cron_lock(user_id):
        data = _load_cron(user_id)
    jobs_out = []
    for j in data.get("jobs", []):
        jid = j.get("id", "")
        name = j.get("name") or j.get("prompt", "")[:50] or jid
        jobs_out.append({
            "id": jid,
            "name": name,
            "prompt": (j.get("prompt") or "")[:120],
            "schedule_display": j.get("schedule_display", ""),
            "state": j.get("state", "unknown"),
            "enabled": j.get("enabled", True),
            "skills": j.get("skills", []),
            "last_run": _cron_last_run(user_id, jid),
        })
    return jobs_out


def create_cron(user_id: str, name: str, prompt: str, schedule: str = "", schedule_display: str = "", skills: list | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    job = {
        "id": job_id,
        "name": name.strip(),
        "prompt": prompt.strip(),
        "schedule": schedule,
        "schedule_display": schedule_display or schedule,
        "state": "scheduled",
        "enabled": True,
        "skills": skills or [],
        "created_at": now_iso,
    }
    with _get_cron_lock(user_id):
        data = _load_cron(user_id)
        data.setdefault("jobs", []).append(job)
        data["updated_at"] = now_iso
        _save_cron(user_id, data)
    return job_id


def toggle_cron(user_id: str, job_id: str, pause: bool = True) -> bool:
    target_state = "paused" if pause else "scheduled"
    with _get_cron_lock(user_id):
        data = _load_cron(user_id)
        for j in data.get("jobs", []):
            if j.get("id") == job_id:
                j["state"] = target_state
                j["enabled"] = not pause
                data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
                _save_cron(user_id, data)
                return True
    return False


def delete_cron(user_id: str, job_id: str) -> bool:
    with _get_cron_lock(user_id):
        data = _load_cron(user_id)
        jobs = data.get("jobs", [])
        new_jobs = [j for j in jobs if j.get("id") != job_id]
        if len(new_jobs) == len(jobs):
            return False
        data["jobs"] = new_jobs
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        _save_cron(user_id, data)
    return True


def trigger_cron(user_id: str, job_id: str) -> bool:
    with _get_cron_lock(user_id):
        data = _load_cron(user_id)
        for j in data.get("jobs", []):
            if j.get("id") == job_id:
                j["state"] = "scheduled"
                j["enabled"] = True
                j["next_run"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
                data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
                _save_cron(user_id, data)
                return True
    return False


def count_cron(user_id: str) -> int:
    data = _load_cron(user_id)
    return len(data.get("jobs", []))


def _cron_last_run(user_id: str, job_id: str) -> dict | None:
    out_dir = _CRON_DIR / "users" / user_id / "output" / job_id
    if not out_dir.is_dir():
        return None
    files = sorted(out_dir.iterdir(), key=lambda p: p.name, reverse=True)
    if not files:
        return None
    f = files[0]
    return {"file": f.name, "at": f.name.replace(".md", "").replace("_", " ")}


# ═══════════════════════════════════════════════════════════════════════════════
# Profiles (Stage 11 v2: models, tools, ha_enabled, session count)
# ═══════════════════════════════════════════════════════════════════════════════

def create_profile(user_id: str, name: str, description: str = "",
                   models: list[str] | None = None, tools: list[str] | None = None,
                   ha_enabled: bool = False, is_default: bool = False) -> str:
    profile_id = f"prf_{uuid.uuid4().hex[:8]}"
    now = __import__('datetime').datetime.now().isoformat()
    conn = _state_conn()
    try:
        if is_default:
            conn.execute(
                "UPDATE profiles SET is_default = 0 WHERE user_id = ?", (user_id,)
            )
        conn.execute(
            "INSERT INTO profiles (id, user_id, name, description, models, tools, "
            "ha_enabled, is_default, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (profile_id, user_id, name, description,
             json.dumps(models or []), json.dumps(tools or []),
             1 if ha_enabled else 0, 1 if is_default else 0, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return profile_id


def list_profiles(user_id: str, admin_override: bool = False, admin_user_id: str = "") -> list[dict]:
    conn = _state_conn()
    try:
        if admin_override:
            rows = conn.execute(
                "SELECT p.id, p.name, p.description, p.user_id, p.is_default, "
                "p.models, p.tools, p.ha_enabled, p.created_at, p.updated_at, "
                "COUNT(s.id) as session_count "
                "FROM profiles p LEFT JOIN sessions s ON s.profile_id = p.id "
                "GROUP BY p.id ORDER BY p.is_default DESC, p.created_at DESC",
            ).fetchall()
            _log_admin_access(admin_user_id, "list_profiles", "all users")
        else:
            rows = conn.execute(
                "SELECT p.id, p.name, p.description, p.is_default, "
                "p.models, p.tools, p.ha_enabled, p.created_at, p.updated_at, "
                "COUNT(s.id) as session_count "
                "FROM profiles p LEFT JOIN sessions s ON s.profile_id = p.id "
                "WHERE p.user_id = ? "
                "GROUP BY p.id ORDER BY p.is_default DESC, p.created_at DESC",
                (user_id,),
            ).fetchall()
        profiles = []
        for r in rows:
            d = dict(r)
            for json_field in ("models", "tools"):
                try:
                    d[json_field] = json.loads(d[json_field]) if d[json_field] else []
                except (json.JSONDecodeError, TypeError):
                    d[json_field] = []
            profiles.append(d)
        return profiles
    finally:
        conn.close()


def get_profile(user_id: str, profile_id: str) -> dict | None:
    conn = _state_conn()
    try:
        row = conn.execute(
            "SELECT p.*, COUNT(s.id) as session_count "
            "FROM profiles p LEFT JOIN sessions s ON s.profile_id = p.id "
            "WHERE p.id = ? AND p.user_id = ? GROUP BY p.id",
            (profile_id, user_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for json_field in ("models", "tools"):
            try:
                d[json_field] = json.loads(d[json_field]) if d[json_field] else []
            except (json.JSONDecodeError, TypeError):
                d[json_field] = []
        return d
    finally:
        conn.close()


def update_profile(user_id: str, profile_id: str, **fields) -> bool:
    allowed = {"name", "description", "models", "tools", "ha_enabled", "is_default"}
    updates: list[str] = []
    params: list = []
    for key in allowed:
        if key in fields:
            val = fields[key]
            if key in ("models", "tools"):
                val = json.dumps(val if val is not None else [])
            if key == "is_default" and val:
                conn2 = _state_conn()
                try:
                    conn2.execute(
                        "UPDATE profiles SET is_default = 0 WHERE user_id = ?",
                        (user_id,),
                    )
                    conn2.commit()
                finally:
                    conn2.close()
            updates.append(f"{key} = ?")
            params.append(val)
    if not updates:
        return False
    updates.append("updated_at = ?")
    params.append(__import__('datetime').datetime.now().isoformat())
    params.extend([profile_id, user_id])
    conn = _state_conn()
    try:
        cur = conn.execute(
            f"UPDATE profiles SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_profile(user_id: str, profile_id: str) -> bool:
    """Delete profile. Cannot delete the only remaining profile (must keep at least one)."""
    conn = _state_conn()
    try:
        # Check count — must keep at least 1
        cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()["cnt"]
        if cnt <= 1:
            return False  # Cannot delete the only profile
        cur = conn.execute(
            "DELETE FROM profiles WHERE id = ? AND user_id = ? AND is_default = 0",
            (profile_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_default_profile(user_id: str, profile_id: str) -> bool:
    conn = _state_conn()
    try:
        conn.execute("UPDATE profiles SET is_default = 0 WHERE user_id = ?", (user_id,))
        cur = conn.execute(
            "UPDATE profiles SET is_default = 1, updated_at = ? WHERE id = ? AND user_id = ?",
            (__import__('datetime').datetime.now().isoformat(), profile_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def activate_profile(user_id: str, profile_id: str) -> bool:
    """Set a profile as the active/default one."""
    return set_default_profile(user_id, profile_id)


def get_profile_session_count(user_id: str, profile_id: str) -> int:
    conn = _state_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# GDPR — Cascade User Deletion
# ═══════════════════════════════════════════════════════════════════════════════


def _collect_user_data(user_id: str) -> dict:
    """Export all user data before deletion."""
    import shutil as _shutil
    data: dict = {"user_id": user_id, "exported_at": datetime_timezone_utc.now().isoformat()}

    conn = _state_conn()
    try:
        data["user"] = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() or {})
        data["subscriptions"] = [dict(r) for r in conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchall()]
        data["telegram_links"] = [dict(r) for r in conn.execute("SELECT * FROM telegram_links WHERE user_id = ?", (user_id,)).fetchall()]
        data["profiles"] = [dict(r) for r in conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchall()]
        data["sessions"] = [dict(r) for r in conn.execute("SELECT * FROM sessions WHERE user_id = ?", (user_id,)).fetchall()]
        data["api_usage"] = [dict(r) for r in conn.execute("SELECT * FROM api_usage_log WHERE user_id = ?", (user_id,)).fetchall()]
        data["monthly_counts"] = [dict(r) for r in conn.execute("SELECT * FROM monthly_request_counts WHERE user_id = ?", (user_id,)).fetchall()]
    finally:
        conn.close()

    kconn = _kanban_conn()
    try:
        data["kanban_tasks"] = [dict(r) for r in kconn.execute("SELECT * FROM tasks WHERE user_id = ?", (user_id,)).fetchall()]
    finally:
        kconn.close()

    return data


def delete_user_cascade(user_id: str) -> dict:
    """Full cascading user deletion with pre-delete export to JSON.

    Deletes from: AIModelJudge state.db, kanban.db,
    and file-based user directories (skills, cron, profile contexts).
    """
    stats: dict = {"deleted": False, "user_id": user_id}

    # ── 1. Export before deletion ──
    export_dir = _BASE / "deleted_users"
    export_dir.mkdir(parents=True, exist_ok=True)
    try:
        user_data = _collect_user_data(user_id)
        export_path = export_dir / f"{user_id}.json"
        with open(export_path, "w") as f:
            json.dump(user_data, f, default=str, indent=2, ensure_ascii=False)
        stats["export_path"] = str(export_path)
    except Exception:
        stats["export_path"] = None

    # ── 2. AIModelJudge state.db ──
    conn = _state_conn()
    try:
        tables = [
            ("profiles", "user_id"),
            ("sessions", "user_id"),
            ("subscriptions", "user_id"),
            ("telegram_links", "user_id"),
            ("api_usage_log", "user_id"),
            ("monthly_request_counts", "user_id"),
        ]
        rows_deleted = 0
        for table, col in tables:
            cur = conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (user_id,))
            rows_deleted += cur.rowcount
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        stats["state_db_rows"] = rows_deleted
    finally:
        conn.close()

    # ── 3. kanban.db ──
    kconn = _kanban_conn()
    try:
        cur = kconn.execute("DELETE FROM tasks WHERE user_id = ?", (user_id,))
        kconn.commit()
        stats["kanban_tasks"] = cur.rowcount
    finally:
        kconn.close()

    # ── 4. File-based data ──
    import shutil

    user_dir = _user_base(user_id)
    if user_dir.exists():
        try:
            shutil.rmtree(user_dir)
            stats["user_dir_removed"] = True
        except Exception:
            stats["user_dir_removed"] = False

    cron_dir = _CRON_DIR / "users" / user_id
    if cron_dir.exists():
        try:
            shutil.rmtree(cron_dir)
            stats["cron_dir_removed"] = True
        except Exception:
            stats["cron_dir_removed"] = False

    stats["deleted"] = True
    return stats
