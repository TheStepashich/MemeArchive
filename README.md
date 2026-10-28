# Meme Archive

Семантический архив мемов: изображение описывается моделью Gemini, описание превращается в эмбеддинг и сохраняется в ChromaDB. Поиск идёт по смыслу запроса, а не по именам файлов.

## Возможности

- Загрузка изображений через веб-интерфейс и API.
- Автоматическое описание мема (Gemini) и семантический поиск.
- Лента всех мемов с ленивой подгрузкой и отдельные карточки мемов.
- Кэш эмбеддингов запросов (точный + fuzzy через rapidfuzz), персистентный в SQLite — переживает рестарт.
- Идемпотентность: id = SHA-256 содержимого, повторная загрузка не создаёт дубликат.
- Теги: до 3 automatic tags from the keyword line of the description, случайные чипы, панель всех тегов, фильтрация и поиск по тегам.
- Пагинация ленты и поиска (`limit`/`offset`).
- Массовый импорт из папки с фоновым сканированием.
- Защита от 429: пауза по retryDelay, до 3 повторов на запрос; после 5 ошибок подряд проход прерывается, а сканирование уходит в экспоненциальный backoff (до `SCAN_BACKOFF_MAX`).
- Удаление записей и файлов.
- Переиндексация при смене модели эмбеддингов.
- Docker Compose.

## Структура

```
app/
  main.py        FastAPI-приложение и маршруты
  config.py      настройки из .env (pydantic-settings)
  ai.py          Gemini: описание и эмбеддинги
  db.py          ChromaDB
  service.py     бизнес-логика
  images.py      валидация изображений, безопасные пути, теги
  ingest.py      импорт из папки
  scheduler.py   фоновый импорт
  reindex.py     CLI переиндексации
static/
  index.html     лента и поиск
  meme.html      страница мема
  css/acid.css   общие стили (шапка, кнопки, тосты)
  css/index.css  стили ленты
  css/meme.css   стили страницы мема
  js/index.js    скрипт ленты
  js/meme.js     скрипт страницы мема
  js/theme.js    переключатель темы (автодетект системной)
tests/
```

## Быстрый старт (локально)

```bash
cp .env.example .env
# укажите настоящий API_KEY

uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python main.py
```

Приложение: http://localhost:8080

## Настройки

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `API_KEY` | ключ Google AI Studio | обязательна |
| `EMBEDDING_MODEL` | модель эмбеддингов | обязательна |
| `RECOGNIZING_MODEL` | модель описания изображений | обязательна |
| `PORT` | порт локального запуска | `8080` |
| `LANG` | язык описаний | `Russian` |
| `I2T_PROMPT_FILE` | файл промпта | `prompt.txt` |
| `CHROMA_DIR` | директория ChromaDB | `./chroma_db` |
| `UPLOADS_DIR` | директория загруженных файлов | `./uploads` |
| `MEME_IN_DIR` | папка для массового импорта | `./memes` |
| `MAX_UPLOAD_MB` | лимит размера файла | `25` |
| `MAX_IMAGE_PIXELS` | лимит разрешения | `40000000` |
| `SCAN_INTERVAL` | период сканирования папки, сек (0 — выключить) | `10` |
| `SCAN_BACKOFF_MAX` | максимальная пауза между сканированиями после ошибок, сек | `1800` |
| `UPSTREAM_FAILURE_STREAK` | сколько ошибок подряд прерывают сканирование | `5` |
| `GEMINI_RETRY_ATTEMPTS` | попыток на один запрос к Gemini (включая первый), 1 — без повторов | `5` |
| `LOG_LEVEL` | уровень логирования | `INFO` |
| `CORS_ORIGINS` | разрешённые origin через запятую | `*` |
| `SOCKS5_PROXY` | SOCKS5-прокси для запросов к Gemini, например `socks5h://host:1080` | — |
| `BOT_API_TOKEN` | токен для `/api/v1` (X-API-Key или Bearer). Если пуст — доступ без авторизации | — |
| `STATS_FILE` | файл статистики вызовов Gemini и кэша эмбеддингов | `./stats.json` |
| `EMBED_CACHE_FILE` | SQLite-файл персистентного кэша эмбеддингов | `./embed_cache.db` |

## Docker Compose

```bash
cp .env.example .env
# укажите API_KEY и при необходимости MEME_IN_DIR

mkdir -p memes
docker compose up --build -d
docker compose logs -f
```

- `http://localhost:8080` — интерфейс.
- `MEME_IN_DIR` на хосте монтируется в контейнер как `/memes` (только чтение).
- `uploads` и `chroma_db` живут в именованных volume `uploads_data` и `chroma_data`.
- Если `MEME_IN_DIR` не задан, используется локальная папка `./memes`.

