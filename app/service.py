from __future__ import annotations

import logging
import os
import random
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import ai, db
from app.config import settings
from app.errors import NotFoundError
from app.images import (
    ImageInfo,
    extract_tags,
    image_path_from_metadata,
    inspect_image,
    metadata_tags,
    parse_tags,
    safe_original_filename,
    safe_upload_path,
)

logger = logging.getLogger(__name__)


def _build_record(
    image_id: str,
    description: str,
    metadata: dict[str, Any],
    *,
    distance: float | None = None,
    duplicate: bool = False,
) -> dict[str, Any]:
    stored_name = metadata.get("stored_name")
    if not stored_name:
        stored_name = Path(str(metadata.get("source") or "")).name

    mime_type = metadata.get("mime_type")
    if not mime_type:
        suffix = Path(str(stored_name)).suffix.lower().lstrip(".")
        mime_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "gif": "image/gif",
        }.get(suffix)

    created_at = metadata.get("created_at")
    if not created_at:
        source = Path(str(metadata.get("source") or settings.uploads_dir / str(stored_name)))
        try:
            created_at = datetime.fromtimestamp(source.stat().st_mtime, UTC).isoformat(timespec="seconds")
        except OSError:
            created_at = None

    return {
        "id": image_id,
        "description": description,
        "stored_name": stored_name,
        "original_filename": metadata.get("original_filename"),
        "source": metadata.get("source") or str(settings.uploads_dir / str(stored_name)),
        "tags": metadata_tags(metadata),
        "favorite": bool(metadata.get("favorite", False)),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "size": metadata.get("size"),
        "mime_type": mime_type,
        "content_hash": metadata.get("content_hash") or image_id,
        "created_at": created_at,
        "distance": distance,
        "duplicate": duplicate,
        "pending": bool(metadata.get("pending", False)),
    }


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _existing_record(image_id: str) -> tuple[str, dict[str, Any]] | None:
    result = db.db_get([image_id])
    if not result["ids"]:
        return None
    return result["documents"][0], result["metadatas"][0] or {}


