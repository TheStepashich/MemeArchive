import base64
import io

from fastapi.testclient import TestClient
from PIL import Image

from app import ai, captcha, db, stats
from app.config import settings


def png_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def mock_ai(monkeypatch) -> None:
    monkeypatch.setattr(ai, "get_img_description", lambda path: "funny cat")
    monkeypatch.setattr(ai, "get_embedding", lambda text, task_type, bypass_delay=False: [1.0, 0.0])


def make_client(monkeypatch, tmp_path, *, captcha_enabled: bool = True) -> TestClient:
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "meme_in_dir", tmp_path / "memes")
    monkeypatch.setattr(settings, "stats_file", tmp_path / "stats.json")
    monkeypatch.setattr(settings, "embed_cache_file", tmp_path / "embed.db")
    monkeypatch.setattr(settings, "scan_interval", 0)
    monkeypatch.setattr(settings, "captcha_enabled", captcha_enabled)
    monkeypatch.setattr(settings, "pending_ttl_seconds", 0)
    monkeypatch.setattr(settings, "admin_token", "test-admin")
    monkeypatch.setattr(settings, "telegram_bot_token", None)
    monkeypatch.setattr(settings, "telegram_admin_chat_id", None)
    db.get_collection.cache_clear()
    ai.reset_blocked()
    captcha.reset()

    from app.main import app

    return TestClient(app)


def test_captcha_renders_png(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha, "_random_answer", lambda: "3248")
    with make_client(monkeypatch, tmp_path) as client:
        response = client.get("/captcha")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["id"]
    assert payload["expires_in"] == settings.captcha_ttl_seconds
    encoded = payload["image"].split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.format == "PNG"
        assert image.width == 240
        assert image.height == 84


def test_captcha_required_and_single_use(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha, "_random_answer", lambda: "3248")
    mock_ai(monkeypatch)
    with make_client(monkeypatch, tmp_path) as client:
        failures_before = stats.snapshot()["captcha_failures"]

        missing = client.post(
            "/add",
            files={"file": ("meme.png", png_bytes(), "image/png")},
        )
        assert missing.status_code == 400
        assert "код" in missing.json()["detail"].lower()

        challenge = client.get("/captcha").json()
        added = client.post(
            "/add",
            files={"file": ("meme.png", png_bytes(), "image/png")},
            data={"captcha_id": challenge["id"], "captcha_answer": "3248"},
        )
        assert added.status_code == 200, added.text
        assert added.json()["pending"] is False

        replay = client.post(
            "/add",
            files={"file": ("other.png", png_bytes((1, 2, 3)), "image/png")},
            data={"captcha_id": challenge["id"], "captcha_answer": "3248"},
        )
        assert replay.status_code == 400
        assert stats.snapshot()["captcha_failures"] == failures_before + 2


def test_number_to_words():
    assert captcha._number_to_words(3248).find("тысяча") > -1
    assert captcha._number_to_words(100).find("сто") > -1
    assert captcha._number_to_words(42).find("сорок") > -1


def test_captcha_can_be_disabled(monkeypatch, tmp_path):
    mock_ai(monkeypatch)
    with make_client(monkeypatch, tmp_path, captcha_enabled=False) as client:
        assert client.get("/captcha").status_code == 404
        added = client.post(
            "/add",
            files={"file": ("meme.png", png_bytes(), "image/png")},
        )
        assert added.status_code == 200, added.text
        assert added.json()["pending"] is False


def test_public_config(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        payload = client.get("/config").json()
    assert payload["captcha_enabled"] is True
    assert payload["pending_enabled"] is False
    assert payload["pending_ttl_seconds"] == 0
