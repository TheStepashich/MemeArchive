from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from app import service
from app.config import settings
from app.errors import AppError, UpstreamAIError
from app.images import ALLOWED_EXTENSIONS

logger = logging.getLogger(__name__)


def iter_image_files(folder: Path) -> Iterator[Path]:
    if not folder.is_dir():
        logger.warning("Папка с мемами не найдена: %s", folder)
        return

    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        extension = entry.suffix.lower().lstrip(".")
        if extension in ALLOWED_EXTENSIONS:
            yield entry
        else:
            logger.debug("Пропуск файла %s: неподдерживаемое расширение %s", entry.name, extension or "нет")


def add_dir() -> Counter:
    stats: Counter = Counter()
    folder = settings.meme_in_dir
    streak = 0

    for path in iter_image_files(folder):
        stats["seen"] += 1
        try:
            result = service.add_image(path.read_bytes(), path.name)
        except UpstreamAIError as exc:
            logger.warning("Не удалось обработать %s: %s", path.name, exc.message)
            stats["failed"] += 1
            streak += 1
            if streak >= settings.upstream_failure_streak:
                stats["aborted"] += 1
                logger.warning(
                    "Upstream errors in a row reached %d, aborting scan pass for backoff: %s",
                    streak,
                    folder,
                )
                break
            continue
        except AppError as exc:
            logger.warning("Не удалось обработать %s: %s", path.name, exc.message)
            stats["failed"] += 1
            streak = 0
            continue
        except Exception:
            logger.exception("Критическая ошибка при обработке %s", path.name)
            stats["failed"] += 1
            streak = 0
            continue

        streak = 0
        if result["duplicate"]:
            stats["duplicates"] += 1
        else:
            stats["added"] += 1

    if stats["seen"]:
        logger.info(
            "Импорт из %s: добавлено %d, дубликатов %d, ошибок %d",
            folder,
            stats["added"],
            stats["duplicates"],
            stats["failed"],
        )
    return stats
