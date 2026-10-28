import io

from PIL import Image

from app import ai, db, ingest, service
from app.config import settings
from app.errors import ImageValidationError, UpstreamAIError


def test_add_dir_continues_after_errors(tmp_path, monkeypatch):
    for name in ["good.png", "bad.png", "also.jpg", "notes.txt"]:
        (tmp_path / name).write_bytes(b"data")

    calls = []

    def fake_add_image(data, original_filename, tags=None, favorite=False, added_via="web"):
        calls.append(original_filename)
        if original_filename == "bad.png":
            raise ImageValidationError("broken")
        if original_filename == "also.jpg":
            return {"duplicate": True}
        return {"duplicate": False}

    monkeypatch.setattr(ingest.settings, "meme_in_dir", tmp_path)
    monkeypatch.setattr(ingest.service, "add_image", fake_add_image)

    stats = ingest.add_dir()

    assert sorted(calls) == ["also.jpg", "bad.png", "good.png"]
    assert stats["seen"] == 3
    assert stats["added"] == 1
    assert stats["duplicates"] == 1
    assert stats["failed"] == 1


def test_iter_image_files_handles_missing_dir(tmp_path):
    assert list(ingest.iter_image_files(tmp_path / "missing")) == []


def test_iter_image_files_accepts_jpeg_suffix(tmp_path):
    for name in ("a.jpg", "b.jpeg", "c.JPEG", "d.png", "e.mp4", "noext"):
        (tmp_path / name).write_bytes(b"x")

    names = [path.name for path in ingest.iter_image_files(tmp_path)]

    assert names == ["a.jpg", "b.jpeg", "c.JPEG", "d.png"]


def test_add_dir_indexes_images_without_explicit_tags(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(0, 128, 255)).save(buffer, format="PNG")
    (tmp_path / "cat.png").write_bytes(buffer.getvalue())

    buffer2 = io.BytesIO()
    Image.new("RGB", (8, 8), color=(255, 0, 0)).save(buffer2, format="PNG")
    (tmp_path / "dog.png").write_bytes(buffer2.getvalue())

    descriptions = iter(
        [
            "Cat with a hat sits at an office desk.\ncat, office, irony",
            "Dog walks through a park on a leash.",
        ]
    )

    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(settings, "meme_in_dir", tmp_path)
    monkeypatch.setattr(
        ai, "get_img_description", lambda path: next(descriptions, "Uncaptioned image.")
    )
    monkeypatch.setattr(ai, "get_embedding", lambda text, task_type: [1.0, 0.0, 0.0])

    db.get_collection.cache_clear()

    stats = ingest.add_dir()

    assert stats["seen"] == 2
    assert stats["added"] == 2
    assert stats["failed"] == 0

    tags = {
        tuple(service.get_image(image_id)["tags"]) for image_id in db.db_get_all()["ids"]
    }
    assert tags == {("cat", "office", "irony"), ()}
def test_add_dir_aborts_after_upstream_streak(tmp_path, monkeypatch):
    for index in range(10):
        (tmp_path / f"meme-{index}.png").write_bytes(b"data")

    attempts: list[str] = []

    def fake_add_image(data, original_filename, tags=None, favorite=False, added_via="web"):
        attempts.append(original_filename)
        raise UpstreamAIError("429 Too Many Requests")

    monkeypatch.setattr(ingest.settings, "meme_in_dir", tmp_path)
    monkeypatch.setattr(ingest.settings, "upstream_failure_streak", 3)
    monkeypatch.setattr(ingest.service, "add_image", fake_add_image)

    stats = ingest.add_dir()

    assert stats["aborted"] == 1
    assert stats["failed"] == 3
    assert stats["seen"] == 3
    assert len(attempts) == 3


def test_add_dir_keeps_scanning_on_local_errors(tmp_path, monkeypatch):
    for index in range(10):
        (tmp_path / f"meme-{index}.png").write_bytes(b"data")

    attempts: list[str] = []

    def fake_add_image(data, original_filename, tags=None, favorite=False, added_via="web"):
        attempts.append(original_filename)
        raise ImageValidationError("not an image")

    monkeypatch.setattr(ingest.settings, "meme_in_dir", tmp_path)
    monkeypatch.setattr(ingest.service, "add_image", fake_add_image)

    stats = ingest.add_dir()

    assert not stats.get("aborted")
    assert stats["failed"] == 10
    assert len(attempts) == 10
