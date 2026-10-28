import io
import time

from fastapi.testclient import TestClient
from PIL import Image

from app import ai, captcha, db, moderation, pending, stats
from app.config import settings

ADMIN_HEADERS = {"X-API-Key": "test-admin"}


def png_bytes(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def mock_ai(monkeypatch) -> None:
    monkeypatch.setattr(ai, "get_img_description", lambda path: "funny cat, office")
    monkeypatch.setattr(ai, "get_embedding", lambda text, task_type, bypass_delay=False: [1.0, 0.0, 0.0])


def make_client(monkeypatch, tmp_path, *, pending_ttl: int = 3600) -> TestClient:
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "meme_in_dir", tmp_path / "memes")
    monkeypatch.setattr(settings, "stats_file", tmp_path / "stats.json")
    monkeypatch.setattr(settings, "embed_cache_file", tmp_path / "embed.db")
    monkeypatch.setattr(settings, "scan_interval", 0)
    monkeypatch.setattr(settings, "captcha_enabled", False)
    monkeypatch.setattr(settings, "pending_ttl_seconds", pending_ttl)
    monkeypatch.setattr(settings, "admin_token", "test-admin")
    monkeypatch.setattr(settings, "telegram_bot_token", None)
    monkeypatch.setattr(settings, "telegram_admin_chat_id", None)
    db.get_collection.cache_clear()
    ai.reset_blocked()
    captcha.reset()

    from app.main import app

    return TestClient(app)


def upload(client: TestClient, name: str = "meme.png", color: tuple[int, int, int] = (10, 20, 30), tags: str = "cat"):
    return client.post(
        "/add",
        files={"file": (name, png_bytes(color), "image/png")},
        data={"tags": tags},
    )


