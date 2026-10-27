from __future__ import annotations

import asyncio
import logging
import mimetypes
import secrets
from contextlib import asynccontextmanager
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
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import ai, db, service, stats
from app.config import STATIC_DIR, settings
from app.errors import AppError, NotFoundError
from app.images import safe_upload_path
from app.scheduler import periodic_ingest
from app.schemas import (
    BotSearchResponse,
    BotSearchResult,
    FavoriteRequest,
    HealthResponse,
    ImageListResponse,
    ImageRecord,
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

    stop = asyncio.Event()
    task = asyncio.create_task(periodic_ingest(stop), name="periodic-ingest")
    try:
        yield
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=30)
        except TimeoutError:
            task.cancel()
            logger.warning("Фоновый импорт не завершился за 30 секунд, отменён")


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


def require_bot_token(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.bot_api_token
    if not expected:
        return

    token = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Неверный или отсутствующий API-ключ.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.post("/add", response_model=ImageRecord)
async def add_image(
    file: Annotated[UploadFile, File()],
    tags: Annotated[str, Form()] = "",
    favorite: Annotated[bool, Form()] = False,
) -> ImageRecord:
    data = await file.read()
    try:
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
        "already exists" if record["duplicate"] else "added",
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
    order: Annotated[str, Query(pattern="^(new|old|top)$")] = "new",
    tags: Annotated[list[str] | None, Query()] = None,
) -> ImageListResponse:
    return ImageListResponse(**service.list_images(limit=limit, offset=offset, order=order, tags=tags))


@app.get("/images/{image_id}", response_model=ImageRecord)
def get_image(image_id: str) -> ImageRecord:
    return ImageRecord(**service.get_image(image_id))


@app.delete("/images/{image_id}")
def delete_image(image_id: str) -> dict[str, bool]:
    service.delete_image(image_id)
    return {"deleted": True}


@app.patch("/images/{image_id}/favorite", response_model=ImageRecord)
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
    )


@app.get("/stats", response_model=StatsResponse)
def get_stats() -> StatsResponse:
    return _stats_payload()


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    index_file = Path(STATIC_DIR) / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=500, detail="index.html не найден.")
    return FileResponse(index_file, media_type="text/html")


@app.get("/meme/{image_id}", response_class=FileResponse)
def meme_page(image_id: str) -> FileResponse:
    page = Path(STATIC_DIR) / "meme.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="meme.html не найден.")
    return FileResponse(page, media_type="text/html")
