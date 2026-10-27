from __future__ import annotations

import array
import logging
import sqlite3
import threading
import time
from collections import OrderedDict

from app.config import settings

logger = logging.getLogger(__name__)

MAXSIZE = 4096

_lock = threading.Lock()
_db: sqlite3.Connection | None = None
_initialised = False


def _connect() -> sqlite3.Connection:
    path = settings.embed_cache_file
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS embed_cache (
            query_text TEXT NOT NULL,
            task_type TEXT NOT NULL,
            model TEXT NOT NULL,
            vector BLOB NOT NULL,
            last_used REAL NOT NULL,
            PRIMARY KEY (query_text, task_type, model)
        )
        """
    )
    conn.commit()
    return conn


def ensure() -> None:
    global _db, _initialised
    if _initialised:
        return
    with _lock:
        if _initialised:
            return
        try:
            _db = _connect()
            _initialised = True
            count = int(_db.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0])
            logger.info(
                "Кэш эмбеддингов на диске готов: %s (%d записей)",
                settings.embed_cache_file,
                count,
            )
        except (sqlite3.Error, OSError) as exc:
            _db = None
            _initialised = True
            logger.warning("Кэш эмбеддингов недоступен на диске (%s), режим только в памяти", exc)


def load_into(entries: OrderedDict[tuple[str, str, str], tuple[float, ...]]) -> int:
    ensure()
    if _db is None:
        return 0
    loaded = 0
    with _lock:
        try:
            rows = _db.execute(
                "SELECT query_text, task_type, model, vector FROM embed_cache "
                "ORDER BY last_used ASC LIMIT ?",
                (MAXSIZE,),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("Не удалось загрузить кэш эмбеддингов: %s", exc)
            return 0
        for query_text, task_type, model, blob in rows:
            key = (query_text, task_type, model)
            if key in entries:
                continue
            try:
                entries[key] = tuple(array.array("d", bytes(blob)))
            except (TypeError, ValueError):
                continue
            loaded += 1
    return loaded


def persist(query_text: str, task_type: str, model: str, vector: tuple[float, ...]) -> None:
    ensure()
    if _db is None:
        return
    try:
        blob = array.array("d", vector).tobytes()
    except (TypeError, ValueError):
        return
    with _lock:
        try:
            _db.execute(
                "INSERT INTO embed_cache (query_text, task_type, model, vector, last_used) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(query_text, task_type, model) DO UPDATE SET "
                "vector = excluded.vector, last_used = excluded.last_used",
                (query_text, task_type, model, blob, time.time()),
            )
            _db.commit()
        except sqlite3.Error as exc:
            logger.warning("Не удалось сохранить вектор в кэш: %s", exc)


def touch(query_text: str, task_type: str, model: str) -> None:
    ensure()
    if _db is None:
        return
    with _lock:
        try:
            _db.execute(
                "UPDATE embed_cache SET last_used = ? "
                "WHERE query_text = ? AND task_type = ? AND model = ?",
                (time.time(), query_text, task_type, model),
            )
            _db.commit()
        except sqlite3.Error as exc:
            logger.warning("Не удалось обновить кэш эмбеддингов: %s", exc)


def delete(query_text: str, task_type: str, model: str) -> None:
    ensure()
    if _db is None:
        return
    with _lock:
        try:
            _db.execute(
                "DELETE FROM embed_cache WHERE query_text = ? AND task_type = ? AND model = ?",
                (query_text, task_type, model),
            )
            _db.commit()
        except sqlite3.Error as exc:
            logger.warning("Не удалось удалить запись кэша: %s", exc)


def count() -> int:
    ensure()
    if _db is None:
        return 0
    with _lock:
        try:
            return int(_db.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0])
        except sqlite3.Error:
            return 0
