from __future__ import annotations

import argparse
import logging

from app import ai, db
from app.config import settings
from app.errors import NotFoundError
from app.images import image_path_from_metadata

logger = logging.getLogger(__name__)


def reindex(prune: bool = False) -> None:
    data = db.db_get_all()
    ids = data["ids"]
    documents = data["documents"]
    metadatas = data["metadatas"]

    if not ids:
        logger.info("Коллекция пуста, переиндексировать нечего.")
        return

    to_prune: list[str] = []
    batch_ids: list[str] = []
    batch_docs: list[str] = []
    batch_embeddings: list[list[float]] = []
    batch_metadatas: list[dict] = []

    for image_id, document, metadata in zip(ids, documents, metadatas):
        metadata = metadata or {}
        if prune:
            try:
                path = image_path_from_metadata(metadata)
                exists = path.is_file()
            except (NotFoundError, OSError):
                exists = False
            if not exists:
                to_prune.append(image_id)
                continue

        if not document:
            logger.warning("Пропуск %s: нет текста для эмбеддинга", image_id)
            continue

        embedding = ai.get_embedding(document, settings.embedding_task_document)
        batch_ids.append(image_id)
        batch_docs.append(document)
        batch_embeddings.append(embedding)
        batch_metadatas.append(metadata)

        if len(batch_ids) >= 32:
            db.db_add(batch_ids, batch_embeddings, batch_docs, batch_metadatas)
            logger.info("Переиндексировано %d записей", len(batch_ids))
            batch_ids, batch_docs, batch_embeddings, batch_metadatas = [], [], [], []

    if batch_ids:
        db.db_add(batch_ids, batch_embeddings, batch_docs, batch_metadatas)
        logger.info("Переиндексировано %d записей", len(batch_ids))

    if to_prune:
        db.db_delete(to_prune)
        logger.info("Удалено %d записей без исходных файлов", len(to_prune))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Пересчитать эмбеддинги для всех изображений.")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Удалить записи, у которых отсутствует исходный файл.",
    )
    args = parser.parse_args()
    reindex(prune=args.prune)


if __name__ == "__main__":
    main()