def test_upload_goes_to_pending(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        received_before = stats.snapshot()["uploads_received"]
        response = upload(client)

        assert response.status_code == 202, response.text
        record = response.json()
        assert record["pending"] is True
        assert record["duplicate"] is False
        assert record["expires_at"]
        assert pending.count() == 1
        assert pending.image_path(pending.get(record["id"])).is_file()
        assert stats.snapshot()["uploads_received"] == received_before + 1

        assert client.get("/images").json()["total"] == 0
        assert client.get("/tags").json() == []
        assert client.get(f"/images/{record['id']}").status_code == 404

        health = client.get("/health").json()
        assert health["images"] == 0
        assert health["pending"] == 1


def test_pending_duplicate_is_not_queued_twice(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        first = upload(client)
        second = upload(client)

        assert first.status_code == 202
        assert second.status_code == 202
        assert second.json()["duplicate"] is True
        assert second.json()["pending"] is True
        assert pending.count() == 1


def test_pending_limit(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        monkeypatch.setattr(settings, "max_pending_items", 1)
        assert upload(client, color=(1, 1, 1)).status_code == 202
        too_many = upload(client, color=(2, 2, 2))
        assert too_many.status_code == 429


def test_admin_requires_token(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        assert client.get("/api/v1/admin/stats").status_code == 401
        assert client.get("/api/v1/admin/pending").status_code == 401
        assert client.get("/api/v1/admin/stats", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.delete("/images/whatever").status_code == 401
        assert (
            client.patch("/images/whatever/favorite", json={"favorite": True}).status_code == 401
        )

        monkeypatch.setattr(settings, "admin_token", None)
        missing = client.get("/api/v1/admin/stats")
        assert missing.status_code == 503


def test_admin_stats(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        upload(client)
        payload = client.get("/api/v1/admin/stats", headers=ADMIN_HEADERS).json()

    assert payload["images"] == 0
    assert payload["pending_count"] == 1
    assert payload["upstream_blocked_for"] == 0
    assert "uploads_received" in payload
    assert "description_rate_limits" in payload


def test_admin_pending_list_and_image(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        record = upload(client).json()

        listing = client.get("/api/v1/admin/pending", headers=ADMIN_HEADERS).json()
        assert listing["total"] == 1
        assert listing["max_items"] == settings.max_pending_items
        item = listing["items"][0]
        assert item["id"] == record["id"]
        assert item["seconds_left"] > 0
        assert item["image_url"].endswith(f"/api/v1/admin/pending/{record['id']}/image")

        denied = client.get(item["image_url"])
        assert denied.status_code == 401

        image = client.get(item["image_url"], headers=ADMIN_HEADERS)
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.headers["cache-control"] == "no-store"


def test_approve_publishes_pending_meme(monkeypatch, tmp_path):
    mock_ai(monkeypatch)
    with make_client(monkeypatch, tmp_path) as client:
        record = upload(client).json()
        approved_before = stats.snapshot()["uploads_manual_approved"]

        approved = client.post(
            f"/api/v1/admin/pending/{record['id']}/approve",
            headers=ADMIN_HEADERS,
        )
        assert approved.status_code == 200, approved.text
        published = approved.json()
        assert published["pending"] is False
        assert published["description"] == "funny cat, office"
        assert pending.count() == 0
        assert stats.snapshot()["uploads_manual_approved"] == approved_before + 1

        listing = client.get("/images").json()
        assert listing["total"] == 1
        assert listing["results"][0]["id"] == record["id"]
        assert "cat" in client.get("/tags").json()


def test_reject_removes_pending_meme(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        record = upload(client).json()
        path = pending.image_path(pending.get(record["id"]))
        rejected_before = stats.snapshot()["uploads_rejected"]

        response = client.post(
            f"/api/v1/admin/pending/{record['id']}/reject",
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        assert response.json() == {"rejected": True}
        assert pending.count() == 0
        assert not path.exists()
        assert stats.snapshot()["uploads_rejected"] == rejected_before + 1
        assert client.get("/images").json()["total"] == 0


def test_auto_approve_due_respects_block(monkeypatch, tmp_path):
    mock_ai(monkeypatch)
    with make_client(monkeypatch, tmp_path) as client:
        record = upload(client).json()
        queued = pending.get(record["id"])
        pending.add({**queued, "expires_at": time.time() - 1})

        ai._mark_blocked("description", 3600)
        assert moderation.auto_approve_due() == 0
        assert pending.count() == 1

        ai.reset_blocked()
        auto_before = stats.snapshot()["uploads_auto_approved"]
        assert moderation.auto_approve_due() == 1
        assert pending.count() == 0
        assert stats.snapshot()["uploads_auto_approved"] == auto_before + 1
        assert client.get("/images").json()["total"] == 1


def test_auto_approve_keeps_pending_on_upstream_error(monkeypatch, tmp_path):
    from app.errors import UpstreamAIError

    def fail_description(path):
        raise UpstreamAIError("Не удалось получить описание изображения.")

    monkeypatch.setattr(ai, "get_img_description", fail_description)
    with make_client(monkeypatch, tmp_path) as client:
        record = upload(client).json()
        queued = pending.get(record["id"])
        pending.add({**queued, "expires_at": time.time() - 1})

        assert moderation.auto_approve_due() == 0
        assert pending.count() == 1
        assert client.get("/images").json()["total"] == 0


def test_telegram_notification_is_sent(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        moderation.telegram,
        "notify_pending",
        lambda record, url: calls.append((record, url)) or True,
    )
    with make_client(monkeypatch, tmp_path) as client:
        assert upload(client).status_code == 202

    assert len(calls) == 1
    record, url = calls[0]
    assert record["original_filename"] == "meme.png"
    assert url.endswith("/admin")


def test_telegram_failure_does_not_break_upload(monkeypatch, tmp_path):
    def boom(record, url):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(moderation.telegram, "notify_pending", boom)
    with make_client(monkeypatch, tmp_path) as client:
        response = upload(client)
        assert response.status_code == 202
        assert pending.count() == 1


def test_admin_delete_meme(monkeypatch, tmp_path):
    mock_ai(monkeypatch)
    with make_client(monkeypatch, tmp_path) as client:
        record = upload(client).json()
        client.post(f"/api/v1/admin/pending/{record['id']}/approve", headers=ADMIN_HEADERS)
        assert client.get("/images").json()["total"] == 1

        deleted = client.delete(f"/api/v1/admin/memes/{record['id']}", headers=ADMIN_HEADERS)
        assert deleted.status_code == 200
        assert client.get("/images").json()["total"] == 0
