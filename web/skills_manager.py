"""AIModelJudge — Skill Manager: создание, метрики, рейтинг.

Создаёт SKILL.md с YAML-фронтматтером в ~/.hermes-aimodeljudge/skills/.
Ведёт skills.json со счётчиками вызовов и рейтингом.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("aimodeljudge.skills")

SKILLS_DIR = Path.home() / ".hermes-aimodeljudge" / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

METRICS_FILE = Path.home() / ".hermes-aimodeljudge" / "skills.json"

# Валидация имени навыка: kebab-case, латиница + цифры + дефисы
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

# Максимальные размеры
MAX_DESCRIPTION = 1024
MAX_CONTENT = 100_000


def _load_metrics() -> dict:
    """Загружает skills.json или возвращает пустой словарь."""
    if not METRICS_FILE.exists():
        return {}
    try:
        return json.loads(METRICS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_metrics(data: dict) -> None:
    """Сохраняет skills.json атомарно."""
    try:
        tmp = METRICS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(METRICS_FILE)
    except OSError:
        _log.warning("Не удалось сохранить skills.json", exc_info=True)


def get_metrics(path: str) -> dict:
    """Возвращает метрики для конкретного навыка."""
    metrics = _load_metrics()
    return metrics.get(path, {"call_count": 0, "upvotes": 0, "downvotes": 0})


def inc_call_count(path: str) -> None:
    """Увеличивает счётчик вызовов навыка."""
    metrics = _load_metrics()
    entry = metrics.get(path, {"call_count": 0, "upvotes": 0, "downvotes": 0})
    entry["call_count"] = entry.get("call_count", 0) + 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat()
    metrics[path] = entry
    _save_metrics(metrics)


def record_rating(path: str, rating: str) -> dict:
    """Записывает рейтинг навыка (up/down). Возвращает обновлённые метрики."""
    metrics = _load_metrics()
    entry = metrics.get(path, {"call_count": 0, "upvotes": 0, "downvotes": 0})
    if rating == "up":
        entry["upvotes"] = entry.get("upvotes", 0) + 1
    elif rating == "down":
        entry["downvotes"] = entry.get("downvotes", 0) + 1
    metrics[path] = entry
    _save_metrics(metrics)
    return entry


def validate_name(name: str) -> str | None:
    """Проверяет имя навыка. Возвращает сообщение об ошибке или None."""
    if not name or not name.strip():
        return "Имя навыка не может быть пустым"
    name = name.strip().lower()
    if not _NAME_RE.match(name):
        return "Имя должно быть в kebab-case: латиница, цифры, дефисы (напр. my-skill)"
    if len(name) > 64:
        return "Имя навыка не должно превышать 64 символа"
    # Проверка на конфликт с существующими
    target = SKILLS_DIR / name / "SKILL.md"
    if target.exists():
        return f"Навык «{name}» уже существует"
    return None


def build_frontmatter(name: str, description: str) -> str:
    """Генерирует YAML-фронтматтер для SKILL.md."""
    desc = description.replace('"', "'")[:MAX_DESCRIPTION]
    return (
        "---\n"
        f'name: {name}\n'
        f'description: "{desc}"\n'
        "version: 1.0.0\n"
        "author: Hermes Agent\n"
        "metadata:\n"
        "  hermes:\n"
        "    tags: [auto-generated]\n"
        "    related_skills: []\n"
        "---\n"
    )


def create(name: str, description: str, content: str = "", tools: list[str] | None = None) -> Path:
    """Создаёт новый навык.

    Args:
        name: Имя навыка в kebab-case.
        description: Краткое описание (до 1024 символов).
        content: Тело навыка в Markdown.
        tools: Список используемых инструментов (опционально).

    Returns:
        Path к созданному SKILL.md.

    Raises:
        ValueError: при невалидном имени.
        FileExistsError: если навык уже существует.
    """
    name = name.strip().lower()

    err = validate_name(name)
    if err:
        raise ValueError(err)

    skill_dir = SKILLS_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=False)

    frontmatter = build_frontmatter(name, description)
    tools_note = ""
    if tools:
        tools_note = "\n## Инструменты\n\n" + "\n".join(f"- `{t}`" for t in tools) + "\n"

    body = content[:MAX_CONTENT]
    title = name.replace("-", " ").title()

    skill_md = (
        f"{frontmatter}\n"
        f"# {title}\n\n"
        f"{body}\n"
        f"{tools_note}"
    )

    target = skill_dir / "SKILL.md"
    target.write_text(skill_md, encoding="utf-8")

    # Инициализируем метрики
    metrics = _load_metrics()
    metrics[str(target)] = {
        "call_count": 0,
        "upvotes": 0,
        "downvotes": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_metrics(metrics)

    _log.info("Создан навык %s → %s", name, target)
    return target


# ── SkillRanker: hot_score, auto-promotion ──

def _parse_date_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def calculate_hot_score(entry: dict) -> float:
    """Вычисляет hot_score для навыка по формуле:
    hot_score = freq*0.4 + quality*0.4 + recency*0.2
    """
    call_count = max(entry.get("call_count", 0), 0)
    upvotes = max(entry.get("upvotes", 0), 0)
    downvotes = max(entry.get("downvotes", 0), 0)
    last_used = entry.get("last_used")

    # freq: log scale, 0..1
    if call_count > 0:
        freq = min(math.log(call_count + 1) / math.log(100), 1.0)
    else:
        freq = 0.0

    # quality: 0..1
    total = upvotes + downvotes
    quality = upvotes / total if total > 0 else 0.0

    # recency: 0..1, decays over 30 days
    if last_used:
        last_dt = _parse_date_iso(last_used)
        if last_dt:
            days = (datetime.now(timezone.utc) - last_dt).days
            recency = max(0.0, 1.0 - days / 30.0)
        else:
            recency = 0.0
    else:
        recency = 0.0

    return round(freq * 0.4 + quality * 0.4 + recency * 0.2, 4)


@dataclass
class RankResult:
    path: str
    hot_score: float
    is_hot: bool
    call_count: int
    upvotes: int
    downvotes: int
    suggest_delete: bool


class SkillRanker:
    """Пересчитывает hot_score для всех навыков, управляет hot-кэшем."""

    HOT_THRESHOLD = 0.7
    DELETE_THRESHOLD = 0.2

    @staticmethod
    def rank_all() -> list[RankResult]:
        """Пересчитывает hot_score для всех навыков. Возвращает отсортированный список."""
        metrics = _load_metrics()
        results: list[RankResult] = []

        for path, entry in metrics.items():
            score = calculate_hot_score(entry)
            results.append(RankResult(
                path=path,
                hot_score=score,
                is_hot=score >= SkillRanker.HOT_THRESHOLD,
                call_count=entry.get("call_count", 0),
                upvotes=entry.get("upvotes", 0),
                downvotes=entry.get("downvotes", 0),
                suggest_delete=score < SkillRanker.DELETE_THRESHOLD,
            ))

        results.sort(key=lambda r: r.hot_score, reverse=True)

        # Сохраняем обновлённые hot_score обратно
        for r in results:
            if r.path in metrics:
                metrics[r.path]["hot_score"] = r.hot_score
                metrics[r.path]["is_hot"] = r.is_hot
        _save_metrics(metrics)

        return results

    @staticmethod
    def get_top_hot(limit: int = 5) -> list[dict]:
        """Возвращает топ-N горячих навыков для инжекции в промпт."""
        results = SkillRanker.rank_all()
        hot = [r for r in results if r.is_hot][:limit]
        output: list[dict] = []
        for r in hot:
            skill_file = Path(r.path)
            if skill_file.is_file():
                try:
                    content = skill_file.read_text(encoding="utf-8")
                except OSError:
                    content = ""
                name = skill_file.parent.name
                output.append({
                    "name": name,
                    "path": r.path,
                    "hot_score": r.hot_score,
                    "content": content[:2000],
                })
        return output
