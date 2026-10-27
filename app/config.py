from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_key: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    recognizing_model: str = Field(min_length=1)

    port: int = Field(default=8080, ge=1, le=65535)
    lang: str = "Russian"
    i2t_prompt_file: Path = BASE_DIR / "prompt.txt"

    chroma_dir: Path = BASE_DIR / "chroma_db"
    meme_in_dir: Path = BASE_DIR / "memes"
    uploads_dir: Path = BASE_DIR / "uploads"
    stats_file: Path = BASE_DIR / "stats.json"
    embed_cache_file: Path = BASE_DIR / "embed_cache.db"

    max_upload_mb: int = Field(default=25, ge=1, le=200)
    max_image_pixels: int = Field(default=40_000_000, ge=1_000_000)
    scan_interval: int = Field(default=10, ge=0)
    log_level: str = "INFO"
    cors_origins: str = "*"
    socks5_proxy: str | None = None
    bot_api_token: str | None = None

    embedding_task_document: str = "RETRIEVAL_DOCUMENT"
    embedding_task_query: str = "RETRIEVAL_QUERY"

    @field_validator(
        "i2t_prompt_file",
        "chroma_dir",
        "meme_in_dir",
        "uploads_dir",
        "stats_file",
        "embed_cache_file",
        mode="after",
    )
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            value = (BASE_DIR / value).resolve()
        return value

    @field_validator("bot_api_token", mode="before")
    @classmethod
    def _validate_bot_api_token(cls, value: object) -> str | None:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @field_validator("socks5_proxy", mode="before")
    @classmethod
    def _validate_socks5_proxy(cls, value: object) -> str | None:
        if value is None:
            return None
        proxy = str(value).strip()
        if not proxy:
            return None
        if not proxy.startswith(("socks5://", "socks5h://")):
            raise ValueError("SOCKS5_PROXY должен начинаться с socks5:// или socks5h://")
        return proxy

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def i2t_prompt(self) -> str:
        return _read_prompt(self.i2t_prompt_file).replace("{lang}", self.lang)

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)
        self.embed_cache_file.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Не удалось прочитать файл промпта: {path}") from exc


settings = Settings()
