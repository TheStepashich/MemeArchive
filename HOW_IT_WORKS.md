# How Meme Archive works

Technical walkthrough of the internals. `README.md` covers usage; this article explains the machinery.

## 1. Big picture

Meme Archive is a single-process FastAPI app that turns images into searchable text:

```
image bytes -> SHA-256 id -> Gemini description -> embedding vector -> ChromaDB
```

Search embeds the *user's query* and compares vectors in ChromaDB (cosine distance), so "cat in office" finds a meme even if no filename mentions it. Blocking work is pushed off the event loop with `run_in_threadpool`.

| Module | Role |
| --- | --- |
| `app/main.py` | routes, auth, lifespan, background tasks |
| `app/service.py` | add / search / list / similar / tags / delete |
| `app/ai.py` | Gemini description + embedding, cache, rate-limit logic |
| `app/db.py` | ChromaDB wrapper |
| `app/embed_cache.py` | persistent SQLite query-embedding cache |
| `app/pending.py` + `app/moderation.py` | moderation queue, approvals, Telegram |
| `app/captcha.py` | self-drawn captcha |
| `app/images.py` | validation, hashing, tags, path safety |
| `app/ingest.py` + `app/scheduler.py` | background folder import |
| `app/stats.py` | JSON counters |
| `app/config.py` | pydantic-settings from `.env` |

## 2. Content hash is the primary key

`images.sha256_bytes` — every image's id **is** the SHA-256 of its bytes. This yields:

- **Idempotency**: re-uploading the same bytes never re-runs Gemini. `service.add_image` looks the hash up first (service.py:106); if it exists it only merges tags/favorite and re-creates the file if missing.
- **Storage layout**: files are `<hash>.<ext>` in `uploads/`, written via temp file + `os.replace` (`_write_atomic`) so a crash never leaves half-written files.
- **Dedup across sources**: web upload, folder import and re-approval all collide harmlessly on the same hash.

The extension comes from Pillow-detected format, never the uploaded filename.

## 3. Upload pipeline

Captcha (`captcha.py`): the server picks a random number 100-99999, renders it **in Russian words** over noise lines/dots with Pillow, and the expected answer is the digit form. A bot can't OCR it trivially; a human reads the words and types digits. Challenges live in an in-memory dict with TTL; `verify()` pops the entry (single use) and compares with `hmac.compare_digest`.

`POST /add` (main.py:197):

1. Verify captcha, else `CaptchaError`.
2. If `PENDING_TTL_SECONDS > 0` -> `moderation.submit_upload`, respond `202 pending`; otherwise `service.add_image` directly, respond `200`.

## 4. Validation and path safety (`images.py`)

`inspect_image` order: reject empty bytes -> reject > `MAX_UPLOAD_MB` -> `PIL.Image.open().verify()` (format detected from **content**, not name) -> allowed formats only (JPEG/PNG/WEBP/BMP/GIF) -> reject > `MAX_IMAGE_PIXELS` (stops decompression bombs).

`safe_upload_path` rejects anything that isn't a bare filename (no `/`, `\`, NUL, `..`) and verifies the resolved parent equals the uploads dir, so `/image/{filename}` can't traverse; unsafe or unknown names answer as a generic "not found".

## 5. Gemini layer (`ai.py`)

**Description**: raw bytes + prompt from `prompt.txt` go to `RECOGNIZING_MODEL.generate_content`. The prompt asks for a trailing **keyword line**; `images.extract_tags` mines it into up to 3 auto tags (validating the last line looks like comma-separated short segments).

