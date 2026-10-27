import pytest
from pydantic import ValidationError

from app import ai
from app.config import Settings


def test_http_options_without_proxy(monkeypatch):
    monkeypatch.setattr(ai.settings, "socks5_proxy", None)
    ai.get_http_options.cache_clear()

    assert ai.get_http_options() is None


def test_http_options_with_proxy(monkeypatch):
    proxy = "socks5h://user:secret@127.0.0.1:1080"
    monkeypatch.setattr(ai.settings, "socks5_proxy", proxy)
    ai.get_http_options.cache_clear()

    try:
        options = ai.get_http_options()
        assert options is not None
        assert options.client_args == {"proxy": proxy}
        assert options.async_client_args == {"proxy": proxy}
    finally:
        ai.get_http_options.cache_clear()


def test_client_constructs_with_socks_proxy(monkeypatch):
    monkeypatch.setattr(ai.settings, "socks5_proxy", "socks5h://127.0.0.1:1080")
    ai.get_http_options.cache_clear()
    ai.get_client.cache_clear()

    try:
        assert ai.get_client() is not None
    finally:
        ai.get_client.cache_clear()
        ai.get_http_options.cache_clear()


def test_redact_proxy_hides_credentials():
    assert ai._redact_proxy("socks5h://user:pass@example.com:1080") == "socks5h://example.com:1080"


def test_rejects_non_socks_scheme():
    with pytest.raises(ValidationError):
        Settings(socks5_proxy="http://127.0.0.1:1080")


def test_empty_proxy_is_none():
    assert Settings(socks5_proxy="   ").socks5_proxy is None
