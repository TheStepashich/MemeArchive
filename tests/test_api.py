import io
import json
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from PIL import Image

from app import ai, db
from app.config import settings

ADMIN_HEADERS = {"X-API-Key": "test-admin"}


def png_bytes(color: tuple[int, int, int] = (0, 128, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_full_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "meme_in_dir", tmp_path / "memes")
    monkeypatch.setattr(settings, "scan_interval", 0)

    descriptions = iter(
        [
            "funny cat, office, work",
            "funny dog, park, walk",
        ]
    )

    def fake_description(path) -> str:
        return next(descriptions, "funny cat, office, work")

    embedding_calls: list[str] = []

    def fake_embedding(text: str, task_type: str, bypass_delay: bool = False) -> list[float]:
        embedding_calls.append(text)
        if "dog" in text:
            return [0.0, 1.0, 0.0]
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(ai, "get_img_description", fake_description)
    monkeypatch.setattr(ai, "get_embedding", fake_embedding)

    db.get_collection.cache_clear()

    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/add",
            files={"file": ("cat.png", png_bytes(), "image/png")},
            data={"tags": "cat, work", "favorite": "false"},
        )
        assert response.status_code == 200, response.text
        added = response.json()
        assert added["duplicate"] is False
        assert added["tags"] == ["cat", "work"]

        duplicate = client.post(
            "/add",
            files={"file": ("cat.png", png_bytes(), "image/png")},
            data={"tags": "office"},
        ).json()
        assert duplicate["duplicate"] is True
        assert set(duplicate["tags"]) == {"cat", "work", "office"}

        listing = client.get("/images", params={"limit": 10, "offset": 0}).json()
        assert listing["total"] == 1
        assert listing["limit"] == 10
        assert listing["offset"] == 0
        assert listing["next_offset"] == 1
        assert len(listing["results"]) == 1
        assert listing["results"][0]["id"] == added["id"]
        assert listing["results"][0]["created_at"]

        assert client.get(f"/meme/{added['id']}").status_code == 200

        embedding_calls.clear()
        results = client.post("/search", json={"query": "cat", "n_results": 5}).json()
        assert results["matched_tag"] == "cat"
        assert results["matched_tag_count"] == 1
        assert [r["description"] for r in results["results"]] == [
            "funny cat, office, work",
        ]
        assert embedding_calls == ["cat"]

        semantic = client.post("/search", json={"query": "kitten", "n_results": 5}).json()
        assert semantic["matched_tag"] is None
        assert [r["description"] for r in semantic["results"]] == [
            "funny cat, office, work",
        ]

        filtered = client.post(
            "/search",
            json={"query": "cat", "tags": ["work"], "favorite": False},
        ).json()
        assert len(filtered["results"]) == 1

        no_match = client.post(
            "/search",
            json={"query": "cat", "tags": ["dog"]},
        ).json()
        assert no_match["results"] == []

        favorite = client.patch(
            f"/images/{added['id']}/favorite",
            json={"favorite": True},
            headers=ADMIN_HEADERS,
        ).json()
        assert favorite["favorite"] is True

        favorites = client.get("/search", params={"query": "cat", "favorite": "true"}).json()
        assert len(favorites["results"]) == 1

        unmarked = client.patch(
            f"/images/{added['id']}/favorite",
            json={"favorite": False},
            headers=ADMIN_HEADERS,
        ).json()
        assert unmarked["favorite"] is False

        image = client.get(f"/image/{added['stored_name']}")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"

        assert client.get("/image/..%2Fsecret").status_code == 404
        assert client.get("/tags").json() == ["cat", "office", "work"]

        second_response = client.post(
            "/add",
            files={"file": ("dog.png", png_bytes(color=(255, 0, 0)), "image/png")},
            data={"tags": "dog, home", "favorite": "true"},
        )
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()
        assert second["duplicate"] is False
        assert second["tags"] == ["dog", "home"]

        listing = client.get("/images", params={"limit": 10, "offset": 0}).json()
        assert listing["total"] == 2
        assert [r["id"] for r in listing["results"]] == [second["id"], added["id"]]
        assert listing["next_offset"] == 2

        page_one = client.get("/images", params={"limit": 1, "offset": 0}).json()
        assert [r["id"] for r in page_one["results"]] == [second["id"]]
        assert page_one["next_offset"] == 1

        page_two = client.get("/images", params={"limit": 1, "offset": 1}).json()
        assert [r["id"] for r in page_two["results"]] == [added["id"]]
        assert page_two["next_offset"] == 2

        page_beyond = client.get("/images", params={"limit": 1, "offset": 5}).json()
        assert page_beyond["results"] == []
        assert page_beyond["next_offset"] == 5

        oldest = client.get("/images", params={"limit": 10, "order": "old"}).json()
        assert oldest["total"] == 2
        assert [r["id"] for r in oldest["results"]] == [added["id"], second["id"]]

        top = client.get("/images", params={"limit": 10, "order": "top"}).json()
        assert top["total"] == 1
        assert [r["id"] for r in top["results"]] == [second["id"]]

        by_tag = client.get("/images", params={"limit": 10, "tags": ["dog"]}).json()
        assert by_tag["total"] == 1
        assert [r["id"] for r in by_tag["results"]] == [second["id"]]

        multi_tag = client.get("/images", params={"limit": 10, "tags": ["cat", "dog"]}).json()
        assert multi_tag["total"] == 0
        assert multi_tag["results"] == []
        assert multi_tag["next_offset"] == 0

        semantic_both = client.post("/search", json={"query": "kitten", "n_results": 5}).json()
        assert semantic_both["matched_tag"] is None
        assert [r["description"] for r in semantic_both["results"]] == [
            "funny cat, office, work",
            "funny dog, park, walk",
        ]

        tag_first = client.post("/search", json={"query": "cat", "n_results": 5}).json()
        assert tag_first["matched_tag"] == "cat"
        assert tag_first["matched_tag_count"] == 1
        assert [r["description"] for r in tag_first["results"]] == [
            "funny cat, office, work",
            "funny dog, park, walk",
        ]

        assert client.get("/images", params={"order": "bogus"}).status_code == 422

        assert client.get("/tags").json() == ["cat", "dog", "home", "office", "work"]

        random_tags = client.get("/tags", params={"limit": 2}).json()
        assert len(random_tags) == 2
        assert set(random_tags) <= {"cat", "dog", "home", "office", "work"}

        deleted_second = client.delete(f"/images/{second['id']}", headers=ADMIN_HEADERS)
        assert deleted_second.status_code == 200
        deleted = client.delete(f"/images/{added['id']}", headers=ADMIN_HEADERS)
        assert deleted.status_code == 200
        assert client.post("/search", json={"query": "cat"}).json()["results"] == []

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"


