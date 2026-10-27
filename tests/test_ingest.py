
from app import ingest
from app.errors import ImageValidationError


def test_add_dir_continues_after_errors(tmp_path, monkeypatch):
    for name in ["good.png", "bad.png", "also.jpg", "notes.txt"]:
        (tmp_path / name).write_bytes(b"data")

    calls = []

    def fake_add_image(data, original_filename, tags=None, favorite=False):
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
