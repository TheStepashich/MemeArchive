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

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 5
_WIDTH = 300
_HEIGHT = 104
_FONT_SIZE = 58

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
_BACKGROUNDS = ("#E0E7FF", "#F3F4F6", "#FFFFFF", "#FDF4FF", "#F7FEE7")
_INKS = ("#000000", "#7C3AED", "#0EA5E9", "#DB2777", "#65A30D")

_store: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _font() -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, _FONT_SIZE)
    try:
        return ImageFont.load_default(size=_FONT_SIZE)
    except TypeError:
        return ImageFont.load_default()


def _random_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def _render(code: str) -> bytes:
    background = random.choice(_BACKGROUNDS)
    image = Image.new("RGB", (_WIDTH, _HEIGHT), background)
    draw = ImageDraw.Draw(image)

    for _ in range(6):
        points = [(random.uniform(0, _WIDTH), random.uniform(0, _HEIGHT)) for _ in range(3)]
        draw.line(points, fill=random.choice(_INKS), width=random.choice((1, 2)))
    for _ in range(170):
        draw.point(
            (random.uniform(0, _WIDTH), random.uniform(0, _HEIGHT)),
            fill=random.choice(_INKS),
        )

    font = _font()
    spacing = max(34, (_WIDTH - 48) // _CODE_LENGTH)
    offset_x = 20
    for char in code:
        scale = random.uniform(0.85, 1.2)
        glyph = Image.new("RGBA", (max(20, int(spacing * 0.85)), _HEIGHT), (0, 0, 0, 0))
        glyph_draw = ImageDraw.Draw(glyph)
        glyph_draw.text((8, 20), char, font=font, fill=random.choice(_INKS))
        glyph = glyph.resize((max(8, int(glyph.width * scale)), max(8, int(glyph.height * scale))), Image.Resampling.BICUBIC)
        glyph = glyph.rotate(
            random.uniform(-22, 22),
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
        image.paste(glyph, (offset_x, int(random.uniform(-5, 5)) + 22), glyph)
        offset_x += spacing

    draw.rectangle((0, 0, _WIDTH - 1, _HEIGHT - 1), outline="#000000", width=3)
    warp = [
        random.uniform(4, _WIDTH - 4),
        random.uniform(4, _HEIGHT - 4),
        random.uniform(4, _WIDTH - 4),
        random.uniform(4, _HEIGHT - 4),
        random.uniform(4, _WIDTH - 4),
        random.uniform(4, _HEIGHT - 4),
        random.uniform(4, _WIDTH - 4),
        random.uniform(4, _HEIGHT - 4),
    ]
    distorted = image.transform((_WIDTH, _HEIGHT), Image.Transform.QUAD, warp, resample=Image.Resampling.BICUBIC)

    buffer = io.BytesIO()
    distorted.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def new_challenge() -> tuple[str, bytes]:
    challenge_id = secrets.token_urlsafe(16)
    answer = _random_code()
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
    return hmac.compare_digest(expected, answer.strip().upper())


def size() -> int:
    with _lock:
        return len(_store)


def reset() -> None:
    with _lock:
        _store.clear()
