"""AIModelJudge — In-memory caches: model responses, semantic similarity, tool results.

ModelCache: TTL 300s base, adaptive based on hit rate [60, 900].
SemanticCache: sentence-transformers embeddings, cosine > 0.85 → hit. Max 128, LRU.
ToolResultCache: sha256(tool + sorted args), TTL 24h. Max 256, LRU.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Optional

log = logging.getLogger("aimodeljudge.cache")


class ModelCache:
    def __init__(self, ttl: int = 300, max_size: int = 64):
        self._ttl = ttl
        self._max = max_size
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._hit_count = 0
        self._miss_count = 0

    @property
    def hit_count(self) -> int:
        return self._hit_count

    @property
    def miss_count(self) -> int:
        return self._miss_count

    @property
    def hit_rate(self) -> float:
        total = self._hit_count + self._miss_count
        return self._hit_count / total if total > 0 else 0.0

    @property
    def effective_ttl(self) -> float:
        # Adaptive TTL: grows with hit rate, bounded [60, 900]
        ttl = self._ttl * (1.0 + self.hit_rate * 2.0)
        return max(60.0, min(900.0, ttl))

    def _key(self, model: str, messages: list[dict]) -> str:
        user = ""
        for m in messages:
            if m.get("role") == "user":
                user = str(m.get("content", ""))
        h = hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]
        return f"{model}:{h}"

    def get(self, model: str, messages: list[dict]) -> dict | None:
        k = self._key(model, messages)
        entry = self._store.get(k)
        if entry is None:
            self._miss_count += 1
            try:
                from web.metrics import record_cache_miss
                record_cache_miss()
            except Exception:
                pass
            return None
        expires, result = entry
        if time.monotonic() > expires:
            del self._store[k]
            self._miss_count += 1
            try:
                from web.metrics import record_cache_miss
                record_cache_miss()
            except Exception:
                pass
            return None
        self._store.move_to_end(k)
        self._hit_count += 1
        try:
            from web.metrics import record_cache_hit
            record_cache_hit()
        except Exception:
            pass
        return result

    def set(self, model: str, messages: list[dict], result: dict) -> None:
        k = self._key(model, messages)
        self._store[k] = (time.monotonic() + self.effective_ttl, result)
        self._store.move_to_end(k)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def invalidate(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


_cache = ModelCache(ttl=300)


def get_cache() -> ModelCache:
    return _cache


def invalidate_cache() -> None:
    _cache.invalidate()


# ══════════════════════════════════════════════════════════════════════
# Semantic Cache — sentence-transformers embeddings
# ══════════════════════════════════════════════════════════════════════


class SemanticCache:
    """Кэш на основе семантической близости (cosine similarity).

    Использует all-MiniLM-L6-v2 для эмбеддингов запросов.
    Cosine > threshold → возврат из кэша.
    """

    def __init__(self, threshold: float = 0.85, max_size: int = 128):
        self._threshold = threshold
        self._max = max_size
        self._store: OrderedDict[str, tuple[list[float], dict]] = OrderedDict()
        self._model = None
        self._hit_count = 0
        self._miss_count = 0
        self._init_model()

    def _init_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            log.info("SemanticCache: модель all-MiniLM-L6-v2 загружена")
        except Exception:
            log.warning("SemanticCache: sentence-transformers недоступен, кэш отключён")

    def _encode(self, text: str) -> Optional[list[float]]:
        if self._model is None:
            return None
        try:
            emb = self._model.encode(text, normalize_embeddings=True)
            return emb.tolist()
        except Exception:
            return None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        # Vectors already normalized → dot product is cosine
        return sum(x * y for x, y in zip(a, b))

    def _make_key(self, model: str, message: str) -> str:
        h = hashlib.sha256(f"{model}:{message}".encode()).hexdigest()[:16]
        return h

    @property
    def hit_count(self) -> int:
        return self._hit_count

    @property
    def miss_count(self) -> int:
        return self._miss_count

    @property
    def hit_rate(self) -> float:
        total = self._hit_count + self._miss_count
        return self._hit_count / total if total > 0 else 0.0

    def get(self, model: str, message: str) -> dict | None:
        """Поиск семантически близкого ответа в кэше."""
        if self._model is None:
            self._miss_count += 1
            try:
                from web.metrics import record_cache_miss
                record_cache_miss()
            except Exception:
                pass
            return None
        emb = self._encode(message)
        if emb is None:
            self._miss_count += 1
            try:
                from web.metrics import record_cache_miss
                record_cache_miss()
            except Exception:
                pass
            return None
        best_key: str | None = None
        best_score = -1.0
        for key, (cached_emb, _) in self._store.items():
            score = self._cosine(emb, cached_emb)
            if score > best_score:
                best_score = score
                best_key = key
        if best_key and best_score >= self._threshold:
            _, result = self._store[best_key]
            self._store.move_to_end(best_key)
            self._hit_count += 1
            try:
                from web.metrics import record_cache_hit
                record_cache_hit()
            except Exception:
                pass
            return dict(result)
        self._miss_count += 1
        try:
            from web.metrics import record_cache_miss
            record_cache_miss()
        except Exception:
            pass
        return None

    def set(self, model: str, message: str, result: dict) -> None:
        """Сохраняет ответ в кэш с эмбеддингом запроса."""
        if self._model is None:
            return
        emb = self._encode(message)
        if emb is None:
            return
        key = self._make_key(model, message)
        self._store[key] = (emb, dict(result))
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def invalidate(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


_semantic_cache = SemanticCache()


def get_semantic_cache() -> SemanticCache:
    return _semantic_cache


# ══════════════════════════════════════════════════════════════════════
# Tool Result Cache — deterministic results, TTL 24h
# ══════════════════════════════════════════════════════════════════════


class ToolResultCache:
    """Кэш результатов выполнения инструментов.

    Ключ: sha256(tool_name + json.dumps(sorted_args))[:16].
    TTL: 24 часа — детерминированные результаты (поиск, чтение файлов).
    Max: 256 записей, LRU eviction.
    """

    def __init__(self, ttl: float = 86400, max_size: int = 256):
        self._ttl = ttl
        self._max = max_size
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._hit_count = 0
        self._miss_count = 0

    def _make_key(self, tool_name: str, **kwargs) -> str:
        payload = json.dumps({"tool": tool_name, "args": kwargs}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def hit_count(self) -> int:
        return self._hit_count

    @property
    def miss_count(self) -> int:
        return self._miss_count

    def get(self, tool_name: str, **kwargs) -> dict | None:
        key = self._make_key(tool_name, **kwargs)
        entry = self._store.get(key)
        if entry is None:
            self._miss_count += 1
            try:
                from web.metrics import record_cache_miss
                record_cache_miss()
            except Exception:
                pass
            return None
        expires, result = entry
        if time.monotonic() > expires:
            del self._store[key]
            self._miss_count += 1
            try:
                from web.metrics import record_cache_miss
                record_cache_miss()
            except Exception:
                pass
            return None
        self._store.move_to_end(key)
        self._hit_count += 1
        try:
            from web.metrics import record_cache_hit
            record_cache_hit()
        except Exception:
            pass
        return dict(result)

    def set(self, tool_name: str, result: dict, **kwargs) -> None:
        key = self._make_key(tool_name, **kwargs)
        self._store[key] = (time.monotonic() + self._ttl, dict(result))
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def invalidate(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


_tool_cache = ToolResultCache()


def get_tool_cache() -> ToolResultCache:
    return _tool_cache
