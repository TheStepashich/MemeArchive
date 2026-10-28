from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from google import genai
from google.genai import types
from google.genai.errors import ClientError
from rapidfuzz import fuzz

from app import embed_cache, stats
from app.config import settings
from app.errors import UpstreamAIError

logger = logging.getLogger(__name__)

_MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "gif": "image/gif",
}

_SPACE_RE = re.compile(r"\s+")

_EMBED_CACHE: OrderedDict[tuple[str, str, str], tuple[float, ...]] = OrderedDict()
_EMBED_CACHE_MAXSIZE = 4096
_EMBED_FUZZY_THRESHOLD = 90.0

# Дефолтный сон, если не удалось распарсить точное время из ошибки
_DEFAULT_SLEEP_SECS = 300

# Регулярные выражения для поиска времени ожидания в тексте ошибки
_RETRY_SECONDS_RE = re.compile(r"retryDelay':\s*'(\d+)s'")
_RETRY_HUMAN_RE = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?")

# Бюджет повторов при 429: не зацикливаемся навсегда на исчерпанной квоте
_MAX_RATE_LIMIT_RETRIES = 3
_MAX_RATE_LIMIT_SLEEP = 900

_block_lock = threading.Lock()
_blocked_until: dict[str, float] = {"description": 0.0, "embedding": 0.0}


def _mark_blocked(kind: str, seconds: int) -> None:
    until = time.monotonic() + max(0, seconds)
    with _block_lock:
        _blocked_until[kind] = max(_blocked_until[kind], until)


def _clear_blocked(kind: str) -> None:
    with _block_lock:
        _blocked_until[kind] = 0.0


def reset_blocked() -> None:
    with _block_lock:
        _blocked_until["description"] = 0.0
        _blocked_until["embedding"] = 0.0


def upstream_blocked_seconds() -> int:
    with _block_lock:
        until = max(_blocked_until.values())
    return max(0, math.ceil(until - time.monotonic()))

if (restored := embed_cache.load_into(_EMBED_CACHE)) > 0:
    logger.info("Кэш эмбеддингов восстановлен с диска: %d записей", restored)


def _parse_retry_delay(error_message: str) -> int:
    """Пытается достать время ожидания в секундах из текста ошибки Gemini API."""
    if not error_message:
        return _DEFAULT_SLEEP_SECS

    # 1. Пробуем найти 'retryDelay': '995s'
    if match := _RETRY_SECONDS_RE.search(error_message):
        return int(match.group(1)) + 5  # Добавляем 5 секунд буфера

    # 2. Пробуем найти человекочитаемый текст вроде "Please retry in 16m35.09s"
    if match := _RETRY_HUMAN_RE.search(error_message):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = float(match.group(3) or 0.0)
        total_secs = int(hours * 3600 + minutes * 60 + seconds)
        return total_secs + 5 if total_secs > 0 else _DEFAULT_SLEEP_SECS

    return _DEFAULT_SLEEP_SECS


def _redact_proxy(proxy: str) -> str:
    parsed = urlparse(proxy)
    host = parsed.hostname or "unknown"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


@lru_cache(maxsize=1)
def get_http_options() -> types.HttpOptions:
    options = types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=settings.gemini_retry_attempts,
            http_status_codes=[408, 500, 502, 503, 504],
        )
    )

    proxy = settings.socks5_proxy
    if not proxy:
        return options

    logger.info("Gemini requests use SOCKS proxy %s", _redact_proxy(proxy))
    options.client_args = {"proxy": proxy}
    options.async_client_args = {"proxy": proxy}
    return options



@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    return genai.Client(api_key=settings.api_key, http_options=get_http_options())


def get_img_description(image_path: Path) -> str:
    if not image_path.is_file():
        raise UpstreamAIError(f"Изображение не найдено: {image_path}")

    mime_type = _MIME_TYPES.get(image_path.suffix.lower().lstrip("."))
    if not mime_type:
        raise UpstreamAIError(f"Неизвестный тип изображения: {image_path.suffix}")

    data = image_path.read_bytes()

    rate_limit_retries = 0
    while True:
        try:
            response = get_client().models.generate_content(
                model=settings.recognizing_model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    settings.i2t_prompt,
                ],
            )
            break
        except ClientError as exc:
            if exc.code == 429:
                stats.incr("description_rate_limits")
                sleep_secs = _parse_retry_delay(str(exc))
                rate_limit_retries += 1
                if rate_limit_retries > _MAX_RATE_LIMIT_RETRIES or sleep_secs > _MAX_RATE_LIMIT_SLEEP:
                    logger.warning(
                        "Gemini 429 budget exhausted (%d retries, next pause %ds), giving up this call",
                        rate_limit_retries, sleep_secs,
                    )
                    _mark_blocked("description", sleep_secs)
                    raise UpstreamAIError("Не удалось получить описание изображения.") from exc
                logger.warning(
                    "Превышен лимит запросов Gemini API (429) для %s. Динамическая пауза: %d сек (%d мин). Ждем...",
                    image_path, sleep_secs, sleep_secs // 60
                )
                time.sleep(sleep_secs)
                continue

            stats.incr("description_errors")
            logger.exception("Gemini API client error for %s", image_path)
            raise UpstreamAIError("Ошибка со стороны клиента Gemini API.") from exc
        except Exception as exc:
            stats.incr("description_errors")
            logger.exception("Gemini image description failed for %s", image_path)
            raise UpstreamAIError("Не удалось получить описание изображения.") from exc

    _clear_blocked("description")
    description = (response.text or "").strip()
    if not description:
        stats.incr("description_errors")
        raise UpstreamAIError("Модель вернула пустое описание изображения.")
    stats.incr("description_calls")
    return description


