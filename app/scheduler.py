from __future__ import annotations

import asyncio
import logging
from collections import Counter

from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.ingest import add_dir

logger = logging.getLogger(__name__)


def next_scan_delay(current: float, aborted: bool) -> float:
    base = float(settings.scan_interval)
    cap = max(float(settings.scan_backoff_max), base)
    if not aborted:
        return base
    return min(cap, max(base * 2.0, current * 2.0))


async def periodic_ingest(stop: asyncio.Event) -> None:
    if settings.scan_interval <= 0:
        logger.info("Периодический импорт отключён (SCAN_INTERVAL=0)")
        return

    delay = float(settings.scan_interval)

    while not stop.is_set():
        stats: Counter = Counter()
        try:
            stats = await run_in_threadpool(add_dir)
        except Exception:
            logger.exception("Ошибка фонового импорта")

        aborted = bool(stats.get("aborted"))
        delay = next_scan_delay(delay, aborted)
        if aborted:
            logger.warning("Upstream backoff active, next folder scan in %d seconds", int(delay))

        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
