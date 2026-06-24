"""Тонкий клиент к memory-mcp SQLite для использования в хуках.

Прямой доступ к БД — быстрее и надёжнее HTTP/прокси в пределах одного процесса.
Семантический поиск заменён на LIKE (полноценный только через MCP-сервер).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

_MEMORY_DB = Path.home() / ".memory-mcp" / "memory.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_MEMORY_DB))
    conn.row_factory = sqlite3.Row
    return conn


def remember(
    content: str,
    memory_type: str = "project",
    tags: list[str] | None = None,
    category: str | None = None,
) -> int | None:
    """Сохраняет memory-факт в SQLite.

    Возвращает memory_id или None при ошибке.
    """
    if not _MEMORY_DB.exists():
        return None

    conn = _conn()
    try:
        now = int(time.time())
        cur = conn.execute(
            """INSERT INTO memories (content, memory_type, source, category, created_at, trust_score)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (content, memory_type, "hook", category or "", now, 0.5),
        )
        memory_id = cur.lastrowid

        if tags and memory_id:
            conn.executemany(
                "INSERT INTO memory_tags (memory_id, tag) VALUES (?, ?)",
                [(memory_id, t) for t in tags],
            )

        conn.commit()
        return memory_id
    except Exception:
        return None
    finally:
        conn.close()


def recall(
    query: str,
    memory_type: str | None = None,
    mode: str = "balanced",
    limit: int = 10,
) -> list[dict]:
    """Ищет memory-факты по текстовому запросу (LIKE-поиск).

    Args:
        query: Поисковый запрос (разбивается на слова).
        memory_type: Фильтр по типу (project/pattern/reference).
        mode: Не используется в SQLite-режиме (для совместимости с MCP API).
        limit: Максимальное количество результатов.

    Returns:
        Список dict-объектов с ключами: id, content, memory_type, category, tags.
    """
    if not _MEMORY_DB.exists():
        return []

    conn = _conn()
    try:
        # Разбиваем запрос на слова для LIKE-поиска
        words = [w for w in query.split() if len(w) > 2]
        if not words:
            words = [query]

        conditions = []
        params: list = []
        for w in words[:5]:  # максимум 5 слов
            conditions.append("m.content LIKE ?")
            params.append(f"%{w}%")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        if memory_type:
            prefix = "WHERE" if not conditions else " AND"
            where += f" {prefix} m.memory_type = ?"
            params.append(memory_type)

        sql = (
            f"SELECT m.id, m.content, m.memory_type, m.category, m.trust_score "
            f"FROM memories m {where} "
            f"ORDER BY m.trust_score DESC, m.id DESC "
            f"LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()

        results: list[dict] = []
        for r in rows:
            d = dict(r)
            tag_rows = conn.execute(
                "SELECT tag FROM memory_tags WHERE memory_id = ?", (d["id"],)
            ).fetchall()
            d["tags"] = [t[0] for t in tag_rows]
            results.append(d)

        return results
    except Exception:
        return []
    finally:
        conn.close()


def recall_by_tags(
    tags: list[str],
    limit: int = 10,
) -> list[dict]:
    """Ищет memory-факты по тегам."""
    if not _MEMORY_DB.exists() or not tags:
        return []

    conn = _conn()
    try:
        placeholders = ",".join("?" for _ in tags)
        sql = (
            f"SELECT DISTINCT m.id, m.content, m.memory_type, m.category, m.trust_score "
            f"FROM memories m "
            f"JOIN memory_tags mt ON mt.memory_id = m.id "
            f"WHERE mt.tag IN ({placeholders}) "
            f"ORDER BY m.id DESC LIMIT ?"
        )
        rows = conn.execute(sql, [*tags, limit]).fetchall()

        results: list[dict] = []
        for r in rows:
            d = dict(r)
            tag_rows = conn.execute(
                "SELECT tag FROM memory_tags WHERE memory_id = ?", (d["id"],)
            ).fetchall()
            d["tags"] = [t[0] for t in tag_rows]
            results.append(d)

        return results
    except Exception:
        return []
    finally:
        conn.close()