def add_image(
    data: bytes,
    original_filename: str | None,
    tags: str | Iterable[str] | None = None,
    favorite: bool = False,
    added_via: str = "web",
) -> dict[str, Any]:
    info = inspect_image(data)
    existing = _existing_record(info.content_hash)

    if existing is not None:
        description, metadata = existing
        metadata = dict(metadata)
        stored_name = metadata.get("stored_name") or Path(str(metadata.get("source") or "")).name
        metadata["stored_name"] = stored_name
        metadata["source"] = str(settings.uploads_dir / stored_name)

        path = image_path_from_metadata(metadata)
        if not path.is_file():
            _write_atomic(path, data)

        merged_tags = parse_tags([*metadata_tags(metadata), *parse_tags(tags)])
        changed = merged_tags != metadata_tags(metadata)
        if merged_tags:
            metadata["tags"] = merged_tags
            changed = True
        if favorite and not metadata.get("favorite"):
            metadata["favorite"] = True
            changed = True
        if changed:
            db.db_update_metadata(info.content_hash, metadata)

        return _build_record(info.content_hash, description, metadata, duplicate=True)

    stored_name = f"{info.content_hash}.{info.extension}"
    path = safe_upload_path(stored_name)
    _write_atomic(path, data)

    try:
        description = ai.get_img_description(path)
        embedding = ai.get_embedding(description, settings.embedding_task_document)
        metadata = _metadata(
            info=info,
            stored_name=stored_name,
            original_filename=safe_original_filename(original_filename),
            tags=parse_tags([*parse_tags(tags), *extract_tags(description)]),
            favorite=favorite,
            added_via=added_via,
        )
        db.db_add(
            ids=[info.content_hash],
            embeddings=[embedding],
            documents=[description],
            metadatas=[metadata],
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return _build_record(info.content_hash, description, metadata)


def _metadata(
    *,
    info: ImageInfo,
    stored_name: str,
    original_filename: str,
    tags: list[str],
    favorite: bool,
    added_via: str = "web",
) -> dict[str, Any]:
    metadata = {
        "source": str(settings.uploads_dir / stored_name),
        "stored_name": stored_name,
        "original_filename": original_filename,
        "content_hash": info.content_hash,
        "mime_type": info.mime_type,
        "width": info.width,
        "height": info.height,
        "size": info.size,
        "favorite": favorite,
        "pending": False,
        "added_via": added_via,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if tags:
        metadata["tags"] = tags
    return metadata


def find_image(image_id: str) -> dict[str, Any] | None:
    existing = _existing_record(image_id)
    if existing is None:
        return None
    description, metadata = existing
    return _build_record(image_id, description, metadata)


def get_image(image_id: str) -> dict[str, Any]:
    existing = _existing_record(image_id)
    if existing is None:
        raise NotFoundError("Изображение не найдено.")
    description, metadata = existing
    return _build_record(image_id, description, metadata)


def delete_image(image_id: str) -> None:
    existing = _existing_record(image_id)
    if existing is None:
        raise NotFoundError("Изображение не найдено.")
    _, metadata = existing
    path = image_path_from_metadata(metadata)
    path.unlink(missing_ok=True)
    db.db_delete([image_id])
    logger.info("Deleted image %s (%s)", image_id, path)


def set_favorite(image_id: str, favorite: bool) -> dict[str, Any]:
    existing = _existing_record(image_id)
    if existing is None:
        raise NotFoundError("Изображение не найдено.")
    description, metadata = existing
    metadata = dict(metadata)
    metadata["favorite"] = favorite
    db.db_update_metadata(image_id, metadata)
    return _build_record(image_id, description, metadata)


def _build_where(
    tags: list[str],
    favorite: bool | None,
    pending: bool | None = False,
) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    if pending is not None:
        clauses.append({"pending": pending})
    if favorite is not None:
        clauses.append({"favorite": favorite})
    for tag in tags:
        clauses.append({"tags": {"$contains": tag}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _find_matching_tag(query: str) -> str | None:
    wanted = parse_tags([query])
    if not wanted:
        return None
    wanted_cf = wanted[0].casefold()
    for tag in list_tags():
        if tag.casefold() == wanted_cf:
            return tag
    return None


def _semantic_results(
    query_embedding: list[float],
    normalized_tags: list[str],
    favorite: bool | None,
    n_results: int,
    offset: int,
    exclude_ids: set[str] | None = None,
    pending: bool | None = False,
) -> list[dict[str, Any]]:
    raw = db.db_search(
        query_embedding=query_embedding,
        n_results=n_results,
        where=_build_where(normalized_tags, favorite, pending),
        offset=offset,
    )

    results: list[dict[str, Any]] = []
    for image_id, document, metadata, distance in zip(
        raw["ids"], raw["documents"], raw["metadatas"], raw["distances"]
    ):
        if exclude_ids and image_id in exclude_ids:
            continue
        metadata = metadata or {}
        try:
            path = image_path_from_metadata(metadata)
        except NotFoundError:
            logger.warning("Skipping record with invalid path: %s", image_id)
            continue
        if not path.is_file():
            logger.warning("Skipping record with missing file: %s", image_id)
            continue
        results.append(
            _build_record(
                image_id,
                document or "",
                metadata,
                distance=float(distance),
            )
        )
    return results


def search(
    query: str,
    n_results: int = 5,
    offset: int = 0,
    tags: Iterable[str] | None = None,
    favorite: bool | None = None,
    pending: bool | None = False,
) -> dict[str, Any]:
    normalized_tags = parse_tags(tags)

    matched_tag = _find_matching_tag(query)
    tag_results: list[dict[str, Any]] = []
    exclude_ids: set[str] | None = None

    if matched_tag is not None:
        effective_tags = parse_tags([matched_tag, *normalized_tags])
        where = _build_where(effective_tags, favorite, pending)
        tag_data = list_images(
            limit=max(db.db_count(where), 1),
            offset=0,
            order="new",
            tags=effective_tags,
            favorite=favorite,
            pending=pending,
        )
        tag_results = tag_data["results"]
        exclude_ids = {item["id"] for item in tag_results}

    query_embedding = ai.get_embedding(query, settings.embedding_task_query, bypass_delay=True)
    semantic = _semantic_results(
        query_embedding,
        normalized_tags,
        favorite,
        n_results,
        offset,
        exclude_ids,
        pending,
    )

    return {
        "query": query,
        "results": [*tag_results, *semantic],
        "total": db.db_count(_build_where([], None, pending)),
        "n_results": n_results,
        "offset": offset,
        "matched_tag": matched_tag,
        "matched_tag_count": len(tag_results) if matched_tag else None,
    }


def list_images(
    limit: int = 24,
    offset: int = 0,
    order: str = "new",
    tags: Iterable[str] | None = None,
    favorite: bool | None = None,
    pending: bool | None = False,
) -> dict[str, Any]:
    if favorite is None:
        favorite = True if order == "top" else None
    where = _build_where(parse_tags(tags), favorite, pending)
    total = db.db_count(where)
    take = min(limit, max(0, total - offset))

    if take:
        if order == "old":
            raw = db.db_list(limit=take, offset=offset, where=where)
        else:
            raw = db.db_list(limit=take, offset=total - offset - take, where=where)
            raw = {key: list(reversed(value)) for key, value in raw.items()}
    else:
        raw = {"ids": [], "documents": [], "metadatas": []}

    results: list[dict[str, Any]] = []

    for image_id, document, metadata in zip(raw["ids"], raw["documents"], raw["metadatas"]):
        metadata = metadata or {}
        try:
            path = image_path_from_metadata(metadata)
        except NotFoundError:
            logger.warning("Skipping record with invalid path: %s", image_id)
            continue
        if not path.is_file():
            logger.warning("Skipping record with missing file: %s", image_id)
            continue
        results.append(_build_record(image_id, document or "", metadata))

    return {
        "results": results,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(raw["ids"]),
    }


def get_random_image(pending: bool | None = False) -> dict[str, Any]:
    record = db.db_get_random(where=_build_where([], None, pending))
    if record is None:
        raise NotFoundError("В архиве нет мемов.")
    metadata = record.get("metadata") or {}
    try:
        path = image_path_from_metadata(metadata)
    except NotFoundError:
        raise NotFoundError("Изображение не найдено.")
    if not path.is_file():
        raise NotFoundError("Изображение не найдено.")
    return _build_record(record["id"], record.get("document") or "", metadata)


def get_similar_images(image_id: str, n_results: int = 5) -> dict[str, Any]:
    existing = _existing_record(image_id)
    if existing is None:
        raise NotFoundError("Изображение не найдено.")

    embedding = db.db_get_embedding(image_id)
    if embedding is None:
        # fallback: rebuild from description
        description, metadata = existing
        embedding = ai.get_embedding(description, settings.embedding_task_query)

    raw = db.db_search(
        embedding,
        n_results=n_results + 1,
        where=_build_where([], None, False),
    )
    results: list[dict[str, Any]] = []
    for mid, document, metadata, distance in zip(
        raw["ids"], raw["documents"], raw["metadatas"], raw["distances"]
    ):
        if mid == image_id:
            continue
        metadata = metadata or {}
        try:
            path = image_path_from_metadata(metadata)
        except NotFoundError:
            continue
        if not path.is_file():
            continue
        results.append(_build_record(mid, document or "", metadata, distance=float(distance)))
        if len(results) >= n_results:
            break

    return {"image_id": image_id, "results": results}


def list_tags(limit: int | None = None) -> list[str]:
    data = db.db_get_all()
    tags: dict[str, str] = {}
    for metadata in data["metadatas"]:
        if (metadata or {}).get("pending", False):
            continue
        for tag in metadata_tags(metadata):
            tags.setdefault(tag.casefold(), tag)
    all_tags = sorted(tags.values(), key=str.casefold)
    if limit is None or limit >= len(all_tags):
        return all_tags
    return random.sample(all_tags, limit)
