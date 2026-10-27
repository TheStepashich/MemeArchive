from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.config import settings
from app.errors import ImageValidationError, NotFoundError, PayloadTooLargeError

ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "BMP": ("bmp", "image/bmp"),
    "GIF": ("gif", "image/gif"),
}
ALLOWED_EXTENSIONS = {ext for ext, _ in ALLOWED_FORMATS.values()}

_TAG_RE = re.compile(r"[^\w\s+.-]", flags=re.UNICODE)
_MAX_TAGS = 20
_MAX_TAG_LENGTH = 50


@dataclass(frozen=True)
class ImageInfo:
    content_hash: str
    extension: str
    mime_type: str
    width: int
    height: int
    size: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_image(data: bytes, max_bytes: int | None = None, max_pixels: int | None = None) -> ImageInfo:
    if not data:
        raise ImageValidationError("Файл пуст.")

    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes
    if len(data) > limit:
        raise PayloadTooLargeError(f"Файл больше {limit // (1024 * 1024)} МБ.")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageValidationError("Файл не является корректным изображением.") from exc

    if image_format not in ALLOWED_FORMATS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ImageValidationError(f"Формат {image_format or 'неизвестен'} не поддерживается. Допустимо: {allowed}.")

    pixels_limit = max_pixels if max_pixels is not None else settings.max_image_pixels
    if width * height > pixels_limit:
        raise ImageValidationError("Слишком большое разрешение изображения.")

    extension, mime_type = ALLOWED_FORMATS[image_format]
    return ImageInfo(
        content_hash=sha256_bytes(data),
        extension=extension,
        mime_type=mime_type,
        width=width,
        height=height,
        size=len(data),
    )


def safe_upload_path(filename: str) -> Path:
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise NotFoundError("Изображение не найдено.")
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise NotFoundError("Изображение не найдено.")

    base = settings.uploads_dir.resolve()
    candidate = (base / filename).resolve()
    if candidate.parent != base:
        raise NotFoundError("Изображение не найдено.")
    return candidate


def safe_original_filename(filename: str | None) -> str:
    name = Path(filename or "upload").name.strip()
    return (name or "upload")[:255]


def parse_tags(tags: str | Iterable[str] | None) -> list[str]:
    if tags is None:
        raw: list[str] = []
    elif isinstance(tags, str):
        raw = tags.split(",")
    else:
        raw = []
        for item in tags:
            raw.extend(str(item).split(","))

    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = _TAG_RE.sub("", item).strip()
        tag = re.sub(r"\s+", " ", tag)[:_MAX_TAG_LENGTH]
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= _MAX_TAGS:
            break
    return result


def image_path_from_metadata(metadata: dict[str, Any] | None) -> Path:
    metadata = metadata or {}
    stored_name = metadata.get("stored_name")
    if not stored_name:
        source = str(metadata.get("source") or "")
        stored_name = Path(source).name
    return safe_upload_path(str(stored_name))


def metadata_tags(metadata: dict[str, Any] | None) -> list[str]:
    value = (metadata or {}).get("tags") or []
    if isinstance(value, str):
        return parse_tags(value)
    return [str(tag) for tag in value]
