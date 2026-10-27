from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

COUNTER_KEYS = (
    "embedding_query_calls",
    "embedding_document_calls",
    "embedding_errors",
    "description_calls",
    "description_errors",
    "cache_exact_hits",
    "cache_fuzzy_hits",
    "cache_misses",
)

_lock = threading.Lock()
_counters: dict[str, int] = dict.fromkeys(COUNTER_KEYS, 0)
_started_at = ""
_updated_at = ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _save_locked() -> None:
    payload = {
        "started_at": _started_at,
        "updated_at": _updated_at,
        "counters": _counters,
    }
    path = settings.stats_file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load() -> None:
    global _counters, _started_at, _updated_at
    with _lock:
        path = settings.stats_file
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _started_at = _now_iso()
            _updated_at = _started_at
            return
        except (OSError, ValueError) as exc:
            logger.warning("Не удалось загрузить статистику (%s), начинаем с нуля", exc)
            _started_at = _now_iso()
            _updated_at = _started_at
            return

        raw = data.get("counters") or {}
        _counters = {key: max(0, int(raw.get(key, 0) or 0)) for key in COUNTER_KEYS}
        _started_at = str(data.get("started_at") or _now_iso())
        _updated_at = str(data.get("updated_at") or _started_at)


def reset() -> None:
    global _counters, _started_at, _updated_at
    with _lock:
        _counters = dict.fromkeys(COUNTER_KEYS, 0)
        _started_at = _now_iso()
        _updated_at = _started_at
        try:
            _save_locked()
        except OSError as exc:
            logger.warning("Не удалось сохранить сброс статистики: %s", exc)


def incr(key: str) -> None:
    global _updated_at
    if key not in COUNTER_KEYS:
        raise ValueError(f"Неизвестный счётчик статистики: {key}")
    with _lock:
        _counters[key] += 1
        _updated_at = _now_iso()
        try:
            _save_locked()
        except OSError as exc:
            logger.warning("Не удалось сохранить статистику: %s", exc)


def snapshot() -> dict[str, Any]:
    with _lock:
        counters = dict(_counters)
        started = _started_at
        updated = _updated_at

    exact = counters["cache_exact_hits"]
    fuzzy = counters["cache_fuzzy_hits"]
    misses = counters["cache_misses"]
    cache_requests = exact + fuzzy + misses
    hits = exact + fuzzy
    gemini_calls = (
        counters["embedding_query_calls"]
        + counters["embedding_document_calls"]
        + counters["description_calls"]
    )
    return {
        "started_at": started,
        "updated_at": updated,
        **counters,
        "cache_requests": cache_requests,
        "cache_hit_rate": round(hits / cache_requests, 4) if cache_requests else 0.0,
        "gemini_calls": gemini_calls,
        "gemini_errors": counters["embedding_errors"] + counters["description_errors"],
    }


load()
