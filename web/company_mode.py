"""Company Mode — hub-and-spoke specialist orchestration.

Specialists (Маркетолог, Юрист, Бухгалтер, DevOps) are isolated agents
that consult with the Architect who synthesises ONE answer.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_SPECIALISTS_ROOT = Path(__file__).resolve().parent.parent / "specialists"

SPECIALIST_ROLES = frozenset({"marketer", "lawyer", "accountant", "devops"})

# Tool restrictions per specialist role (all are read-only consultants)
_READ_ONLY_DENYLIST = frozenset({"edit_file", "write_file", "bash", "shell", "execute"})


@dataclass(slots=True)
class SpecialistConfig:
    name: str              # marketer, lawyer, accountant, devops
    role: str              # Chief Marketing Officer, Corporate Lawyer, ...
    folder: Path           # specialists/{name}/
    briefing: str          # BRIEFING.md content
    readme: str            # README.md content
    system_prompt: str     # assembled from briefing + readme
    tools_denylist: frozenset = _READ_ONLY_DENYLIST
    max_rounds: int = 10   # 10 standard / 30 deep / 90 research

    @property
    def display_name(self) -> str:
        _names = {
            "marketer": "Маркетолог",
            "lawyer": "Юрист",
            "accountant": "Бухгалтер",
            "devops": "DevOps",
        }
        return _names.get(self.name, self.name)


def load_specialist_context(name: str) -> SpecialistConfig:
    """Загружает контекст специалиста из папки specialists/{name}/."""
    if name not in SPECIALIST_ROLES:
        raise ValueError(f"Unknown specialist: {name}. Must be one of {SPECIALIST_ROLES}")

    folder = _SPECIALISTS_ROOT / name
    if not folder.is_dir():
        raise FileNotFoundError(f"Specialist folder not found: {folder}")

    def _read(fname: str) -> str:
        fp = folder / fname
        return fp.read_text(encoding="utf-8") if fp.is_file() else ""

    briefing = _read("BRIEFING.md")
    readme = _read("README.md")

    # Extract role from briefing frontmatter or first heading
    role = name.title()
    if briefing:
        for line in briefing.split("\n"):
            if line.startswith("# "):
                role = line[2:].strip().replace(" — Специалист компании", "")
                break

    system_prompt = _build_specialist_prompt(name, role, briefing, readme)

    return SpecialistConfig(
        name=name,
        role=role,
        folder=folder,
        briefing=briefing,
        readme=readme,
        system_prompt=system_prompt,
    )


def _build_specialist_prompt(name: str, role: str, briefing: str, readme: str) -> str:
    return f"""Ты — {role} в компании AIModelJudge.

{briefing}

{readme}

## Правила работы
1. Отвечай только в рамках своей роли ({name}).
2. Не выходи за границы компетенции.
3. Если вопрос вне твоей зоны — честно скажи об этом.
4. Ты НЕ видишь ответы других специалистов.
5. Ты read-only консультант — не можешь редактировать файлы или выполнять bash-команды.

## Формат ответа
- Начни с краткого SUMMARY (2-3 предложения)
- Затем DETAILED ANALYSIS с конкретными рекомендациями
- В конце — RISKS & ASSUMPTIONS (что может пойти не так)
"""


def check_sandbox(specialist: SpecialistConfig, requested_path: Path | str) -> bool:
    """Проверяет, что специалист может читать запрошенный путь."""
    rp = Path(requested_path).resolve()
    allowed = [
        specialist.folder.resolve(),
        Path.cwd().resolve(),  # project root, read-only
    ]
    return any(rp.is_relative_to(a) for a in allowed if a.exists())


def get_memory_namespace(specialist_name: str | None, level: str = "specialist") -> str:
    """Возвращает неймспейс для memory-mcp."""
    if level == "specialist" and specialist_name:
        return f"company.specialist.{specialist_name}"
    elif level == "company":
        return "company.shared"
    return "project"


def list_available_specialists() -> list[str]:
    """Список доступных специалистов (папки с BRIEFING.md)."""
    available = []
    for name in SPECIALIST_ROLES:
        fp = _SPECIALISTS_ROOT / name / "BRIEFING.md"
        if fp.is_file():
            available.append(name)
    return available