def test_bot_api(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "meme_in_dir", tmp_path / "memes")
    monkeypatch.setattr(settings, "scan_interval", 0)
    monkeypatch.setattr(settings, "bot_api_token", "secret")
    monkeypatch.setattr(ai, "get_img_description", lambda path: "funny cat")
    monkeypatch.setattr(ai, "get_embedding", lambda text, task_type, bypass_delay=False: [1.0, 0.0, 0.0])

    db.get_collection.cache_clear()

    from app.main import app

    with TestClient(app) as client:
        added = client.post(
            "/add",
            files={"file": ("cat.png", png_bytes(), "image/png")},
            data={"tags": "cat"},
        ).json()

        assert client.get("/api/v1/search", params={"query": "cat"}).status_code == 401

        response = client.get(
            "/api/v1/search",
            params={"query": "cat", "limit": 5},
            headers={"X-API-Key": "secret"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["limit"] == 5
        assert payload["results"][0]["id"] == added["id"]
        assert payload["results"][0]["tags"] == ["cat"]

        image_path = urlparse(payload["results"][0]["image_url"]).path
        assert client.get(image_path).status_code == 401
        image = client.get(image_path, headers={"Authorization": "Bearer secret"})
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"

        random_res = client.get("/api/v1/random", headers={"X-API-Key": "secret"})
        assert random_res.status_code == 200
        random_data = random_res.json()
        assert len(random_data["results"]) == 1
        assert random_data["results"][0]["id"] == added["id"]

        similar_res = client.get(
            f"/api/v1/memes/{added['id']}/similar",
            params={"limit": 5},
            headers={"X-API-Key": "secret"},
        )
        assert similar_res.status_code == 200
        similar_data = similar_res.json()
        assert similar_data["query"] == "similar"


def test_stats(monkeypatch, tmp_path):
    from app import stats as stats_mod

    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "meme_in_dir", tmp_path / "memes")
    monkeypatch.setattr(settings, "scan_interval", 0)
    monkeypatch.setattr(settings, "bot_api_token", "secret")
    monkeypatch.setattr(settings, "stats_file", tmp_path / "stats" / "stats.json")
    monkeypatch.setattr(ai, "get_img_description", lambda path: "funny cat")

    def fake_embed(normalized: str, task_type: str, model: str, bypass_delay: bool = False) -> list[float]:
        stats_mod.incr(
            "embedding_document_calls"
            if task_type == settings.embedding_task_document
            else "embedding_query_calls"
        )
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(ai, "_embed_uncached", fake_embed)

    stats_mod.reset()
    ai._EMBED_CACHE.clear()
    db.get_collection.cache_clear()

    from app.main import app

    with TestClient(app) as client:
        client.post(
            "/add",
            files={"file": ("cat.png", png_bytes(), "image/png")},
            data={"tags": "cat"},
        )

        client.post("/search", json={"query": "кот"})
        client.post("/search", json={"query": "КОТ"})

        payload = client.get("/stats").json()
        assert payload["embedding_query_calls"] == 1
        assert payload["embedding_document_calls"] == 1
        assert payload["cache_misses"] == 2
        assert payload["cache_exact_hits"] == 1
        assert payload["cache_requests"] == 3
        assert payload["cache_hit_rate"] == 0.3333
        assert payload["cache_size"] == 2
        assert payload["gemini_calls"] == 2
        assert payload["description_calls"] == 0
        assert payload["started_at"]
        assert payload["updated_at"]

        assert client.get("/api/v1/stats").status_code == 401
        bot_stats = client.get("/api/v1/stats", headers={"X-API-Key": "secret"})
        assert bot_stats.status_code == 200
        assert bot_stats.json()["cache_exact_hits"] == 1

        saved = json.loads((tmp_path / "stats" / "stats.json").read_text())
        assert saved["counters"]["embedding_query_calls"] == 1
        assert saved["counters"]["embedding_document_calls"] == 1
        assert saved["counters"]["cache_exact_hits"] == 1


def test_folder_scan_style_add_without_tags(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "meme_in_dir", tmp_path / "memes")
    monkeypatch.setattr(settings, "scan_interval", 0)

    descriptions = iter(
        [
            "Cat with a hat sits at an office desk.\ncat, office, irony",
            "Dog walks through a park on a leash.",
        ]
    )

    monkeypatch.setattr(
        ai,
        "get_img_description",
        lambda path: next(descriptions, "Uncaptioned meme image."),
    )
    monkeypatch.setattr(ai, "get_embedding", lambda text, task_type, bypass_delay=False: [1.0, 0.0, 0.0])

    db.get_collection.cache_clear()

    from app.main import app

    with TestClient(app) as client:
        tagged = client.post(
            "/add",
            files={"file": ("cat.png", png_bytes(), "image/png")},
        )
        assert tagged.status_code == 200, tagged.text
        added = tagged.json()
        assert added["tags"] == ["cat", "office", "irony"]

        plain_response = client.post(
            "/add",
            files={"file": ("dog.png", png_bytes(color=(255, 0, 0)), "image/png")},
        )
        assert plain_response.status_code == 200, plain_response.text
        plain = plain_response.json()
        assert plain["tags"] == []
        assert plain["id"] != added["id"]

        assert client.get("/tags").json() == ["cat", "irony", "office"]

        by_tag = client.get("/images", params={"limit": 10, "tags": ["cat"]}).json()
        assert by_tag["total"] == 1
        assert [r["id"] for r in by_tag["results"]] == [added["id"]]

        listing = client.get("/images", params={"limit": 10}).json()
        assert listing["total"] == 2

        filtered = client.post("/search", json={"query": "cat", "tags": ["cat"]}).json()
        assert [r["description"] for r in filtered["results"]] == [added["description"]]

        favorite = client.patch(
            f"/images/{plain['id']}/favorite",
            json={"favorite": True},
            headers=ADMIN_HEADERS,
        )
        assert favorite.status_code == 200, favorite.text
        assert favorite.json()["tags"] == []
