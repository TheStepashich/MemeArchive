from __future__ import annotations

import logging
import random
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "images"


@lru_cache(maxsize=1)
def get_collection() -> chromadb.Collection:
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("ChromaDB ready at %s (%d items)", settings.chroma_dir, collection.count())
    return collection


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if not isinstance(value, list) or value
    }


def db_add(
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> None:
    if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
        raise ValueError("Длины ids, embeddings, documents и metadatas должны совпадать.")

    get_collection().upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=[_clean_metadata(metadata) for metadata in metadatas],
    )


def db_get(ids: list[str]) -> dict[str, Any]:
    if not ids:
        return {"ids": [], "documents": [], "metadatas": []}
    result = get_collection().get(
        ids=ids,
        include=["documents", "metadatas"],
    )
    return {
        "ids": result.get("ids") or [],
        "documents": result.get("documents") or [],
        "metadatas": result.get("metadatas") or [],
    }


def db_delete(ids: list[str]) -> None:
    if ids:
        get_collection().delete(ids=ids)


def db_update_metadata(image_id: str, metadata: dict[str, Any]) -> None:
    get_collection().update(ids=[image_id], metadatas=[_clean_metadata(metadata)])


def db_search(
    query_embedding: list[float],
    n_results: int,
    where: dict[str, Any] | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    collection = get_collection()
    total = collection.count()
    if total == 0:
        return {"ids": [], "distances": [], "metadatas": [], "documents": []}

    fetch = min(total, n_results + offset)
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=fetch,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    ids = result.get("ids") or [[]]
    distances = result.get("distances") or [[]]
    metadatas = result.get("metadatas") or [[]]
    documents = result.get("documents") or [[]]

    return {
        "ids": ids[0][offset:offset + n_results],
        "distances": distances[0][offset:offset + n_results],
        "metadatas": metadatas[0][offset:offset + n_results],
        "documents": documents[0][offset:offset + n_results],
    }


def db_count(where: dict[str, Any] | None = None) -> int:
    if where is None:
        return get_collection().count()
    return len(get_collection().get(where=where, include=[]).get("ids") or [])


def db_list(limit: int, offset: int = 0, where: dict[str, Any] | None = None) -> dict[str, Any]:
    result = get_collection().get(
        limit=limit,
        offset=offset,
        where=where,
        include=["documents", "metadatas"],
    )
    return {
        "ids": result.get("ids") or [],
        "documents": result.get("documents") or [],
        "metadatas": result.get("metadatas") or [],
    }


def db_get_random() -> dict[str, Any] | None:
    collection = get_collection()
    total = collection.count()
    if total == 0:
        return None
    offset = random.randint(0, total - 1)
    result = collection.get(limit=1, offset=offset, include=["documents", "metadatas"])
    ids = result.get("ids") or []
    if not ids:
        return None
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    return {
        "id": ids[0],
        "document": documents[0] if documents else "",
        "metadata": metadatas[0] if metadatas else {},
    }


def db_get_embedding(image_id: str) -> list[float] | None:
    result = get_collection().get(ids=[image_id], include=["embeddings"])
    embeddings = result.get("embeddings")
    if embeddings is None:
        return None
    try:
        if len(embeddings) == 0:
            return None
    except TypeError:
        pass
    first = embeddings[0]
    if first is None:
        return None
    try:
        if len(first) == 0:
            return None
    except TypeError:
        pass
    if isinstance(first, (list, tuple)):
        return [float(v) for v in first]
    try:
        return [float(v) for v in first]
    except (TypeError, ValueError):
        return None


def db_get_all() -> dict[str, Any]:
    result = get_collection().get(include=["documents", "metadatas"])
    return {
        "ids": result.get("ids") or [],
        "documents": result.get("documents") or [],
        "metadatas": result.get("metadatas") or [],
    }
