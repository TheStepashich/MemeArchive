import io

import pytest
from PIL import Image

from app.errors import ImageValidationError, NotFoundError, PayloadTooLargeError
from app.images import (
    extract_tags,
    inspect_image,
    metadata_tags,
    parse_tags,
    safe_original_filename,
    safe_upload_path,
    sha256_bytes,
)


def make_image(fmt: str = "PNG", size: tuple[int, int] = (10, 10)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(255, 0, 0)).save(buffer, format=fmt)
    return buffer.getvalue()


def test_inspect_valid_image():
    data = make_image()

    info = inspect_image(data)

    assert info.extension == "png"
    assert info.mime_type == "image/png"
    assert info.width == 10
    assert info.height == 10
    assert info.size == len(data)
    assert info.content_hash == sha256_bytes(data)


def test_inspect_rejects_non_image():
    with pytest.raises(ImageValidationError):
        inspect_image(b"not an image")


def test_inspect_rejects_unsupported_format():
    with pytest.raises(ImageValidationError):
        inspect_image(make_image("TIFF"))


def test_inspect_rejects_large_payload():
    with pytest.raises(PayloadTooLargeError):
        inspect_image(make_image(), max_bytes=10)


def test_inspect_rejects_too_many_pixels():
    with pytest.raises(ImageValidationError):
        inspect_image(make_image(size=(100, 100)), max_pixels=100)


def test_safe_upload_path_rejects_traversal():
    for name in ["../secret.jpg", "a/b.jpg", "..", "", "a\\b.jpg"]:
        with pytest.raises(NotFoundError):
            safe_upload_path(name)


def test_parse_tags_normalizes_and_dedupes():
    assert parse_tags(" cat, funny , CAT,  , #tag, two words ") == [
        "cat",
        "funny",
        "tag",
        "two words",
    ]


def test_parse_tags_accepts_iterable():
    assert parse_tags(["a,b", "c"]) == ["a", "b", "c"]


def test_metadata_tags_supports_legacy_string():
    assert metadata_tags({"tags": "a, b"}) == ["a", "b"]


def test_extract_tags_reads_keyword_line():
    description = "Cat with a hat sits at an office desk.\ncat, office, irony"

    assert extract_tags(description) == ["cat", "office", "irony"]


def test_extract_tags_caps_at_three():
    assert extract_tags("Paragraph text.\na, b, c, d") == ["a", "b", "c"]


def test_extract_tags_accepts_single_keyword():
    assert extract_tags("Paragraph text here.\ncats") == ["cats"]


def test_extract_tags_strips_bullet_and_label():
    description = "Paragraph text here.\n\n  - Keywords: cat, dog  "

    assert extract_tags(description) == ["cat", "dog"]


def test_extract_tags_ignores_single_line_description():
    assert extract_tags("funny cat, office, work") == []


def test_extract_tags_ignores_wrapped_prose():
    description = (
        "First line of a long paragraph that keeps\n"
        "going and going, and even more words here, ending abruptly"
    )

    assert extract_tags(description) == []


def test_extract_tags_handles_missing_description():
    assert extract_tags(None) == []
    assert extract_tags("") == []


def test_safe_original_filename_strips_paths():
    assert safe_original_filename("../../etc/passwd") == "passwd"


def test_safe_original_filename_defaults():
    assert safe_original_filename(None) == "upload"
