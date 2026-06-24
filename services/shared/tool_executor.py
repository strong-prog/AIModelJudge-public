"""Локальное выполнение инструментов, вызванных моделью через tool_use."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

MAX_BASH_TIMEOUT = 300
MAX_RESULT_CHARS = 80_000
SEARXNG_URL = "http://127.0.0.1:8888"
WORK_DIR = str(Path.home())

# Инструменты, требующие подтверждения пользователя перед выполнением
DANGEROUS_TOOLS: set[str] = {"bash", "write_file", "edit_file"}

# Сетевые утилиты, запрещённые к выполнению через bash.
# Внешний сетевой доступ — только через web_search (SearXNG) и web_fetch (httpx).
_NETWORK_DENYLIST: set[str] = {
    "curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp",
    "ftp", "rsync", "socat", "nmap", "tcpdump", "tshark",
}

# Паттерн: полное слово (границы слова) из деннилиста
_NETWORK_DENY_PATTERN = re.compile(
    r"\b(?:" + "|".join(map(re.escape, _NETWORK_DENYLIST)) + r")\b"
)


def _check_network_denylist(command: str) -> str | None:
    """Проверить команду на запрещённые сетевые утилиты."""
    found = set()
    for match in _NETWORK_DENY_PATTERN.finditer(command):
        found.add(match.group(0))
    if found:
        names = ", ".join(sorted(found))
        return (
            f"Запрещён прямой сетевой доступ через {names}. "
            f"Используй инструменты web_search или web_fetch."
        )
    return None

# ── Tool definitions (Anthropic format для DeepSeek) ──────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "bash",
        "description": (
            "Выполнить bash-команду в рабочей директории. "
            "Используй для запуска тестов, проверки синтаксиса, "
            "установки пакетов, работы с git."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Bash-команда для выполнения.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Таймаут в секундах (по умолчанию 60, максимум 300).",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Прочитать файл с диска с номерами строк. "
            "Используй offset и limit для больших файлов."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Абсолютный путь к файлу.",
                },
                "offset": {
                    "type": "integer",
                    "description": "С какой строки начать (1-индексация).",
                    "default": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Максимум строк (по умолчанию 500, максимум 2000).",
                    "default": 500,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Записать содержимое в файл, перезаписывая если существует. "
            "Родительские директории создаются автоматически."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Абсолютный путь к файлу.",
                },
                "content": {
                    "type": "string",
                    "description": "Полное содержимое файла.",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Заменить строку в файле (find-and-replace). "
            "old_string должен быть уникальным в файле."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Абсолютный путь к файлу.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Текст для замены (должен быть уникальным).",
                },
                "new_string": {
                    "type": "string",
                    "description": "Новый текст.",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "glob",
        "description": "Найти файлы по glob-паттерну (например, **/*.py).",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob-паттерн, например '**/*.py' или 'src/**/*.ts'.",
                },
                "path": {
                    "type": "string",
                    "description": "Директория для поиска (по умолчанию текущая).",
                    "default": ".",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Поиск по содержимому файлов через регулярные выражения (ripgrep).",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Регулярное выражение для поиска.",
                },
                "path": {
                    "type": "string",
                    "description": "Директория или файл для поиска.",
                    "default": ".",
                },
                "glob": {
                    "type": "string",
                    "description": "Фильтр файлов, например '*.py'.",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": "Режим вывода.",
                    "default": "content",
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Максимум результатов (по умолчанию 50).",
                    "default": 50,
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "web_search",
        "description": "Поиск в интернете через SearXNG.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Максимум результатов (по умолчанию 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Загрузить и извлечь содержимое веб-страницы.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL страницы для загрузки.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "agent",
        "description": (
            "Запустить подагента для выполнения изолированной подзадачи. "
            "Подагент выполняет read-only операции (чтение файлов, поиск, grep, glob) "
            "в указанной директории и возвращает результат. "
            "Используй для параллельного исследования разных частей кодовой базы, "
            "поиска в нескольких директориях одновременно, или когда нужно "
            "делегировать подзадачу чтобы не загромождать основной контекст. "
            "Можно вызвать несколько agent-ов в одном ответе для параллельной работы."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Описание подзадачи для подагента (на русском или английском). Чётко опиши что нужно найти/прочитать/исследовать.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Рабочая директория для подагента (по умолчанию домашняя).",
                    "default": str(Path.home()),
                },
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Список read-only команд (find, grep, cat, ls, head, wc). Подагент выполнит их последовательно.",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "hermes_ask",
        "description": (
            "Делегировать задачу агенту Hermes через MCP-сервер. "
            "Hermes имеет доступ к web_search, web_fetch, file tools, "
            "и может выполнять комплексные многошаговые задачи. "
            "Используй для: поиска в интернете, исследования внешних ресурсов, "
            "сложных аналитических задач требующих нескольких шагов. "
            "Hermes работает асинхронно для долгих задач (>30s)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Задача для Hermes-агента. Чётко опиши что нужно сделать (поиск, анализ, исследование, etc).",
                },
                "async_mode": {
                    "type": "boolean",
                    "description": "True — асинхронный режим (вернуть job_id сразу), False — ждать результат. По умолчанию автоопределение.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Создать карточку задачи в канбан-доске. "
            "Используй для декомпозиции запроса пользователя на подзадачи. "
            "Колонки: subagent — субагенты/исследование, "
            "tasks — активные задачи в работе, "
            "edits — изменения кода/файлов."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "column": {
                    "type": "string",
                    "enum": ["subagent", "tasks", "edits"],
                    "description": "Колонка для задачи: subagent, tasks или edits.",
                },
                "title": {
                    "type": "string",
                    "description": "Краткий заголовок задачи (до 80 символов).",
                },
                "description": {
                    "type": "string",
                    "description": "Подробное описание задачи (опционально).",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Приоритет задачи: high/medium/low (по умолчанию medium).",
                },
            },
            "required": ["column", "title"],
        },
    },
    {
        "name": "move_task",
        "description": (
            "Переместить карточку задачи между колонками канбан-доски. "
            "Используй когда задача переходит на следующий этап."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID задачи, полученный при create_task.",
                },
                "column": {
                    "type": "string",
                    "enum": ["subagent", "tasks", "edits"],
                    "description": "Целевая колонка.",
                },
            },
            "required": ["task_id", "column"],
        },
    },
    {
        "name": "update_task",
        "description": (
            "Обновить статус задачи в канбан-доске. "
            "Статусы: pending — ожидает, in_progress — выполняется, "
            "completed — завершена, error — ошибка."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID задачи.",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "error"],
                    "description": "Новый статус задачи.",
                },
                "result": {
                    "type": "string",
                    "description": "Результат выполнения (для completed/error).",
                },
                "diff_added": {
                    "type": "integer",
                    "description": "Количество добавленных строк кода (опционально).",
                },
                "diff_removed": {
                    "type": "integer",
                    "description": "Количество удалённых строк кода (опционально).",
                },
            },
            "required": ["task_id", "status"],
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────

# Инструменты, чьи результаты можно кэшировать (детерминированные, без побочных эффектов)
_CACHEABLE_TOOLS: set[str] = {"read_file", "glob", "grep", "web_search", "web_fetch"}


async def dispatch(name: str, args: dict, extra_handlers: dict | None = None, *, user_id: str | None = None) -> str:
    """Выполнить инструмент и вернуть JSON-строку с результатом.

    Если user_id передан и для него подключен локальный агент (Dev Mode),
    инструмент выполняется на машине пользователя через WebSocket.
    Иначе — локально на сервере.
    """
    # Dev Mode: route to local agent if connected
    if user_id:
        try:
            from web.agent_manager import get_agent_manager
            mgr = get_agent_manager()
            if mgr.is_connected(user_id):
                result = await mgr.execute(user_id, name, args)
                status = result.get("status", "error")
                if status == "success":
                    return json.dumps(result.get("data", result), ensure_ascii=False)
                return json.dumps({"error": result.get("message", "Unknown agent error")}, ensure_ascii=False)
        except Exception:
            pass  # Fallback to local execution

    # ToolResultCache: проверяем кэш для детерминированных инструментов
    if name in _CACHEABLE_TOOLS:
        try:
            from web.model_cache import get_tool_cache
            cached = get_tool_cache().get(name, **args)
            if cached is not None:
                return cached["result"]
        except Exception:
            pass

    handler = (extra_handlers or {}).get(name) or _HANDLERS.get(name)
    if not handler:
        return _error(f"Неизвестный инструмент: {name}")
    try:
        result = await handler(args)
        if isinstance(result, str) and len(result) > MAX_RESULT_CHARS:
            result = result[: MAX_RESULT_CHARS - 3] + "..."
        # Сохраняем в кэш
        if name in _CACHEABLE_TOOLS and not result.startswith('{"error"'):
            try:
                from web.model_cache import get_tool_cache
                get_tool_cache().set(name, {"result": result}, **args)
            except Exception:
                pass
        try:
            from web.metrics import record_tool_execution
            record_tool_execution(tool=name)
        except Exception:
            pass
        return result
    except Exception as exc:
        try:
            from web.metrics import record_tool_error
            record_tool_error(tool=name, error_type=type(exc).__name__)
        except Exception:
            pass
        return _error(f"Ошибка в {name}: {exc}")


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


# ── Handlers ──────────────────────────────────────────────────────────────

async def _handle_bash(args: dict) -> str:
    command = args.get("command", "")
    if not command:
        return _error("Пустая команда")

    # Блокировка запрещённых сетевых утилит (быстрая проверка до sandbox)
    deny_reason = _check_network_denylist(command)
    if deny_reason:
        return _error(deny_reason)

    timeout = min(int(args.get("timeout", 60)), MAX_BASH_TIMEOUT)

    # Execution Sandbox
    try:
        from web.sandbox import sandbox_exec, SandboxConfig
        sandbox_config = SandboxConfig(
            project_root=Path(WORK_DIR),
            max_timeout=timeout,
            max_output_bytes=MAX_RESULT_CHARS,
            allow_network=False,
        )
        result = await sandbox_exec(command, config=sandbox_config)

        if result.blocked:
            return _error(result.block_reason)

        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if result.truncated:
            output += "\n[output truncated]"

        return json.dumps(
            {"output": output, "exit_code": result.returncode,
             "duration_ms": round(result.duration_ms)},
            ensure_ascii=False,
        )
    except ImportError:
        pass  # Fallback: прямой subprocess (без sandbox)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=WORK_DIR,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return _error(f"Команда превысила таймаут {timeout}с")
    output = stdout.decode("utf-8", errors="replace")
    return json.dumps(
        {"output": output, "exit_code": proc.returncode}, ensure_ascii=False
    )


async def _handle_read_file(args: dict) -> str:
    path = Path(args["file_path"])
    if not path.is_file():
        return _error(f"Файл не найден: {path}")
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _error(str(exc))
    lines = content.splitlines()
    offset = max(1, int(args.get("offset", 1)))
    limit = min(int(args.get("limit", 500)), 2000)
    selected = lines[offset - 1 : offset - 1 + limit]
    result = "\n".join(
        f"{i + offset:>6}|{line}" for i, line in enumerate(selected)
    )
    return json.dumps(
        {"content": result, "total_lines": len(lines), "offset": offset, "limit": limit},
        ensure_ascii=False,
    )


async def _handle_write_file(args: dict) -> str:
    path = Path(args["file_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return json.dumps(
        {"ok": True, "path": str(path), "size": len(args["content"])},
        ensure_ascii=False,
    )


async def _handle_edit_file(args: dict) -> str:
    path = Path(args["file_path"])
    if not path.is_file():
        return _error(f"Файл не найден: {path}")
    content = path.read_text(encoding="utf-8")
    old = args["old_string"]
    new = args["new_string"]
    count = content.count(old)
    if count == 0:
        return _error("old_string не найден в файле")
    if count > 1:
        return _error(f"old_string найден {count} раз, должен быть уникальным")
    content = content.replace(old, new, 1)
    path.write_text(content, encoding="utf-8")
    return json.dumps({"ok": True, "path": str(path)}, ensure_ascii=False)


async def _handle_glob(args: dict) -> str:
    import glob as _glob

    pattern = args["pattern"]
    search_path = args.get("path", ".")
    results = sorted(
        _glob.glob(str(Path(search_path) / pattern), recursive=True)
    )[:100]
    return json.dumps(
        {"files": results, "count": len(results)}, ensure_ascii=False
    )


async def _handle_grep(args: dict) -> str:
    pattern = args["pattern"]
    search_path = args.get("path", ".")
    glob_filter = args.get("glob", "")
    output_mode = args.get("output_mode", "content")
    head_limit = int(args.get("head_limit", 50))

    cmd = ["rg", "--no-heading", "-n", "--color", "never"]
    if glob_filter:
        cmd.extend(["--glob", glob_filter])
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    cmd.extend([pattern, str(search_path)])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")
    lines = output.splitlines()[:head_limit]
    error_text = stderr.decode("utf-8", errors="replace")
    return json.dumps(
        {
            "results": "\n".join(lines),
            "count": len(lines),
            "exit_code": proc.returncode,
            "stderr": error_text[:500] if proc.returncode != 0 else "",
        },
        ensure_ascii=False,
    )


async def _handle_web_search(args: dict) -> str:
    import httpx

    query = args["query"]
    limit = int(args.get("limit", 5))

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{SEARXNG_URL}/search",
                params={"q": query, "format": "json"},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            return _error(f"Ошибка поиска: {exc}")
        except ValueError:
            return _error("Невалидный JSON от SearXNG")

    results = []
    for r in data.get("results", [])[:limit]:
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        })
    return json.dumps(
        {"results": results, "query": query}, ensure_ascii=False
    )


async def _handle_web_fetch(args: dict) -> str:
    import httpx

    url = args["url"]
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(
                url,
                timeout=20.0,
                headers={"User-Agent": "Hermes-WebAgent/1.0"},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return _error(f"Ошибка загрузки: {exc}")

    text = resp.text[:MAX_RESULT_CHARS]
    return json.dumps(
        {
            "content": text,
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "url": str(resp.url),
        },
        ensure_ascii=False,
    )


# Разрешённые read-only команды для подагентов
_READONLY_COMMANDS: set[str] = {
    "find", "grep", "rg", "cat", "head", "tail", "wc", "ls", "file",
    "stat", "du", "df", "sort", "uniq", "cut", "awk", "sed", "tr",
    "git", "python3", "python",
}


async def _handle_agent(args: dict) -> str:
    """Выполнить подзадачу в изолированном подагенте (read-only)."""
    task = args.get("task", "")
    if not task:
        return _error("Пустая задача для подагента")

    cwd = str(Path(args.get("cwd", WORK_DIR)).expanduser().resolve())
    if not Path(cwd).is_dir():
        return _error(f"Директория не найдена: {cwd}")

    commands = args.get("commands", [])
    timeout = min(int(args.get("timeout", 60)), 180)

    if not commands:
        # Автоопределение команд по задаче
        return json.dumps({
            "agent_task": task,
            "result": "Подагент запущен. Укажи конкретные команды (find, grep, cat, ls) "
                      "для выполнения в параметре commands.",
            "hint": "Используй commands: ['find ...', 'grep ...', 'cat ...'] для "
                    "исследования директории " + cwd,
        }, ensure_ascii=False)

    outputs = []
    for cmd in commands:
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        exe = cmd.strip().split()[0] if cmd.strip().split() else ""
        if exe not in _READONLY_COMMANDS:
            outputs.append(f"[blocked] {cmd}")
            continue

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            if len(out) > 10_000:
                out = out[:10_000] + "\n... (обрезано)"
            outputs.append(f"[{cmd}]\n{out or '(пусто)'}")
        except TimeoutError:
            proc.kill()
            outputs.append(f"[{cmd}]\n(таймаут {timeout}с)")
        except Exception as exc:
            outputs.append(f"[{cmd}]\n(ошибка: {exc})")

    return json.dumps({
        "agent_task": task,
        "cwd": cwd,
        "commands_executed": len([c for c in commands if c and c.strip()]),
        "output": "\n\n".join(outputs),
    }, ensure_ascii=False)


# ── Kanban store ───────────────────────────────────────────────────────────

_KANBAN_COLUMNS: frozenset[str] = frozenset({"subagent", "tasks", "edits"})
_KANBAN_STATUSES: frozenset[str] = frozenset({"pending", "in_progress", "completed", "error"})


class KanbanStore:
    """In-memory kanban state for validation (frontend is the source of truth)."""
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._current_session_id: str = ""

    def set_session(self, session_id: str) -> None:
        self._current_session_id = session_id

    def create(self, column: str, title: str, priority: str = "medium") -> str:
        task_id = uuid.uuid4().hex[:8]
        self._tasks[task_id] = {
            "column": column,
            "title": title,
            "priority": priority,
            "status": "pending",
            "result": None,
            "session_id": self._current_session_id,
        }
        return task_id

    def move(self, task_id: str, column: str) -> tuple[str, str] | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        old = task["column"]
        task["column"] = column
        return (old, column)

    def resolve(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def update_status(self, task_id: str, status: str, result: str | None = None) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task["status"] = status
        if result:
            task["result"] = result
        return True

    def get_plan_snapshot(self) -> list[dict]:
        """Возвращает задачи текущей сессии как plan-entries (ACP-формат)."""
        plan_columns = {"tasks", "subagent", "edits"}
        entries = []
        for task_id, task in self._tasks.items():
            if task["column"] not in plan_columns:
                continue
            if task.get("session_id", "") != self._current_session_id:
                continue
            entries.append({
                "id": task_id,
                "title": task["title"],
                "column": task["column"],
                "priority": task.get("priority", "medium"),
                "status": task.get("status", "pending"),
                "result": task.get("result"),
            })
        return entries


_kanban = KanbanStore()


async def _handle_create_task(args: dict) -> str:
    column = args.get("column", "")
    title = args.get("title", "")
    description = args.get("description", "")
    priority = args.get("priority", "medium")

    if column not in _KANBAN_COLUMNS:
        return _error(f"Недопустимая колонка: {column}. Допустимые: {', '.join(sorted(_KANBAN_COLUMNS))}")
    if not title or not title.strip():
        return _error("Пустой заголовок задачи")
    if priority not in ("high", "medium", "low"):
        priority = "medium"

    task_id = _kanban.create(column, title.strip(), priority)
    return json.dumps({
        "ok": True,
        "task_id": task_id,
        "column": column,
        "title": title.strip(),
        "description": description.strip() if description else "",
        "priority": priority,
    }, ensure_ascii=False)


async def _handle_move_task(args: dict) -> str:
    task_id = args.get("task_id", "")
    column = args.get("column", "")

    if column not in _KANBAN_COLUMNS:
        return _error(f"Недопустимая колонка: {column}")
    if not task_id:
        return _error("Пустой task_id")

    result = _kanban.move(task_id, column)
    if result is None:
        return _error(f"Задача не найдена: {task_id}")

    old_col, new_col = result
    return json.dumps({
        "ok": True,
        "task_id": task_id,
        "from_column": old_col,
        "to_column": new_col,
    }, ensure_ascii=False)


async def _handle_update_task(args: dict) -> str:
    task_id = args.get("task_id", "")
    status = args.get("status", "")
    result_text = args.get("result", "")
    diff_added = args.get("diff_added", 0)
    diff_removed = args.get("diff_removed", 0)

    if not task_id:
        return _error("Пустой task_id")
    if status not in _KANBAN_STATUSES:
        return _error(f"Недопустимый статус: {status}. Допустимые: {', '.join(sorted(_KANBAN_STATUSES))}")

    task = _kanban.resolve(task_id)
    if task is None:
        return _error(f"Задача не найдена: {task_id}")

    _kanban.update_status(task_id, status, result_text.strip() if result_text else None)

    return json.dumps({
        "ok": True,
        "task_id": task_id,
        "status": status,
        "result": result_text.strip() if result_text else "",
        "diff_added": int(diff_added) if diff_added else 0,
        "diff_removed": int(diff_removed) if diff_removed else 0,
    }, ensure_ascii=False)


async def _handle_hermes_ask(args: dict) -> str:
    """Делегировать запрос агенту Hermes через MCP."""
    prompt = args.get("prompt", "")
    if not prompt or not prompt.strip():
        return _error("Пустой prompt для hermes_ask")

    async_mode = args.get("async_mode", None)
    if isinstance(async_mode, str):
        async_mode = async_mode.lower() in ("true", "1", "yes")

    try:
        from services.shared.mcp_client import get_mcp_client
        mcp = get_mcp_client()

        # Проверить доступность
        if not await mcp.health():
            return json.dumps({
                "status": "unavailable",
                "message": "Hermes MCP сервер недоступен. Убедись что hermes mcp serve запущен.",
                "prompt": prompt[:200],
            }, ensure_ascii=False)

        result = await mcp.hermes_ask(prompt=prompt.strip(), async_mode=async_mode)
        return json.dumps({
            "ok": result.ok,
            "content": result.content,
            "job_id": result.job_id,
            "status": result.status,
            "error": result.error,
        }, ensure_ascii=False)
    except ImportError:
        return json.dumps({
            "status": "unavailable",
            "message": "Hermes MCP клиент не установлен. Выполни pip install hermes-mcp.",
            "prompt": prompt[:200],
        }, ensure_ascii=False)
    except Exception as exc:
        return _error(f"hermes_ask ошибка: {exc}")


_HANDLERS: dict[str, Any] = {
    "bash": _handle_bash,
    "read_file": _handle_read_file,
    "write_file": _handle_write_file,
    "edit_file": _handle_edit_file,
    "glob": _handle_glob,
    "grep": _handle_grep,
    "web_search": _handle_web_search,
    "web_fetch": _handle_web_fetch,
    "hermes_ask": _handle_hermes_ask,
    "agent": _handle_agent,
    "create_task": _handle_create_task,
    "move_task": _handle_move_task,
    "update_task": _handle_update_task,
}
