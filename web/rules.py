"""AIModelJudge — Rules Engine (security, style, architecture).

Загружает структурированные YAML-правила из ~/.hermes-aimodeljudge/rules/
и парсит ECC Markdown-правила из ~/.hermes/rules/common/ и ~/.hermes/rules/python/.
Используется PreToolUse-хуком для валидации операций перед выполнением.

AgentShield: 88 правил безопасности в agent-shield.yaml.
Режимы: block (жёсткая блокировка, 14 critical) / warn (предупреждение, 74).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

_log = logging.getLogger("aimodeljudge.rules")

_ENV = os.getenv("AMJ_ENV", "")
if _ENV:
    _BASE = Path.home() / ".hermes-aimodeljudge" / _ENV
else:
    _BASE = Path.home() / ".hermes-aimodeljudge"

RULES_DIR = _BASE / "rules"
RULES_DIR.mkdir(parents=True, exist_ok=True)

VIOLATIONS_PATH = RULES_DIR / "violations.jsonl"

ECC_RULES_DIR = Path.home() / ".hermes" / "rules"
ECC_SKILLS_DIR = Path.home() / ".hermes" / "skills" / "ecc-imports"


@dataclass
class RuleViolation:
    """Запись о сработавшем правиле."""
    timestamp: float
    rule_id: str
    tool_name: str
    args_summary: str
    severity: str
    action: str  # block | warn
    message: str
    session_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "rule_id": self.rule_id,
            "tool_name": self.tool_name,
            "args_summary": self.args_summary[:200],
            "severity": self.severity,
            "action": self.action,
            "message": self.message,
            "session_id": self.session_id,
        }


@dataclass
class Rule:
    id: str
    description: str
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    category: Literal["security", "style", "architecture"] = "security"
    applies_to: list[str] = field(default_factory=lambda: ["*"])
    check: Literal["regex", "command_denylist", "content_scan", "path_allowlist"] = "regex"
    pattern: str = ""
    commands: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    message: str = ""
    action: Literal["block", "warn"] = "warn"

    def match_tool(self, tool_name: str) -> bool:
        return "*" in self.applies_to or tool_name in self.applies_to


# ── Built-in critical rules (extracted from SYSTEM_PROMPT) ─────────────

_BUILTIN_RULES: list[Rule] = [
    Rule(
        id="no-api-keys-in-output",
        description="Не выводить API-ключи, токены, пароли в результатах инструментов",
        severity="critical",
        applies_to=["write_file", "edit_file"],
        check="regex",
        pattern=r'sk-[a-zA-Z0-9]{20,}',
        message="Обнаружен API-ключ в выводе (паттерн sk-...). Ключи не должны попадать в файлы.",
    ),
    Rule(
        id="no-secrets-in-files",
        description="Не записывать секреты (пароли, ключи) в файлы",
        severity="critical",
        applies_to=["write_file", "edit_file"],
        check="content_scan",
        pattern=r'(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*["\'][^"\']{8,}["\']',
        message="Запись секретов в файлы запрещена. Используй переменные окружения или .env.",
    ),
    Rule(
        id="no-dangerous-bash",
        description="Блокировать деструктивные shell-команды",
        severity="critical",
        applies_to=["bash"],
        check="command_denylist",
        commands=[
            "rm -rf /",
            "rm -rf ~",
            "mkfs.",
            "dd if=",
            ":(){ :|:& };:",
            "chmod 777 /",
            "> /dev/sda",
            "mv / /dev/null",
        ],
        message="Деструктивная команда заблокирована Rules Engine.",
    ),
    Rule(
        id="no-curl-shell-pipe",
        description="Блокировать curl/wget с пайпом в shell",
        severity="high",
        applies_to=["bash"],
        check="regex",
        pattern=r'(curl|wget)\s+.*\|\s*(sh|bash|zsh|python)',
        message="Пайп curl/wget в интерпретатор заблокирован. Скачай и проверь скрипт отдельно.",
    ),
    Rule(
        id="no-sudo-in-bash",
        description="Блокировать sudo в bash (если не разрешено явно)",
        severity="high",
        applies_to=["bash"],
        check="command_denylist",
        commands=["sudo ", "su -", "su root"],
        message="sudo запрещён. Выполняй команды без повышения привилегий.",
    ),
    Rule(
        id="no-traversal-outside-project",
        description="Не читать/писать файлы вне дерева проекта без явного разрешения",
        severity="medium",
        applies_to=["read_file", "write_file", "edit_file", "glob", "grep"],
        check="path_allowlist",
        paths=[
            str(Path(__file__).resolve().parent.parent),
            str(Path.home() / ".hermes"),
            str(Path.home() / ".hermes-aimodeljudge"),
            "/tmp",
            str(Path.home() / ".claude"),
        ],
        message="Попытка доступа к пути вне разрешённых директорий.",
    ),
]


# ── Rules Engine ───────────────────────────────────────────────────────


class RulesEngine:
    """Загружает и проверяет правила безопасности."""

    def __init__(self) -> None:
        self.rules: dict[str, list[Rule]] = {"security": [], "style": [], "architecture": []}
        self._loaded = False
        self._recent_violations: list[RuleViolation] = []

    # ── load ──────────────────────────────────────────────────────────

    def load_all(self) -> int:
        """Загружает все правила: built-in + YAML + ECC Markdown."""
        self._loaded = False
        total = 0

        # Built-in
        for rule in _BUILTIN_RULES:
            self.rules.setdefault(rule.category, []).append(rule)
            total += 1

        # YAML rules from project rules dir
        total += self._load_yaml_dir(RULES_DIR)

        # ECC Markdown rules
        total += self._load_ecc_markdown()

        self._loaded = True
        _log.info("Rules Engine: загружено %d правил", total)
        return total

    def _load_yaml_dir(self, directory: Path) -> int:
        """Загружает все .yaml/.json файлы из директории."""
        loaded = 0
        for f in sorted(directory.glob("*")):
            if f.suffix in (".yaml", ".yml"):
                loaded += self._load_yaml(f)
            elif f.suffix == ".json":
                loaded += self._load_json(f)
        return loaded

    def _load_yaml(self, path: Path) -> int:
        """Парсит YAML-файл правил."""
        try:
            import yaml as _yaml
        except ImportError:
            _log.debug("PyYAML не установлен, пропущен %s", path)
            return 0
        try:
            with open(path, encoding="utf-8") as fh:
                docs = list(_yaml.safe_load_all(fh))
        except Exception:
            _log.warning("Ошибка парсинга YAML: %s", path, exc_info=True)
            return 0
        return self._ingest_raw_rules(docs, source=str(path))

    def _load_json(self, path: Path) -> int:
        """Парсит JSON-файл правил."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            docs = [data] if isinstance(data, dict) else data
            return self._ingest_raw_rules(docs, source=str(path))
        except Exception:
            _log.warning("Ошибка парсинга JSON: %s", path, exc_info=True)
            return 0

    def _ingest_raw_rules(self, docs: list[dict[str, Any]], source: str) -> int:
        """Преобразует сырые dict'ы в Rule объекты."""
        count = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            category = doc.get("category", "security")
            for r in doc.get("rules", []):
                if not isinstance(r, dict):
                    continue
                try:
                    raw_action = r.get("action", "warn")
                    if raw_action not in ("block", "warn"):
                        raw_action = "warn"
                    rule = Rule(
                        id=r.get("id", f"rule-{count}"),
                        description=r.get("description", ""),
                        severity=r.get("severity", "medium"),
                        category=category,
                        applies_to=r.get("applies_to", ["*"]),
                        check=r.get("check", "regex"),
                        pattern=r.get("pattern", ""),
                        commands=r.get("commands", []),
                        paths=r.get("paths", []),
                        message=r.get("message", ""),
                        action=raw_action,
                    )
                    self.rules.setdefault(category, []).append(rule)
                    count += 1
                except Exception:
                    _log.warning("Ошибка загрузки правила из %s: %s", source, r.get("id", "?"))
        return count

    def _load_ecc_markdown(self) -> int:
        """Парсит ECC Markdown-правила (checklist items)."""
        loaded = 0
        if not ECC_RULES_DIR.exists():
            return 0

        ecc_sources = [
            ECC_RULES_DIR / "common" / "security.md",
            ECC_RULES_DIR / "common" / "coding-style.md",
            ECC_RULES_DIR / "python" / "security.md",
            ECC_RULES_DIR / "python" / "coding-style.md",
            ECC_RULES_DIR / "python" / "patterns.md",
        ]
        for path in ecc_sources:
            if path.exists():
                loaded += self._parse_markdown_rules(path)

        # Also check ecc-imports skills for RULES.md
        if ECC_SKILLS_DIR.exists():
            for rules_md in sorted(ECC_SKILLS_DIR.glob("*/RULES.md")):
                loaded += self._parse_markdown_rules(rules_md)

        return loaded

    def _parse_markdown_rules(self, path: Path) -> int:
        """Извлекает checklist items из Markdown-файла как правила."""
        loaded = 0
        category = "security"
        if "style" in path.name or "coding" in path.name:
            category = "style"
        elif "pattern" in path.name or "architecture" in path.name:
            category = "architecture"

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return 0

        current_section = ""
        for line in text.splitlines():
            stripped = line.strip()
            # Track sections (## headings)
            if stripped.startswith("## "):
                current_section = stripped[3:].strip().lower()
                continue

            # Parse checklist items: - [ ] item text
            m = re.match(r'-\s*\[\s*\S?\s*\]\s+(.+)', stripped)
            if not m:
                continue
            desc = m.group(1).strip()
            if len(desc) < 5:
                continue

            # Try to extract a pattern or command from the description
            pattern = ""
            commands: list[str] = []
            check: Literal["regex", "command_denylist", "content_scan", "path_allowlist"] = "content_scan"

            # Detect regex patterns in backticks
            pat_match = re.search(r'`([^`]{6,})`', desc)
            if pat_match:
                pattern = pat_match.group(1).replace("\\", "\\\\")

            # Detect command names
            cmd_match = re.findall(r'\b(curl|wget|nc|rm\s+-rf|sudo|chmod\s+777|mkfs)\b', desc, re.IGNORECASE)
            if cmd_match:
                commands = list(cmd_match)
                check = "command_denylist"

            rule = Rule(
                id=f"ecc-{path.stem}-{loaded}",
                description=desc,
                severity="medium",
                category=category,
                check=check,
                pattern=pattern,
                commands=commands,
                message=desc,
            )
            self.rules.setdefault(category, []).append(rule)
            loaded += 1

        return loaded

    # ── check ─────────────────────────────────────────────────────────

    def check_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        """Проверяет вызов инструмента через все загруженные правила.

        Возвращает список violation-объектов с полями:
          rule_id, severity, action (block|warn), message, tool_name, args_summary
        Пустой список — всё чисто.
        """
        violations: list[dict[str, Any]] = []
        for _category, rules in self.rules.items():
            for rule in rules:
                if not rule.match_tool(tool_name):
                    continue
                msg = self._check_rule(rule, tool_name, args)
                if msg:
                    v = {
                        "rule_id": rule.id,
                        "severity": rule.severity,
                        "action": rule.action,
                        "message": msg,
                        "tool_name": tool_name,
                        "args_summary": self._args_summary(args),
                    }
                    violations.append(v)
                    self._record_violation(v, session_id)
        return violations

    def check_tool_legacy(self, tool_name: str, args: dict[str, Any]) -> list[str]:
        """Совместимость: возвращает список violation-сообщений (строки)."""
        return [v["message"] for v in self.check_tool(tool_name, args)]

    def has_block_violations(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Есть ли хотя бы одно block-нарушение?"""
        for v in self.check_tool(tool_name, args):
            if v.get("action") == "block":
                return True
        return False

    # ── violation history ─────────────────────────────────────────────

    def _record_violation(self, v: dict[str, Any], session_id: str = "") -> None:
        """Записывает нарушение в in-memory список и JSONL лог."""
        rec = RuleViolation(
            timestamp=time.time(),
            rule_id=v.get("rule_id", ""),
            tool_name=v.get("tool_name", ""),
            args_summary=v.get("args_summary", ""),
            severity=v.get("severity", "medium"),
            action=v.get("action", "warn"),
            message=v.get("message", ""),
            session_id=session_id,
        )
        self._recent_violations.append(rec)
        # Keep last 500 in memory
        if len(self._recent_violations) > 500:
            self._recent_violations = self._recent_violations[-500:]
        # Persist to JSONL
        try:
            with open(VIOLATIONS_PATH, "a") as f:
                f.write(json.dumps(rec.as_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_violations(self, limit: int = 50) -> list[dict[str, Any]]:
        """Возвращает последние нарушения (из памяти + JSONL)."""
        results: list[dict[str, Any]] = []
        # First from JSONL
        if VIOLATIONS_PATH.exists():
            try:
                with open(VIOLATIONS_PATH) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                results.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            except Exception:
                pass
        # Add in-memory ones not yet flushed
        mem_ids = {r.get("rule_id") for r in results[-50:]}
        for v in self._recent_violations[-50:]:
            d = v.as_dict()
            key = f"{d['timestamp']}-{d['rule_id']}"
            if key not in mem_ids:
                results.append(d)
        results.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
        return results[-limit:][::-1]

    @staticmethod
    def _args_summary(args: dict[str, Any]) -> str:
        """Краткая сводка аргументов для лога."""
        parts: list[str] = []
        for k, v in args.items():
            if isinstance(v, str):
                parts.append(f"{k}={v[:60]}")
            elif isinstance(v, (int, float, bool)):
                parts.append(f"{k}={v}")
        return "; ".join(parts[:3])

    def _check_rule(self, rule: Rule, tool_name: str, args: dict[str, Any]) -> str | None:
        """Проверяет одно правило. Возвращает сообщение о нарушении или None."""
        check = rule.check
        text = self._args_to_text(args)

        if check == "regex":
            if rule.pattern and re.search(rule.pattern, text, re.IGNORECASE):
                return rule.message or f"[{rule.severity}] {rule.id}: {rule.description}"
        elif check == "command_denylist":
            command = args.get("command", "")
            for blocked in rule.commands:
                if blocked.lower() in command.lower():
                    return rule.message or f"[{rule.severity}] {rule.id}: {rule.description} — команда '{blocked}'"
            if rule.pattern and re.search(rule.pattern, text, re.IGNORECASE):
                return rule.message or f"[{rule.severity}] {rule.id}: {rule.description}"
        elif check == "content_scan":
            if rule.pattern and re.search(rule.pattern, text, re.IGNORECASE):
                return rule.message or f"[{rule.severity}] {rule.id}: {rule.description}"
            # For write_file/edit_file, also scan the content being written
            content = args.get("content", "")
            if content and rule.pattern and re.search(rule.pattern, str(content), re.IGNORECASE):
                return rule.message or f"[{rule.severity}] {rule.id}: {rule.description}"
        elif check == "path_allowlist":
            file_path = args.get("file_path", "") or args.get("path", "") or ""
            if file_path and not self._path_allowed(rule, file_path):
                return rule.message or f"[{rule.severity}] {rule.id}: путь '{file_path}' не в разрешённых"

        return None

    @staticmethod
    def _args_to_text(args: dict[str, Any]) -> str:
        """Сериализует аргументы в текст для regex-проверок."""
        parts: list[str] = []
        for k, v in args.items():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, (list, dict)):
                try:
                    parts.append(json.dumps(v, ensure_ascii=False))
                except (TypeError, ValueError):
                    pass
        return " ".join(parts)

    @staticmethod
    def _path_allowed(rule: Rule, file_path: str) -> bool:
        """Проверяет что путь находится в разрешённых директориях."""
        resolved = str(Path(file_path).resolve())
        for allowed in rule.paths:
            if resolved.startswith(allowed):
                return True
        return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded


# ── Singleton ──────────────────────────────────────────────────────────

_rules_engine: RulesEngine | None = None


def get_rules_engine() -> RulesEngine:
    global _rules_engine
    if _rules_engine is None:
        _rules_engine = RulesEngine()
    return _rules_engine


def ensure_rules_dir() -> Path:
    """Создаёт директорию правил и seed security.yaml при первом запуске."""
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    seed = RULES_DIR / "security.yaml"
    if not seed.exists():
        seed.write_text(
            "# AIModelJudge — seed security rules\n"
            "# Загружаются автоматически при старте. Редактируй свободно.\n\n"
            "category: security\n"
            "rules:\n"
            '  - id: no-api-keys-in-output\n'
            "    description: Никогда не выводить API-ключи, токены или пароли\n"
            "    severity: critical\n"
            "    applies_to: ['*']\n"
            "    check: regex\n"
            "    pattern: 'sk-[a-zA-Z0-9]{20,}'\n\n"
            '  - id: no-secrets-in-files\n'
            "    description: Не записывать секреты (пароли, ключи) в файлы\n"
            "    severity: critical\n"
            "    applies_to: [write_file, edit_file]\n"
            "    check: content_scan\n"
            "    pattern: '(?i)(api[_-]?key|secret|password|token)\\s*[:=]\\s*[\"\\']\\S{8,}[\"\\']'\n\n"
            '  - id: no-dangerous-bash\n'
            "    description: Блокировать деструктивные shell-команды\n"
            "    severity: critical\n"
            "    applies_to: [bash]\n"
            "    check: command_denylist\n"
            '    commands: [\"rm -rf /\", \"rm -rf ~\", \"mkfs.\", \"dd if=\", \":(){ :|:& };:\", \"chmod 777 /\"]\n\n'
            '  - id: no-curl-shell-pipe\n'
            "    description: Блокировать curl/wget с пайпом в интерпретатор\n"
            "    severity: high\n"
            "    applies_to: [bash]\n"
            "    check: regex\n"
            "    pattern: '(curl|wget)\\s+.*\\|\\s*(sh|bash|zsh|python)'\n"
        )
    return RULES_DIR
