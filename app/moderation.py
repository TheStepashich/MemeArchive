from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool

from app import ai, pending, service, stats, telegram
from app.config import settings
from app.errors import NotFoundError, TooManyRequestsError, UpstreamAIError
from app.images import inspect_image, parse_tags

logger = logging.getLogger(__name__)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def _pending_record(record: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "id": str(record["id"]),
        "description": "",
        "stored_name": str(record.get("stored_name") or ""),
        "original_filename": record.get("original_filename"),
        "source": str(pending.image_path(record)),
        "tags": list(record.get("tags") or []),
        "favorite": False,
        "width": record.get("width"),
        "height": record.get("height"),
        "size": record.get("size"),
        "mime_type": record.get("mime_type"),
        "content_hash": str(record["id"]),
        "created_at": record.get("created_at"),
        "distance": None,
        "duplicate": duplicate,
        "pending": True,
        "expires_at": _iso(float(record.get("expires_at") or 0)),
    }


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def submit_upload(
    data: bytes,
    original_filename: str | None,
    tags: str,
    admin_url: str,
) -> dict[str, Any]:
    info = inspect_image(data)

    existing = service.find_image(info.content_hash)
    if existing is not None:
        return service.add_image(data, original_filename, tags, added_via="web")

    queued = pending.get(info.content_hash)
    if queued is not None:
        return _pending_record(queued, duplicate=True)

    if pending.count() >= settings.max_pending_items:
        raise TooManyRequestsError(
            "Очередь модерации заполнена. Попробуйте загрузить мем позже."
        )

    stored_name = f"{info.content_hash}.{info.extension}"
    _write_atomic(settings.pending_dir / stored_name, data)

    now = time.time()
    record = {
        "id": info.content_hash,
        "stored_name": stored_name,
        "original_filename": original_filename,
        "tags": parse_tags(tags),
        "size": info.size,
        "width": info.width,
        "height": info.height,
        "mime_type": info.mime_type,
        "created_at": _iso(now),
        "expires_at": now + settings.pending_ttl_seconds,
    }
    pending.add(record)
    stats.incr("uploads_received")

    try:
        telegram.notify_pending(record, admin_url)
    except Exception:
        logger.exception("Не удалось отправить уведомление в Telegram")

    logger.info("Мем %s отправлен на модерацию (%s)", record["id"], original_filename)
    return _pending_record(record)


def approve(record: dict[str, Any], *, manual: bool = True) -> dict[str, Any]:
    item_id = str(record["id"])
    path = pending.image_path(record)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        pending.remove(item_id)
        raise NotFoundError("Файл ожидает модерации.") from exc

    result = service.add_image(
        data,
        record.get("original_filename"),
        record.get("tags") or [],
        added_via="web",
    )
    pending.remove(item_id)
    path.unlink(missing_ok=True)
    stats.incr("uploads_manual_approved" if manual else "uploads_auto_approved")
    logger.info("Мем %s опубликован (%s)", item_id, "вручную" if manual else "автоматически")
    return result


def reject(record: dict[str, Any]) -> None:
    item_id = str(record["id"])
    path = pending.image_path(record)
    pending.remove(item_id)
    path.unlink(missing_ok=True)
    stats.incr("uploads_rejected")
    logger.info("Мем %s отклонён", item_id)


def auto_approve_due() -> int:
    if not settings.pending_enabled:
        return 0
    if ai.upstream_blocked_seconds() > 0:
        return 0

    approved = 0
    for record in pending.due(time.time()):
        try:
            approve(record, manual=False)
        except UpstreamAIError as exc:
            logger.warning("Автопубликация приостановлена: %s", exc.message)
            break
        except Exception:
            logger.exception("Не удалось опубликовать мем %s", record.get("id"))
            continue
        approved += 1
    return approved


async def auto_approve_loop(stop: asyncio.Event) -> None:
    logger.info(
        "Модерация включена: автопубликация через %d мин, проверка каждые %d сек",
        settings.pending_ttl_seconds // 60,
        settings.pending_check_interval,
    )
    while not stop.is_set():
        try:
            approved = await run_in_threadpool(auto_approve_due)
            if approved:
                logger.info("Автоматически опубликовано мемов: %d", approved)
        except Exception:
            logger.exception("Ошибка цикла автопубликации")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.pending_check_interval)
        except TimeoutError:
            continue
