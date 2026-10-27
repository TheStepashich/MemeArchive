from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    n_results: int = Field(default=5, ge=1, le=50)
    offset: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)
    favorite: bool | None = None

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Запрос не может быть пустым.")
        return value


class FavoriteRequest(BaseModel):
    favorite: bool


class ImageRecord(BaseModel):
    id: str
    description: str
    stored_name: str
    original_filename: str | None = None
    source: str
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    width: int | None = None
    height: int | None = None
    size: int | None = None
    mime_type: str | None = None
    content_hash: str | None = None
    created_at: str | None = None
    distance: float | None = None
    duplicate: bool = False


class ImageListResponse(BaseModel):
    results: list[ImageRecord]
    total: int
    limit: int
    offset: int
    next_offset: int


class SearchResponse(BaseModel):
    query: str
    results: list[ImageRecord]
    total: int
    n_results: int
    offset: int
    matched_tag: str | None = None
    matched_tag_count: int | None = None


class BotSearchResult(BaseModel):
    id: str
    description: str
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    image_url: str
    page_url: str
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    distance: float | None = None


class BotSearchResponse(BaseModel):
    query: str
    results: list[BotSearchResult]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    images: int
    uploads_dir: str
    meme_in_dir: str
    meme_in_dir_available: bool


class StatsResponse(BaseModel):
    started_at: str
    updated_at: str
    embedding_query_calls: int
    embedding_document_calls: int
    embedding_errors: int
    description_calls: int
    description_errors: int
    cache_exact_hits: int
    cache_fuzzy_hits: int
    cache_misses: int
    cache_requests: int
    cache_hit_rate: float
    cache_size: int
    gemini_calls: int
    gemini_errors: int
