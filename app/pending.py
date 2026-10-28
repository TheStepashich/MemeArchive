from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from app.config import settings
from app.errors import NotFoundError

logger = logging.getLogger(__name__)

_INDEX_NAME = "index.json"
_lock = threading.Lock()


def _index_path() -> Path:
    return settings.pending_dir / _INDEX_NAME


def _read_locked() -> dict[str, dict[str, Any]]:
    path = _index_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Не удалось прочитать очередь модерации (%s)", exc)
        return {}
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, dict):
        return {}
    return {str(key): value for key, value in items.items() if isinstance(value, dict)}


def _write_locked(items: dict[str, dict[str, Any]]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def list_items() -> list[dict[str, Any]]:
    with _lock:
        items = list(_read_locked().values())
    return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def get(item_id: str) -> dict[str, Any] | None:
    with _lock:
        return _read_locked().get(item_id)


def contains(item_id: str) -> bool:
    with _lock:
        return item_id in _read_locked()


def count() -> int:
    with _lock:
        return len(_read_locked())


def add(record: dict[str, Any]) -> None:
    with _lock:
        items = _read_locked()
        items[str(record["id"])] = record
        _write_locked(items)


def remove(item_id: str) -> dict[str, Any] | None:
    with _lock:
        items = _read_locked()
        record = items.pop(item_id, None)
        if record is not None:
            _write_locked(items)
    return record


def due(now: float) -> list[dict[str, Any]]:
    with _lock:
        items = list(_read_locked().values())
    selected = [item for item in items if float(item.get("expires_at") or 0) <= now]
    return sorted(selected, key=lambda item: float(item.get("expires_at") or 0))


def image_path(record: dict[str, Any]) -> Path:
    stored_name = str(record.get("stored_name") or "")
    if not stored_name or Path(stored_name).name != stored_name:
        raise NotFoundError("Файл ожидает модерации.")
    return settings.pending_dir / stored_name


def reset() -> None:
    with _lock:
        items = _read_locked()
        _write_locked({})
    for item in items.values():
        try:
            image_path(item).unlink(missing_ok=True)
        except (OSError, NotFoundError):
            pass
