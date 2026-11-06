"""Server-side rendering for crawlers and social previews.

The UI is a JavaScript app, so without this module every ``/meme/<id>`` URL
returns the exact same empty HTML shell. Search engines then see thousands of
identical pages with no title, description or content and refuse to index them.
These helpers render the important parts (title, meta tags, meme data and the
homepage feed) directly into the HTML.
"""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import quote

SITE_NAME = "Meme Archive"
MAX_TITLE = 70
MAX_DESCRIPTION = 160
MAX_CARD_DESCRIPTION = 220


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _truncate(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return f"{cut}…" if cut else value[:limit]


def _first_line(record: dict[str, Any]) -> str:
    description = (record.get("description") or "").strip()
    if not description:
        return ""
    return description.split("\n", 1)[0]


def meme_title(record: dict[str, Any]) -> str:
    """Short, human-readable title derived from the AI description."""
    line = _first_line(record)
    if line:
        return _truncate(line, MAX_TITLE)
    return str(record.get("original_filename") or "Мем")


def meme_meta_description(record: dict[str, Any]) -> str:
    description = " ".join((record.get("description") or "").split())
    if description:
        return _truncate(description, MAX_DESCRIPTION)
    return "Мем из семантического архива Meme Archive."


def image_url(record: dict[str, Any], site_url: str) -> str:
    stored_name = record.get("stored_name") or ""
    return f"{site_url}/image/{quote(str(stored_name))}"


def meme_url(record: dict[str, Any], site_url: str) -> str:
    return f"{site_url}/meme/{quote(str(record.get('id') or ''))}"


def _head_tags(record: dict[str, Any], site_url: str) -> str:
    title = meme_title(record)
    description = meme_meta_description(record)
    page_url = meme_url(record, site_url)
    image = image_url(record, site_url)
    full_title = f"{title} — {SITE_NAME}"

    json_ld: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "ImageObject",
        "name": title,
        "description": description,
        "contentUrl": image,
        "url": page_url,
        "isPartOf": {
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": f"{site_url}/",
        },
    }
    if record.get("created_at"):
        json_ld["datePublished"] = record["created_at"]
    if record.get("width") and record.get("height"):
        json_ld["width"] = record["width"]
        json_ld["height"] = record["height"]

    return "\n".join(
        [
            f"    <title>{_escape(full_title)}</title>",
            f'    <meta name="description" content="{_escape(description)}">',
            '    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">',
            f'    <link rel="canonical" href="{_escape(page_url)}">',
            '    <meta property="og:type" content="article">',
            f'    <meta property="og:site_name" content="{_escape(SITE_NAME)}">',
            f'    <meta property="og:title" content="{_escape(full_title)}">',
            f'    <meta property="og:description" content="{_escape(description)}">',
            f'    <meta property="og:url" content="{_escape(page_url)}">',
            f'    <meta property="og:image" content="{_escape(image)}">',
            f'    <meta property="og:image:alt" content="{_escape(description)}">',
            '    <meta property="og:locale" content="ru_RU">',
            '    <meta name="twitter:card" content="summary_large_image">',
            f'    <meta name="twitter:title" content="{_escape(full_title)}">',
            f'    <meta name="twitter:description" content="{_escape(description)}">',
            f'    <meta name="twitter:image" content="{_escape(image)}">',
            f'    <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>',
        ]
    )


def _tags_html(tags: list[str]) -> str:
    if not tags:
        return ""
    links = "".join(
        f'<a class="meme-tag" href="/?query={quote(tag)}">#{_escape(tag)}</a>'
        for tag in tags
    )
    return links


def _meta_html(record: dict[str, Any]) -> str:
    rows = [
        ("Файл", record.get("original_filename")),
        (
            "Разрешение",
            (
                f"{record['width']} × {record['height']} px"
                if record.get("width") and record.get("height")
                else None
            ),
        ),
        ("Добавлен", record.get("created_at")),
    ]
    parts: list[str] = []
    for label, value in rows:
        if not value:
            continue
        parts.append(f"<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>")
    return "".join(parts)


def render_meme_content(record: dict[str, Any], site_url: str) -> str:
    """Markup for ``<main>`` on a meme page.

    It keeps the element ids expected by ``static/js/meme.js`` so the client
    can take over without re-fetching layout.
    """
    title = meme_title(record)
    description = record.get("description") or "Описание отсутствует."
    image = image_url(record, site_url)
    alt = meme_meta_description(record)
    size_attrs = ""
    if record.get("width") and record.get("height"):
        size_attrs = f' width="{int(record["width"])}" height="{int(record["height"])}"'

    tags = record.get("tags") or []
    tags_block = (
        f'<div id="tags" class="meme-tags">{_tags_html(tags)}</div>'
        if tags
        else '<div id="tags" class="meme-tags"></div>'
    )

    return "".join(
        [
            '<div id="loading" class="state hidden">',
            '<div class="loader" aria-hidden="true"></div>',
            "<span>Загрузка мема...</span>",
            "</div>",
            '<div id="error" class="state error hidden"></div>',
            '<article id="meme" class="meme">',
            '<div class="image-panel">',
            f'<img id="memeImage" src="{_escape(image)}" alt="{_escape(alt)}"{size_attrs} fetchpriority="high">',
            "</div>",
            '<div class="info-panel">',
            f'<h1 id="title" class="meme-title">{_escape(title)}</h1>',
            '<div class="actions">',
            '<button id="copyBtn" type="button" class="btn">Копировать</button>',
            '<button id="downloadBtn" type="button" class="btn btn-primary">Скачать</button>',
            "</div>",
            f'<p id="description" class="meme-desc">{_escape(description)}</p>',
            tags_block,
            f'<dl id="meta" class="meta">{_meta_html(record)}</dl>',
            "</div>",
            "</article>",
        ]
    )


def render_meme_page(template: str, record: dict[str, Any], site_url: str) -> str:
    return (
        template.replace("<!--SSR_HEAD-->", _head_tags(record, site_url), 1)
        .replace("<!--SSR_CONTENT-->", render_meme_content(record, site_url), 1)
    )


def _card(record: dict[str, Any], site_url: str) -> str:
    url = meme_url(record, site_url)
    image = image_url(record, site_url)
    title = meme_title(record)
    description = _truncate(record.get("description") or "", MAX_CARD_DESCRIPTION)
    size_attrs = ""
    if record.get("width") and record.get("height"):
        size_attrs = f' width="{int(record["width"])}" height="{int(record["height"])}"'
    tags = "".join(
        f'<span class="meme-tag">#{_escape(tag)}</span>'
        for tag in (record.get("tags") or [])
    )
    tags_block = f'<div class="meme-tags">{tags}</div>' if tags else ""
    created = _escape((record.get("created_at") or "").split("T")[0])

    return "".join(
        [
            f'<a class="meme-card" href="{_escape(url)}">',
            (
                f'<img class="meme-image" src="{_escape(image)}"'
                f' alt="{_escape(description or title)}" loading="lazy"{size_attrs}>'
            ),
            '<div class="meme-content">',
            f"<h3 class=\"meme-title\">{_escape(title)}</h3>",
            f'<p class="meme-desc">{_escape(description)}</p>' if description else "",
            tags_block,
            f'<div class="meme-footer"><span class="date">{created}</span></div>',
            "</div>",
            "</a>",
        ]
    )


def render_feed(records: list[dict[str, Any]], site_url: str) -> str:
    return "".join(_card(record, site_url) for record in records)
