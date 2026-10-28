from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_MAX_CAPTION = 1000


def _client() -> httpx.Client:
    return httpx.Client(proxy=settings.socks5_proxy, timeout=_TIMEOUT)


def _caption(record: dict[str, Any], admin_url: str) -> str:
    filename = html.escape(str(record.get("original_filename") or "без имени"))
    tags = [str(tag) for tag in record.get("tags") or []]
    tag_line = " ".join(f"#{html.escape(tag)}" for tag in tags)
    width = record.get("width") or "?"
    height = record.get("height") or "?"
    size_kb = max(1, int(record.get("size") or 0) // 1024)
    minutes = max(1, settings.pending_ttl_seconds // 60)
    lines = [
        "<b>Новый мем на модерации</b>",
        f"Файл: <code>{filename}</code>",
        f"Размер: {width}x{height}, {size_kb} КБ",
    ]
    if tag_line:
        lines.append(f"Теги: {tag_line}")
    lines.append(f"Через {minutes} мин опубликуется автоматически.")
    lines.append(f'<a href="{html.escape(admin_url)}">Открыть админку</a>')
    caption = "\n".join(lines)
    return caption[:_MAX_CAPTION]


def _post(token: str, method: str, chat_id: str, caption: str, path: Path, mime_type: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    field = "photo" if method == "sendPhoto" else "document"
    try:
        content = path.read_bytes()
    except OSError as exc:
        logger.warning("Не удалось прочитать файл для Telegram: %s", exc)
        return False
    files = {field: (path.name, content, mime_type)}
    with _client() as client:
        response = client.post(url, data=data, files=files)
    if response.status_code == 200:
        payload = response.json()
        if payload.get("ok"):
            return True
    logger.warning("Telegram %s вернул %s", method, response.status_code)
    return False


def notify_pending(record: dict[str, Any], admin_url: str) -> bool:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_admin_chat_id
    if not token or not chat_id:
        logger.info("Telegram не настроен, уведомление о модерации пропущено")
        return False

    try:
        path = settings.pending_dir / str(record["stored_name"])
    except KeyError:
        return False
    if not path.is_file():
        logger.warning("Файл модерации не найден: %s", path)
        return False

    mime_type = str(record.get("mime_type") or "application/octet-stream")
    caption = _caption(record, admin_url)
    try:
        if _post(token, "sendPhoto", chat_id, caption, path, mime_type):
            return True
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Telegram sendPhoto не удался: %s", exc)
    try:
        return _post(token, "sendDocument", chat_id, caption, path, mime_type)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Telegram sendDocument не удался: %s", exc)
        return False