Остановка:

```bash
docker compose down
```

Удаление данных вместе с volume:

```bash
docker compose down -v
```

## SOCKS5-прокси

Если Gemini API недоступен из вашего региона, укажите SOCKS5-прокси в `.env`:

```env
SOCKS5_PROXY=socks5h://user:password@host:1080
```

- Используйте `socks5h://`, чтобы DNS-запросы тоже шли через прокси.
- Локальный запуск: `SOCKS5_PROXY=socks5h://127.0.0.1:1080`.
- Docker: если прокси запущен на хосте, используйте имя `host.docker.internal`:
  ```env
  SOCKS5_PROXY=socks5h://host.docker.internal:1080
  ```
  В `docker-compose.yml` уже добавлен `host.docker.internal:host-gateway`.
- Прокси применяется только к клиенту Gemini, остальные запросы идут напрямую.

После изменения `.env`:

```bash
docker compose up -d
```

## API

Интерактивная документация: `http://localhost:8080/docs`.

```bash
# healthcheck
curl http://localhost:8080/health

# загрузка
curl -F "file=@meme.jpg" -F "tags=кот,работа" -F "favorite=false" \
  http://localhost:8080/add

# поиск (JSON)
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{"query":"кот в офисе","n_results":10,"tags":["работа"],"favorite":null}'

# поиск (GET, удобно для отладки)
curl "http://localhost:8080/search?query=кот&n_results=5"

# лента всех мемов (пагинация)
curl "http://localhost:8080/images?limit=24&offset=0"

# карточка мема
curl http://localhost:8080/images/<id>

# теги
curl http://localhost:8080/tags

# статистика Gemini и кэша
curl http://localhost:8080/stats

# избранное
curl -X PATCH http://localhost:8080/images/<id>/favorite \
  -H "Content-Type: application/json" -d '{"favorite":true}'

# удаление
curl -X DELETE http://localhost:8080/images/<id>
```

## API для Telegram-бота

Для внешних клиентов есть отдельное API `/api/v1`. Если задан `BOT_API_TOKEN`, запросы требуют ключ в заголовке `X-API-Key` или `Authorization: Bearer <token>`. Если токен пустой, API открыт — используйте это только в доверенной сети.

```bash
# поиск
curl -H "X-API-Key: $BOT_API_TOKEN" \
  "http://localhost:8080/api/v1/search?query=кот%20в%20офисе&limit=5&tags=работа"

# случайный мем
curl -H "X-API-Key: $BOT_API_TOKEN" \
  "http://localhost:8080/api/v1/random"

# похожие мемы
curl -H "X-API-Key: $BOT_API_TOKEN" \
  "http://localhost:8080/api/v1/memes/<id>/similar?limit=5"

# статистика Gemini и кэша
curl -H "X-API-Key: $BOT_API_TOKEN" \
  "http://localhost:8080/api/v1/stats"

# скачать найденное изображение
curl -H "X-API-Key: $BOT_API_TOKEN" \
  -o meme.png "http://localhost:8080/api/v1/memes/<id>/image"
```

Ответ поиска содержит `description`, `tags`, `favorite`, `image_url` и `page_url`. Поиск по тексту кэширует эмбеддинги (с учётом похожих запросов через rapidfuzz), поэтому повторы в боте не долбят Gemini. `similar` берёт вектор из БД и не вызывает эмбеддинг. Бот может скачать файл по `image_url` с тем же заголовком и отправить его в Telegram; отправлять Telegram ссылку напрямую нельзя, если API закрыт токеном или недоступен извне. Поддерживаются `limit`, `offset`, повторяющийся `tags` и `favorite=true`.

## Переиндексация

При смене `EMBEDDING_MODEL` или `EMBEDDING_TASK_*` старые эмбеддинги несовместимы с новыми. Пересчитайте их:

```bash
.venv/bin/python -m app.reindex
# заодно удалить записи, у которых пропал исходный файл
.venv/bin/python -m app.reindex --prune
```

## Тесты

```bash
.venv/bin/pytest
```

## Безопасность

- `.env` исключён из git. Если ключ когда-либо попадал в историю, перевыпустите его и очистите историю (`git filter-repo`).
- Загружаемые файлы проверяются Pillow по содержимому, а не по расширению.
- Имена файлов на диске — SHA-256, доступ к `/image/{filename}` защищён от path traversal.
- Ошибки клиенту отдаются без внутренних деталей, подробности пишутся в лог.
