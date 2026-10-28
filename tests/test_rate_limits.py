from types import SimpleNamespace

import pytest
from google.genai.errors import ClientError
from PIL import Image

from app import ai
from app.config import settings
from app.errors import UpstreamAIError


def make_429(retry_delay: str | None = "30s") -> ClientError:
    details: dict[str, object] = {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}
    if retry_delay is not None:
        details["details"] = [{"retryDelay": retry_delay}]
    return ClientError(429, {"error": details})


def make_400() -> ClientError:
    return ClientError(400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}})


class FakeModels:
    def __init__(self, script: list[object]):
        self.script = list(script)

    def _next(self) -> object:
        if not self.script:
            raise AssertionError("fake model script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def generate_content(self, **kwargs: object) -> object:
        item = self._next()
        if isinstance(item, str):
            return SimpleNamespace(text=item)
        return item

    def embed_content(self, **kwargs: object) -> object:
        return self._next()


class FakeClient:
    def __init__(self, script: list[object]):
        self.models = FakeModels(script)


def png_file(tmp_path) -> object:
    path = tmp_path / "meme.png"
    Image.new("RGB", (8, 8), color=(0, 128, 255)).save(path, format="PNG")
    return path


def embedding_response(*values: float) -> object:
    return SimpleNamespace(embeddings=[SimpleNamespace(values=list(values))])


def test_parse_retry_delay_prefers_retry_info_field():
    assert ai._parse_retry_delay("429 RESOURCE_EXHAUSTED. {'retryDelay': '36s'}") == 41


def test_parse_retry_delay_human_readable():
    assert ai._parse_retry_delay("Please retry in 16m35.09s") == 16 * 60 + 35 + 5


def test_parse_retry_delay_falls_back_to_default():
    assert ai._parse_retry_delay("429 no details here") == ai._DEFAULT_SLEEP_SECS
    assert ai._parse_retry_delay("") == ai._DEFAULT_SLEEP_SECS


def test_description_retries_after_429_with_retry_delay(monkeypatch, tmp_path):
    path = png_file(tmp_path)
    sleeps: list[int] = []
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: sleeps.append(seconds))
    client = FakeClient([make_429("30s"), make_429("10s"), "a cat in a hat"])
    monkeypatch.setattr(ai, "get_client", lambda: client)

    assert ai.get_img_description(path) == "a cat in a hat"
    assert sleeps == [35, 15]


def test_description_gives_up_after_retry_budget(monkeypatch, tmp_path):
    path = png_file(tmp_path)
    sleeps: list[int] = []
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: sleeps.append(seconds))
    client = FakeClient([make_429("30s") for _ in range(ai._MAX_RATE_LIMIT_RETRIES + 1)])
    monkeypatch.setattr(ai, "get_client", lambda: client)

    with pytest.raises(UpstreamAIError):
        ai.get_img_description(path)

    assert len(sleeps) == ai._MAX_RATE_LIMIT_RETRIES


def test_description_does_not_sleep_on_long_quota_reset(monkeypatch, tmp_path):
    path = png_file(tmp_path)
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: pytest.fail("must not sleep on daily quota"))
    client = FakeClient([make_429("99999s")])
    monkeypatch.setattr(ai, "get_client", lambda: client)

    with pytest.raises(UpstreamAIError):
        ai.get_img_description(path)


def test_description_does_not_retry_other_client_errors(monkeypatch, tmp_path):
    path = png_file(tmp_path)
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: pytest.fail("must not sleep on 400"))
    client = FakeClient([make_400()])
    monkeypatch.setattr(ai, "get_client", lambda: client)

    with pytest.raises(UpstreamAIError):
        ai.get_img_description(path)


def test_embedding_retries_after_429(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "embed_cache_file", tmp_path / "cache.db")
    ai._EMBED_CACHE.clear()
    sleeps: list[int] = []
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: sleeps.append(seconds))
    client = FakeClient([make_429("20s"), embedding_response(1.0, 0.0)])
    monkeypatch.setattr(ai, "get_client", lambda: client)

    assert ai.get_embedding("distinct query", settings.embedding_task_document) == [1.0, 0.0]
    assert sleeps == [25]


def test_embedding_bypass_delay_raises_without_sleep(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "embed_cache_file", tmp_path / "cache.db")
    ai._EMBED_CACHE.clear()
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: pytest.fail("UI query must not sleep"))
    client = FakeClient([make_429("20s")])
    monkeypatch.setattr(ai, "get_client", lambda: client)

    with pytest.raises(UpstreamAIError):
        ai.get_embedding("another query", settings.embedding_task_query, bypass_delay=True)


def test_rate_limit_counters_are_registered():
    from app.stats import COUNTER_KEYS

    assert "description_rate_limits" in COUNTER_KEYS
    assert "embedding_rate_limits" in COUNTER_KEYS
