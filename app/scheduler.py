from __future__ import annotations

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.ingest import add_dir

logger = logging.getLogger(__name__)


async def periodic_ingest(stop: asyncio.Event) -> None:
    if settings.scan_interval <= 0:
        logger.info("Периодический импорт отключён (SCAN_INTERVAL=0)")
        return

    while not stop.is_set():
        try:
            await run_in_threadpool(add_dir)
        except Exception:
            logger.exception("Ошибка фонового импорта")

        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.scan_interval)
        except TimeoutError:
            pass
