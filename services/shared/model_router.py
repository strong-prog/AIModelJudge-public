"""Model Router — переключение между DeepSeek Chat и GPT-5.4.

Хранит активную модель в JSON-файле. Используется и ботом, и web-agent.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

# Где хранить состояние модели
_STATE_FILE = Path(os.getenv("MODEL_STATE_FILE", str(Path.home() / ".hermes-aimodeljudge/state/model_state.json")))

# Значения модели для Hermes API
_MODEL_MAP = {
    "deepseek": "hermes-agent",
    "deepseek-chat": "deepseek/deepseek-chat",
    "gpt-5.4": "gpt-5.4",
    "gemini-2.5-flash": "gemini/gemini-2.5-flash",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
}

# Lock для thread-safe операций
_lock = threading.Lock()


def _ensure_state_dir() -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _read_state() -> dict:
    if not _STATE_FILE.is_file():
        return {"active_model": "deepseek"}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active_model": "deepseek"}


def get_active_model() -> str:
    """Возвращает имя модели для подстановки в поле 'model' запроса к Hermes API."""
    with _lock:
        state = _read_state()
        raw = state.get("active_model", "deepseek")
    return _MODEL_MAP.get(raw, "hermes-agent")


def get_active_model_label() -> str:
    """Возвращает читаемую метку текущей модели (для кнопок/UI)."""
    with _lock:
        state = _read_state()
        raw = state.get("active_model", "deepseek")
    return raw


def switch_model(new_model: str) -> str:
    """Переключает активную модель. Принимает ключ ('deepseek' или 'gpt-5.4').

    Возвращает новую метку модели.
    """
    if new_model not in _MODEL_MAP:
        raise ValueError(f"Неизвестная модель: {new_model}. Доступны: {list(_MODEL_MAP)}")
    with _lock:
        _ensure_state_dir()
        _STATE_FILE.write_text(
            json.dumps({"active_model": new_model}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Пишем также human-readable файл для AI-агента
        _info_file = _STATE_FILE.parent / "active_model.txt"
        _info_file.write_text(
            f"Активная модель: {get_display_name(new_model)} ({new_model})\n"
            f"Дата переключения: {__import__('datetime').datetime.now().isoformat()}\n"
        )
    return new_model


def get_display_name(model_key: str) -> str:
    """Человеко-читаемое имя модели."""
    names = {
        "deepseek": "DeepSeek V4 Pro",
        "deepseek-chat": "DeepSeek Chat",
        "gpt-5.4": "GPT-5.4",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-2.5-pro": "Gemini 2.5 Pro",
    }
    return names.get(model_key, model_key)


def list_available_models() -> list[dict[str, str]]:
    """Список всех доступных моделей для UI."""
    return [{"id": k, "name": get_display_name(k)} for k in _MODEL_MAP]


def get_other_model_label() -> str:
    """Возвращает метку противоположной модели — циклический выбор."""
    current = get_active_model_label()
    keys = list(_MODEL_MAP.keys())
    try:
        idx = keys.index(current)
        return keys[(idx + 1) % len(keys)]
    except ValueError:
        return keys[0]
