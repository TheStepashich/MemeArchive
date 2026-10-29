from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import ai, captcha, db, moderation, pending, service, stats
from app.config import STATIC_DIR, settings
from app.errors import AppError, CaptchaError, NotFoundError, UpstreamAIError
from app.images import safe_upload_path
from app.scheduler import periodic_ingest
from app.schemas import (
    AdminStatsResponse,
    BotSearchResponse,
    BotSearchResult,
    FavoriteRequest,
    HealthResponse,
    ImageListResponse,
    ImageRecord,
    PendingItem,
    PendingListResponse,
    PublicConfigResponse,
    SearchRequest,
    SearchResponse,
    StatsResponse,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    _ = settings.i2t_prompt
    logger.info(
        "Starting Meme Archive: uploads=%s chroma=%s memes=%s scan_interval=%ss",
        settings.uploads_dir,
        settings.chroma_dir,
        settings.meme_in_dir,
        settings.scan_interval,
    )

    try:
        migrated = db.migrate_pending_flag()
        if migrated:
            logger.info("Обновлены записи без флага модерации: %d", migrated)
    except Exception:
        logger.exception("Не удалось обновить флаг модерации в ChromaDB")

    stop = asyncio.Event()
    tasks = [asyncio.create_task(periodic_ingest(stop), name="periodic-ingest")]
    if settings.pending_enabled:
        tasks.append(
            asyncio.create_task(moderation.auto_approve_loop(stop), name="auto-approve")
        )
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            try:
                await asyncio.wait_for(task, timeout=30)
            except TimeoutError:
                task.cancel()
                logger.warning("Фоновая задача %s не завершилась за 30 секунд, отменена", task.get_name())


app = FastAPI(title="Meme Archive", version="2.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)


@app.exception_handler(AppError)
async def app_error_handler(_request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unhandled_error_handler(_request, exc: Exception) -> JSONResponse:
    logger.exception("Необработанная ошибка", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера."},
    )


def _extract_token(x_api_key: str | None, authorization: str | None) -> str | None:
    token = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    return token


def require_bot_token(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.bot_api_token
    if not expected:
        return

    token = _extract_token(x_api_key, authorization)
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Неверный или отсутствующий API-ключ.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_admin_token(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.admin_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN не задан на сервере.",
        )

    token = _extract_token(x_api_key, authorization)
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Неверный или отсутствующий токен администратора.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/config", response_model=PublicConfigResponse)
def public_config() -> PublicConfigResponse:
    return PublicConfigResponse(
        captcha_enabled=settings.captcha_enabled,
        captcha_ttl_seconds=settings.captcha_ttl_seconds,
        pending_enabled=settings.pending_enabled,
        pending_ttl_seconds=settings.pending_ttl_seconds,
    )


@app.get("/captcha", name="captcha_image")
def captcha_image() -> JSONResponse:
    if not settings.captcha_enabled:
        raise NotFoundError("Капча отключена.")
    challenge_id, image = captcha.new_challenge()
    encoded = base64.b64encode(image).decode("ascii")
    return JSONResponse(
        {
            "id": challenge_id,
            "image": f"data:image/png;base64,{encoded}",
            "expires_in": settings.captcha_ttl_seconds,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/add", response_model=ImageRecord)
async def add_image(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    tags: Annotated[str, Form()] = "",
    favorite: Annotated[bool, Form()] = False,
    captcha_id: Annotated[str, Form()] = "",
    captcha_answer: Annotated[str, Form()] = "",
) -> ImageRecord:
    if settings.captcha_enabled and not captcha.verify(captcha_id, captcha_answer):
        stats.incr("captcha_failures")
        raise CaptchaError("Неверный код с картинки. Попробуйте ещё раз.")

    data = await file.read()
    try:
        if settings.pending_enabled:
            admin_url = str(request.base_url).rstrip("/") + "/admin"
            record = await run_in_threadpool(
                moderation.submit_upload,
                data,
                file.filename,
                tags,
                admin_url,
            )
            if record.get("pending"):
                response.status_code = 202
        else:
            record = await run_in_threadpool(
                service.add_image,
                data,
                file.filename,
                tags,
                favorite,
            )
    except AppError:
        raise
    except Exception:
        logger.exception("Ошибка добавления изображения")
        raise HTTPException(status_code=500, detail="Не удалось добавить изображение.")

    logger.info(
        "Image %s %s (%s)",
        record["id"],
        "pending" if record.get("pending") else ("already exists" if record["duplicate"] else "added"),
        record["original_filename"],
    )
    return ImageRecord(**record)


def _run_search(request: SearchRequest) -> SearchResponse:
    try:
        result = service.search(
            query=request.query,
            n_results=request.n_results,
            offset=request.offset,
            tags=request.tags,
            favorite=request.favorite,
        )
    except AppError:
        raise
    except Exception:
        logger.exception("Ошибка поиска")
        raise HTTPException(status_code=500, detail="Не удалось выполнить поиск.")

    return SearchResponse(**result)


@app.post("/search", response_model=SearchResponse)
def search_images(request: SearchRequest) -> SearchResponse:
    return _run_search(request)


@app.get("/search", response_model=SearchResponse)
def search_images_get(
    query: Annotated[str, Query(min_length=1, max_length=1000)],
    n_results: Annotated[int, Query(ge=1, le=50)] = 5,
    offset: Annotated[int, Query(ge=0)] = 0,
    tags: Annotated[list[str] | None, Query()] = None,
    favorite: Annotated[bool | None, Query()] = None,
) -> SearchResponse:
    return _run_search(
        SearchRequest(
            query=query,
            n_results=n_results,
            offset=offset,
            tags=tags or [],
            favorite=favorite,
        )
    )


def _bot_search_response(request: Request, result: SearchResponse) -> BotSearchResponse:
    return BotSearchResponse(
        query=result.query,
        results=[
            BotSearchResult(
                id=item.id,
                description=item.description,
                tags=item.tags,
                favorite=item.favorite,
                image_url=str(request.url_for("bot_image", image_id=item.id)),
                page_url=str(request.url_for("meme_page", image_id=item.id)),
                width=item.width,
                height=item.height,
                mime_type=item.mime_type,
                distance=item.distance,
            )
            for item in result.results
        ],
        total=result.total,
        limit=result.n_results,
        offset=result.offset,
    )


@app.get(
    "/api/v1/search",
    response_model=BotSearchResponse,
    dependencies=[Depends(require_bot_token)],
)
def bot_search(
    request: Request,
    query: Annotated[str, Query(min_length=1, max_length=1000)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
    tags: Annotated[list[str] | None, Query()] = None,
    favorite: Annotated[bool | None, Query()] = None,
) -> BotSearchResponse:
    result = _run_search(
        SearchRequest(
            query=query,
            n_results=limit,
            offset=offset,
            tags=tags or [],
            favorite=favorite,
        )
    )
    return _bot_search_response(request, result)


@app.get(
    "/api/v1/memes/{image_id}/image",
    name="bot_image",
    dependencies=[Depends(require_bot_token)],
)
def bot_image(image_id: str) -> FileResponse:
    record = service.get_image(image_id)
    path = safe_upload_path(record["stored_name"])
    if not path.is_file():
        raise NotFoundError("Изображение не найдено.")

    media_type = record.get("mime_type") or mimetypes.guess_type(path.name)[0]
    return FileResponse(path, media_type=media_type or "application/octet-stream")


@app.get(
    "/api/v1/random",
    response_model=BotSearchResponse,
    dependencies=[Depends(require_bot_token)],
)
def bot_random(request: Request) -> BotSearchResponse:
    record = service.get_random_image()
    return _bot_search_response(
        request,
        SearchResponse(query="", results=[ImageRecord(**record)], total=1, n_results=1, offset=0),
    )


@app.get(
    "/api/v1/memes/{image_id}/similar",
    response_model=BotSearchResponse,
    dependencies=[Depends(require_bot_token)],
)
def bot_similar(
    request: Request,
    image_id: str,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
) -> BotSearchResponse:
    result = service.get_similar_images(image_id, n_results=limit)
    records = result["results"]
    return _bot_search_response(
        request,
        SearchResponse(
            query="similar",
            results=[ImageRecord(**record) for record in records],
            total=len(records),
            n_results=limit,
            offset=0,
        ),
    )


def _stats_payload() -> StatsResponse:
    payload = stats.snapshot()
    payload["cache_size"] = ai.embed_cache_size()
    return StatsResponse(**payload)


@app.get(
    "/api/v1/stats",
    response_model=StatsResponse,
    dependencies=[Depends(require_bot_token)],
)
def bot_stats() -> StatsResponse:
    return _stats_payload()


@app.get("/images", response_model=ImageListResponse)
def list_images(
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Annotated[str, Query(pattern="^(new|old|top|random)$")] = "new",
    tags: Annotated[list[str] | None, Query()] = None,
) -> ImageListResponse:
    return ImageListResponse(**service.list_images(limit=limit, offset=offset, order=order, tags=tags))


@app.get("/images/{image_id}", response_model=ImageRecord)
def get_image(image_id: str) -> ImageRecord:
    return ImageRecord(**service.get_image(image_id))


@app.delete("/images/{image_id}", dependencies=[Depends(require_admin_token)])
def delete_image(image_id: str) -> dict[str, bool]:
    service.delete_image(image_id)
    return {"deleted": True}


@app.patch(
    "/images/{image_id}/favorite",
    response_model=ImageRecord,
    dependencies=[Depends(require_admin_token)],
)
def set_favorite(image_id: str, request: FavoriteRequest) -> ImageRecord:
    return ImageRecord(**service.set_favorite(image_id, request.favorite))


@app.get("/tags", response_model=list[str])
def get_tags(
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> list[str]:
    return service.list_tags(limit=limit)


@app.get("/image/{filename}")
def get_image_file(filename: str) -> FileResponse:
    path = safe_upload_path(filename)
    if not path.is_file():
        raise NotFoundError("Изображение не найдено.")

    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        images = db.db_count()
    except Exception:
        logger.exception("Healthcheck: ChromaDB недоступна")
        raise HTTPException(status_code=503, detail="ChromaDB недоступна.")

    return HealthResponse(
        status="ok",
        images=images,
        uploads_dir=str(settings.uploads_dir),
        meme_in_dir=str(settings.meme_in_dir),
        meme_in_dir_available=settings.meme_in_dir.is_dir(),
        pending=pending.count(),
        upstream_blocked_for=ai.upstream_blocked_seconds(),
    )


@app.get("/stats", response_model=StatsResponse)
def get_stats() -> StatsResponse:
    return _stats_payload()


@app.get(
    "/api/v1/admin/stats",
    response_model=AdminStatsResponse,
    dependencies=[Depends(require_admin_token)],
)
def admin_stats() -> AdminStatsResponse:
    payload = _stats_payload().model_dump()
    payload["images"] = db.db_count()
    payload["pending_count"] = pending.count()
    payload["upstream_blocked_for"] = ai.upstream_blocked_seconds()
    return AdminStatsResponse(**payload)


@app.get(
    "/api/v1/admin/pending",
    response_model=PendingListResponse,
    dependencies=[Depends(require_admin_token)],
)
def admin_pending(request: Request) -> PendingListResponse:
    now = time.time()
    items = []
    for record in pending.list_items():
        expires_at = float(record.get("expires_at") or 0)
        items.append(
            PendingItem(
                id=str(record["id"]),
                original_filename=record.get("original_filename"),
                tags=list(record.get("tags") or []),
                size=record.get("size"),
                width=record.get("width"),
                height=record.get("height"),
                mime_type=record.get("mime_type"),
                created_at=record.get("created_at"),
                expires_at=datetime.fromtimestamp(expires_at, UTC).isoformat(timespec="seconds")
                if expires_at
                else None,
                seconds_left=max(0, int(expires_at - now)),
                image_url=str(
                    request.url_for("admin_pending_image", item_id=str(record["id"]))
                ),
            )
        )
    return PendingListResponse(
        items=items,
        total=len(items),
        max_items=settings.max_pending_items,
    )


@app.get(
    "/api/v1/admin/pending/{item_id}/image",
    name="admin_pending_image",
    dependencies=[Depends(require_admin_token)],
)
def admin_pending_image(item_id: str) -> FileResponse:
    record = pending.get(item_id)
    if record is None:
        raise NotFoundError("Мем не найден в очереди модерации.")
    path = pending.image_path(record)
    if not path.is_file():
        raise NotFoundError("Файл ожидает модерации.")
    return FileResponse(
        path,
        media_type=str(record.get("mime_type") or "application/octet-stream"),
        headers={"Cache-Control": "no-store"},
    )


@app.post(
    "/api/v1/admin/pending/{item_id}/approve",
    response_model=ImageRecord,
    dependencies=[Depends(require_admin_token)],
)
def admin_approve(item_id: str) -> ImageRecord:
    record = pending.get(item_id)
    if record is None:
        raise NotFoundError("Мем не найден в очереди модерации.")
    try:
        result = moderation.approve(record, manual=True)
    except UpstreamAIError as exc:
        logger.warning("Не удалось опубликовать %s: %s", item_id, exc.message)
        raise HTTPException(
            status_code=502,
            detail=f"Gemini недоступен, мем останется в очереди. {exc.message}",
        ) from exc
    return ImageRecord(**result)


@app.post(
    "/api/v1/admin/pending/{item_id}/reject",
    dependencies=[Depends(require_admin_token)],
)
def admin_reject(item_id: str) -> dict[str, bool]:
    record = pending.get(item_id)
    if record is None:
        raise NotFoundError("Мем не найден в очереди модерации.")
    moderation.reject(record)
    return {"rejected": True}


@app.delete(
    "/api/v1/admin/memes/{image_id}",
    dependencies=[Depends(require_admin_token)],
)
def admin_delete_meme(image_id: str) -> dict[str, bool]:
    service.delete_image(image_id)
    return {"deleted": True}


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    index_file = Path(STATIC_DIR) / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=500, detail="index.html не найден.")
    return FileResponse(index_file, media_type="text/html")


@app.get("/admin", response_class=FileResponse, include_in_schema=False)
def admin_page() -> FileResponse:
    page = Path(STATIC_DIR) / "admin.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="admin.html не найден.")
    return FileResponse(page, media_type="text/html")


@app.get("/meme/{image_id}", response_class=FileResponse)
def meme_page(image_id: str) -> FileResponse:
    page = Path(STATIC_DIR) / "meme.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="meme.html не найден.")
    return FileResponse(page, media_type="text/html")
