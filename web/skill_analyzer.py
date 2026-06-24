"""AIModelJudge — Skill Analyzer: автоматическое извлечение навыков из сессий.

Анализирует завершённые сессии в hermes state.db, проверяет критерии
skill-worthy сессии, генерирует SKILL.md кандидатов, сохраняет их
в ~/.hermes-aimodeljudge/skill_candidates.json для показа пользователю.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("aimodeljudge.skill_analyzer")

H_STATE_DB = Path.home() / ".hermes" / "state.db"
H_MEMORY_DB = Path.home() / ".memory-mcp" / "memory.db"
CANDIDATES_FILE = Path.home() / ".hermes-aimodeljudge" / "skill_candidates.json"

# Критерии skill-worthy сессии
MIN_TOOL_CALLS = 5
MIN_DURATION_SEC = 60


@dataclass
class SkillCandidate:
    session_id: str
    suggested_name: str
    description: str
    content: str
    tools_used: list[str]
    goal: str
    tool_sequence: list[str]
    result_summary: str
    confidence: float


def _state_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(H_STATE_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _memory_conn() -> sqlite3.Connection | None:
    if not H_MEMORY_DB.exists():
        return None
    conn = sqlite3.connect(str(H_MEMORY_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _extract_tool_name(text: str) -> str | None:
    m = re.search(r'"name"\s*:\s*"(\w+)"', text)
    if m:
        return m.group(1)
    m = re.search(r"'name'\s*:\s*'(\w+)'", text)
    if m:
        return m.group(1)
    return None


def extract_skill_candidate(session_id: str) -> SkillCandidate | None:
    """Анализирует сессию и возвращает кандидата навыка или None."""
    try:
        conn = _state_conn()
    except Exception:
        _log.debug("state.db недоступен для анализа сессии %s", session_id)
        return None

    try:
        row = conn.execute(
            "SELECT id, tool_call_count, end_reason, started_at, ended_at "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

        if not row:
            return None

        tool_count = row["tool_call_count"] or 0
        end_reason = row["end_reason"] or ""
        started = row["started_at"]
        ended = row["ended_at"]

        # Критерий 1: tool calls
        if tool_count < MIN_TOOL_CALLS:
            return None

        # Критерий 2: end_reason
        if end_reason in ("error", "blocked", "max_turns"):
            return None

        # Критерий 3: длительность > 60s
        duration_ok = False
        if started and ended:
            try:
                t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(ended.replace("Z", "+00:00"))
                duration_ok = (t1 - t0).total_seconds() > MIN_DURATION_SEC
            except (ValueError, TypeError):
                pass
        if not duration_ok:
            return None

        # Загружаем сообщения
        messages = conn.execute(
            "SELECT role, content, tool_calls, tool_results "
            "FROM messages WHERE session_id = ? AND active = 1 "
            "ORDER BY timestamp",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    if not messages:
        return None

    # Анализируем сообщения
    tool_names: list[str] = []
    tool_sequence: list[str] = []
    has_material_output = False
    has_blocked_tool = False
    goal = ""
    result_summary = ""

    # Инструменты из tool_calls поля (JSON строка)
    tool_calls_re = re.compile(r'"tool"\s*:\s*"(\w+)"')

    for msg in messages:
        role = msg["role"] or ""
        content = msg["content"] or ""
        tool_calls_raw = msg["tool_calls"] or ""
        tool_results_raw = msg["tool_results"] or ""

        # Цель = первое сообщение пользователя
        if role == "user" and not goal:
            goal = content[:200].strip()

        # Извлекаем tool calls
        if tool_calls_raw:
            try:
                tc_data = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
                tc_list = tc_data if isinstance(tc_data, list) else [tc_data]
                for tc in tc_list:
                    if isinstance(tc, dict):
                        tn = tc.get("tool") or tc.get("name") or tc.get("tool_name", "")
                    else:
                        tn = str(tc)
                    if tn and tn not in tool_sequence:
                        tool_sequence.append(tn)
                    if tn and tn not in tool_names:
                        tool_names.append(tn)
            except (json.JSONDecodeError, TypeError):
                for m in tool_calls_re.finditer(tool_calls_raw):
                    tn = m.group(1)
                    if tn not in tool_sequence:
                        tool_sequence.append(tn)
                    if tn not in tool_names:
                        tool_names.append(tn)

        # Проверка на блокировки
        if tool_results_raw:
            tr_lower = str(tool_results_raw).lower()
            if "блокирован" in tr_lower or "blocked" in tr_lower:
                has_blocked_tool = True

        # Проверка на материальный вывод
        if not has_material_output and tool_results_raw:
            tr_str = str(tool_results_raw)
            if any(kw in tr_str for kw in ("write_file", "edit_file", "write_to_file")):
                has_material_output = True

        # Результат = последнее сообщение ассистента с контентом
        if role == "assistant" and content.strip():
            result_summary = content.strip()[:500]

    # Критерий 4: материальный вывод
    if not has_material_output:
        return None

    # Критерий 5: нет заблокированных
    if has_blocked_tool:
        return None

    # Генерируем suggested_name
    suggested_name = _generate_skill_name(goal, tool_names)
    if not suggested_name:
        suggested_name = f"session-{session_id[:8]}"

    # Dedup-проверка
    if _is_duplicate(suggested_name):
        return None

    # Генерируем контент
    content = _generate_skill_content(goal, tool_names, tool_sequence, result_summary)
    description = f"Авто-извлечённый навык: {goal[:120]}"

    # Уверенность
    tool_diversity = len(set(tool_names))
    confidence = min(tool_diversity / 10, 1.0) * 0.5
    if duration_ok:
        confidence += 0.3
    if has_material_output:
        confidence += 0.2
    confidence = min(confidence, 1.0)

    return SkillCandidate(
        session_id=session_id,
        suggested_name=suggested_name,
        description=description,
        content=content,
        tools_used=list(set(tool_names)),
        goal=goal,
        tool_sequence=tool_sequence,
        result_summary=result_summary,
        confidence=round(confidence, 2),
    )


def _generate_skill_name(goal: str, tool_names: list[str]) -> str:
    """Генерирует kebab-case имя навыка из цели и инструментов."""
    # Простая эвристика: первые 3-5 значимых слов из цели
    words = re.findall(r"[a-zа-яё]+", goal.lower())[:5]
    if not words:
        # Fallback: используем имена инструментов
        words = [t.replace("_", "-") for t in tool_names[:3]]
        return "-".join(words)[:64] if words else ""

    # Транслитерация русских слов
    ru_map = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    latin_words = []
    for w in words:
        latin = "".join(ru_map.get(c, c) for c in w)
        latin = re.sub(r"[^a-z0-9-]", "", latin)
        if latin:
            latin_words.append(latin)

    name = "-".join(latin_words[:5])
    return re.sub(r"-+", "-", name)[:64].strip("-")


def _is_duplicate(suggested_name: str) -> bool:
    """Проверяет, существует ли уже похожий навык."""
    from web.skills_manager import SKILLS_DIR

    target = SKILLS_DIR / suggested_name / "SKILL.md"
    if target.exists():
        return True

    # Простая проверка на частичное совпадение имени
    if SKILLS_DIR.exists():
        existing = [d.name for d in SKILLS_DIR.iterdir() if d.is_dir()]
        name_parts = set(suggested_name.split("-"))
        for ex in existing:
            ex_parts = set(ex.split("-"))
            overlap = name_parts & ex_parts
            total = len(name_parts | ex_parts)
            if total > 0 and len(overlap) / total > 0.7:
                return True

    return False


def _generate_skill_content(
    goal: str, tool_names: list[str], tool_sequence: list[str], result: str
) -> str:
    lines = []
    if goal:
        lines.append(f"## Цель\n\n{goal}\n")

    if tool_names:
        lines.append("## Инструменты\n")
        for t in sorted(set(tool_names)):
            lines.append(f"- `{t}`")
        lines.append("")

    if tool_sequence:
        lines.append("## Последовательность действий\n")
        for i, t in enumerate(tool_sequence, 1):
            lines.append(f"{i}. `{t}`")
        lines.append("")

    if result:
        lines.append(f"## Результат\n\n{result}\n")

    return "\n".join(lines)


def _load_candidates() -> dict:
    if not CANDIDATES_FILE.exists():
        return {}
    try:
        return json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_candidates(data: dict) -> None:
    try:
        tmp = CANDIDATES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CANDIDATES_FILE)
    except OSError:
        _log.warning("Не удалось сохранить candidates.json", exc_info=True)


def save_candidate(candidate: SkillCandidate) -> None:
    data = _load_candidates()
    data[candidate.session_id] = {
        "session_id": candidate.session_id,
        "suggested_name": candidate.suggested_name,
        "description": candidate.description,
        "content": candidate.content,
        "tools_used": candidate.tools_used,
        "goal": candidate.goal,
        "tool_sequence": candidate.tool_sequence,
        "result_summary": candidate.result_summary,
        "confidence": candidate.confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_candidates(data)


def get_candidate(session_id: str) -> dict | None:
    data = _load_candidates()
    return data.get(session_id)


def remove_candidate(session_id: str) -> None:
    data = _load_candidates()
    data.pop(session_id, None)
    _save_candidates(data)


async def analyze_session(session_id: str) -> None:
    """Асинхронная обёртка: запускает анализ в фоне."""
    try:
        # Небольшая пауза — даём state.db записаться
        await asyncio.sleep(1)
        candidate = extract_skill_candidate(session_id)
        if candidate:
            save_candidate(candidate)
            _log.info("Найден кандидат навыка: %s (confidence=%.2f)",
                      candidate.suggested_name, candidate.confidence)
    except Exception:
        _log.debug("Ошибка анализа сессии %s", session_id, exc_info=True)