def _normalize_query(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return _SPACE_RE.sub(" ", text.strip()).lower()


def _cache_get(normalized: str, task_type: str, model: str) -> tuple[float, ...] | None:
    if not normalized:
        return None
    key = (normalized, task_type, model)
    cached = _EMBED_CACHE.get(key)
    if cached is not None:
        _EMBED_CACHE.move_to_end(key)
        embed_cache.touch(normalized, task_type, model)
        stats.incr("cache_exact_hits")
        return cached

    for (cached_key, cached_vec) in _EMBED_CACHE.items():
        cached_norm, cached_task, cached_model = cached_key
        if cached_task != task_type or cached_model != model:
            continue
        score = fuzz.token_sort_ratio(normalized, cached_norm)
        if score >= _EMBED_FUZZY_THRESHOLD:
            logger.debug("Embedding cache fuzzy hit: %d%% for '%s' ~ '%s'", int(score), normalized, cached_norm)
            _EMBED_CACHE.move_to_end(cached_key)
            embed_cache.touch(cached_norm, cached_task, cached_model)
            stats.incr("cache_fuzzy_hits")
            return cached_vec
    return None


def _cache_set(normalized: str, task_type: str, model: str, vector: tuple[float, ...]) -> None:
    if not normalized:
        return
    key = (normalized, task_type, model)
    _EMBED_CACHE[key] = vector
    _EMBED_CACHE.move_to_end(key)
    embed_cache.persist(normalized, task_type, model, vector)
    while len(_EMBED_CACHE) > _EMBED_CACHE_MAXSIZE:
        oldest_key, _ = _EMBED_CACHE.popitem(last=False)
        embed_cache.delete(*oldest_key)


def embed_cache_size() -> int:
    return len(_EMBED_CACHE)


def _embed_uncached(normalized: str, task_type: str, model: str, bypass_delay: bool = False) -> tuple[float, ...]:
    if not normalized:
        raise UpstreamAIError("Текст для эмбеддинга пуст.")

    rate_limit_retries = 0
    while True:
        try:
            response = get_client().models.embed_content(
                model=model,
                contents=normalized,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            break
        except ClientError as exc:
            if exc.code == 429:
                stats.incr("embedding_rate_limits")
                if bypass_delay:
                    logger.error("Превышен лимит эмбеддингов (429) в UI-запросе. Сон пропущен.")
                    raise UpstreamAIError("Превышен лимит запросов к API. Попробуйте позже.") from exc

                sleep_secs = _parse_retry_delay(str(exc))
                rate_limit_retries += 1
                if rate_limit_retries > _MAX_RATE_LIMIT_RETRIES or sleep_secs > _MAX_RATE_LIMIT_SLEEP:
                    logger.warning(
                        "Gemini 429 budget exhausted (%d retries, next pause %ds), giving up this call",
                        rate_limit_retries, sleep_secs,
                    )
                    _mark_blocked("embedding", sleep_secs)
                    raise UpstreamAIError("Не удалось построить эмбеддинг.") from exc
                logger.warning(
                    "Превышен лимит эмбеддингов Gemini API (429). Динамическая пауза: %d сек (%d мин). Ждем...",
                    sleep_secs, sleep_secs // 60
                )
                time.sleep(sleep_secs)
                continue
            stats.incr("embedding_errors")
            logger.exception("Gemini embedding client error")
            raise UpstreamAIError("Ошибка со стороны клиента Gemini API при создании эмбеддинга.") from exc
        except Exception as exc:
            stats.incr("embedding_errors")
            logger.exception("Gemini embedding failed")
            raise UpstreamAIError("Не удалось построить эмбеддинг.") from exc

    _clear_blocked("embedding")
    embeddings = response.embeddings or []
    if not embeddings or not embeddings[0].values:
        stats.incr("embedding_errors")
        raise UpstreamAIError("Модель вернула пустой эмбеддинг.")

    counter = (
        "embedding_document_calls"
        if task_type == settings.embedding_task_document
        else "embedding_query_calls"
    )
    stats.incr(counter)
    return tuple(float(value) for value in embeddings[0].values)


def get_embedding(text: str, task_type: str, bypass_delay: bool = False) -> list[float]:
    if not isinstance(text, str) or not text.strip():
        raise UpstreamAIError("Текст для эмбеддинга пуст.")

    normalized = _normalize_query(text)
    model = settings.embedding_model
    cached = _cache_get(normalized, task_type, model)
    if cached is not None:
        return list(cached)

    stats.incr("cache_misses")
    vector = _embed_uncached(normalized, task_type, model, bypass_delay=bypass_delay)
    _cache_set(normalized, task_type, model, vector)
    return list(vector)
