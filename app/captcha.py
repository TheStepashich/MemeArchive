from __future__ import annotations

import hmac
import io
import random
import secrets
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import settings

_WIDTH = 280
_HEIGHT = 96
_FONT_SIZE = 52
_TEXT_SIZE = 24

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
)
_BACKGROUNDS = ("#E0E7FF", "#F3F4F6", "#FFFFFF", "#FDF4FF", "#F7FEE7")
_INKS = ("#000000", "#7C3AED", "#0EA5E9", "#DB2777", "#65A30D")

_store: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()

_ONES = ("", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
_TEENS = (
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
)
_TENS = (
    "",
    "",
    "двадцать",
    "тридцать",
    "сорок",
    "пятьдесят",
    "шестьдесят",
    "семьдесят",
    "восемьдесят",
    "девяносто",
)
_HUNDREDS = (
    "",
    "сто",
    "двести",
    "триста",
    "четыреста",
    "пятьсот",
    "шестьсот",
    "семьсот",
    "восемьсот",
    "девятьсот",
)
_GROUP_NAMES = ("", "тысяча", "миллион")


def _font(size: int = _TEXT_SIZE) -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _sub_hundred(chunk: int) -> str:
    if chunk <= 0:
        return ""
    if chunk < 10:
        return _ONES[chunk]
    if chunk < 20:
        return _TEENS[chunk - 10]
    return f"{_TENS[chunk // 10]} {_ONES[chunk % 10]}".strip()


def _number_to_words(number: int) -> str:
    if number <= 0:
        return "ноль"
    parts: list[str] = []
    group = number
    group_index = 0
    while group > 0:
        chunk = group % 1000
        if chunk > 0:
            words: list[str] = []
            if chunk >= 100:
                words.append(_HUNDREDS[chunk // 100])
                remainder = chunk % 100
            else:
                remainder = chunk
            sub = _sub_hundred(remainder)
            if sub:
                words.append(sub)
            if _GROUP_NAMES[group_index]:
                words.append(_GROUP_NAMES[group_index])
            parts.append(" ".join(words))
        group //= 1000
        group_index += 1
    return " ".join(reversed(parts))


def _random_answer() -> str:
    return str(random.randint(100, 99999))


def _render(answer: str) -> bytes:
    text = _number_to_words(int(answer))
    background = random.choice(_BACKGROUNDS)
    image = Image.new("RGB", (_WIDTH, _HEIGHT), background)
    draw = ImageDraw.Draw(image)

    for _ in range(5):
        points = [(random.randint(0, _WIDTH), random.randint(0, _HEIGHT)) for _ in range(3)]
        draw.line(points, fill=random.choice(_INKS), width=random.choice((1, 1, 2)))
    for _ in range(140):
        draw.point((random.randint(0, _WIDTH), random.randint(0, _HEIGHT)), fill=random.choice(_INKS))

    font_size = _TEXT_SIZE
    font = _font(font_size)
    box = font.getbbox(text)
    while (box[2] - box[0]) > _WIDTH - 16 and font_size > 14:
        font_size -= 1
        font = _font(font_size)
        box = font.getbbox(text)
    text_width = box[2] - box[0]
    text_height = box[3] - box[1]
    x = int((_WIDTH - text_width) / 2 - box[0])
    y = int((_HEIGHT - text_height) / 2 - box[1])
    draw.text((x, y), text, font=font, fill=random.choice(_INKS))

    draw.rectangle((0, 0, _WIDTH - 1, _HEIGHT - 1), outline="#000000", width=3)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def new_challenge() -> tuple[str, bytes]:
    challenge_id = secrets.token_urlsafe(16)
    answer = _random_answer()
    now = time.monotonic()
    expires_at = now + settings.captcha_ttl_seconds
    with _lock:
        expired = [key for key, (_, until) in _store.items() if until <= now]
        for key in expired:
            _store.pop(key, None)
        _store[challenge_id] = (answer, expires_at)
    return challenge_id, _render(answer)


def verify(challenge_id: str | None, answer: str | None) -> bool:
    if not challenge_id or not answer:
        return False
    with _lock:
        entry = _store.pop(challenge_id, None)
    if entry is None:
        return False
    expected, expires_at = entry
    if time.monotonic() > expires_at:
        return False
    return hmac.compare_digest(expected, answer.strip())


def size() -> int:
    with _lock:
        return len(_store)


def reset() -> None:
    with _lock:
        _store.clear()