**Embedding**: `embed_content` with asymmetric task types — `RETRIEVAL_DOCUMENT` for descriptions, `RETRIEVAL_QUERY` for searches (Gemini's recommended doc/query split).

**429 handling**: on `ClientError.code == 429`, `_parse_retry_delay` extracts the server's `retryDelay: '995s'` / "retry in 16m35s" hint. If retries (max 3) and delay (max 900 s) allow, sleep and retry in place; otherwise the call gives up and marks a **global block window** (`_mark_blocked`). `upstream_blocked_seconds()` is consulted by the auto-approve loop and folder ingest so background work doesn't hammer a throttled quota. Interactive search passes `bypass_delay=True` (service.py:327): a browser user never sleeps minutes, they just get "try later".

**Embedding cache**: in-process LRU `OrderedDict` (4096) keyed by `(normalized_text, task_type, model)`; exact hit, else fuzzy hit via `rapidfuzz token_sort_ratio >= 90` with same task/model. Misses go to Gemini and are persisted to SQLite (`embed_cache.db`) as float64 blobs with `last_used`. On restart, `load_into` (ai.py:76) reloads the freshest 4096 rows — the cache survives restarts; LRU eviction also deletes disk rows. Counters feed `/stats`.

## 6. ChromaDB (`db.py`)

One persistent collection `images` with `hnsw:space=cosine`: id = hash, document = description, embedding = document vector, metadata = `stored_name`, `source`, `original_filename`, `tags`, `favorite`, `pending`, dimensions, `created_at`, `added_via`. Empty list metadata is dropped (`_clean_metadata`). Pagination: fetch `n_results + offset` then slice; `where` filters (`tags $contains`, `favorite`, `pending`) are pushed down.

`service._build_record` reconstructs everything the UI shows, with fallbacks for records written by older versions.

## 7. Search (`service.search`)

1. **Tag shortcut**: if the query exactly matches an existing tag (case-insensitive), all its memes return first and are excluded from the semantic pass — one search box doubles as tag browsing.
2. **Semantic pass**: embed query (`RETRIEVAL_QUERY`) and run `db_search`.

Records whose file vanished from disk are skipped rather than shown broken.

Other modes: `list_images` (feed order `new|old|top|random`, "new" = tail of Chroma insertion order reversed), `get_similar_images` (reuses the stored vector via `db_get_embedding`, zero Gemini calls), `get_random_image` (random offset into filtered `get()`).

## 8. Moderation queue (`pending.py` + `moderation.py`)

Queued memes live **outside** Chroma so unapproved content is never indexed. `pending_dir` holds image files plus `index.json` (id -> record with `expires_at`), rewritten atomically under a lock.

`submit_upload`: already archived -> instant add; already queued -> duplicate pending record; queue >= `MAX_PENDING_ITEMS` -> 429. New items get a Telegram `sendPhoto` notification to the admin chat (`telegram.py`, failures logged, never block the upload).

`auto_approve_loop` (started in `lifespan`, main.py:83) wakes every `PENDING_CHECK_INTERVAL` s; for each due item it calls `approve()`, which re-runs `service.add_image` on the stored bytes — description + embedding therefore happen **at publish time**, when quota may have recovered. Guards: while `ai.upstream_blocked_seconds() > 0` the loop does nothing; an upstream error stops the batch until the next cycle. Admins can approve/reject early via `/api/v1/admin/*`.

## 9. Folder import (`ingest.py` + `scheduler.py`)

Background task scans `MEME_IN_DIR` every `SCAN_INTERVAL` s, calling `service.add_image(added_via="folder")` per file — same dedup/description path as uploads. Policy: skip the pass entirely while Gemini is blocked; count consecutive upstream errors, abort the pass after `UPSTREAM_FAILURE_STREAK` (5); `next_scan_delay` doubles the interval per aborted pass up to `SCAN_BACKOFF_MAX` (30 min); a clean pass resets it.

## 10. Auth and errors (`main.py`)

Two independent tokens compared with `secrets.compare_digest`, accepted via `X-API-Key` or `Authorization: Bearer`:

- `BOT_API_TOKEN` gates `/api/v1/*` (bot API: search, random, similar, image download). Empty = open API.
- `ADMIN_TOKEN` gates `/api/v1/admin/*`, favorite/delete on `/images`. Empty = admin features answer 503.

`AppError` subclasses map to clean JSON `{"detail": ...}` without internals; a catch-all handler logs the traceback and returns a generic 500.

## 11. Frontend and stats

Server-served pages `/` (feed + search), `/meme/{id}` (card), `/admin` (queue with countdown, counters, approve/reject/delete); assets under `/static`, admin token kept only in `sessionStorage`. `stats.py` keeps counters (`description_calls`, `cache_*`, `uploads_*`, `captcha_failures`, ...) in memory, persisted to `stats.json` atomically under a lock, and exposed via `/stats`.

## 12. Reindexing

Vectors from an old `EMBEDDING_MODEL` are incompatible with new ones. `python -m app.reindex` re-embeds every stored description; `--prune` also deletes records whose file has disappeared.
