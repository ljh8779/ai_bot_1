"""Real-time Notion API client: fetch blocks and render as HTML (with cache)."""
import json
import logging
import re
import threading
import time
import socket
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Sequence

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# In-memory cache (TTL = 10 minutes)
# ---------------------------------------------------------------------------
_CACHE_TTL = 600  # seconds
_cache: dict[str, tuple[float, str]] = {}  # page_id -> (expire_time, html)
_cache_lock = threading.Lock()
DEFAULT_FRANCHISE_ROOT_KEYWORDS = ("가맹점포용", "가맹본부용")


def _cache_get(page_id: str) -> str | None:
    with _cache_lock:
        entry = _cache.get(page_id)
        if entry and entry[0] > time.time():
            return entry[1]
        if entry:
            del _cache[page_id]
    return None


def _cache_set(page_id: str, html: str) -> None:
    with _cache_lock:
        _cache[page_id] = (time.time() + _CACHE_TTL, html)


def clear_cache(page_id: str | None = None) -> None:
    """Clear cache for a specific page or all pages."""
    with _cache_lock:
        if page_id:
            _cache.pop(page_id, None)
        else:
            _cache.clear()

_BASE = "https://api.notion.com/v1"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.notion_api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _api_get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers=_headers())
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            if e.code >= 500 and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            logger.warning("Notion API GET %s failed: %s", url, e)
            return None
        except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            logger.warning("Notion API GET %s error: %s", url, e)
            return None
        except Exception as e:
            logger.warning("Notion API GET %s error: %s", url, e)
            return None
    return None


def _api_post(url: str, data: dict | None = None) -> dict | None:
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(url, data=body, headers=_headers(), method="POST")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            if e.code >= 500 and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            logger.warning("Notion API POST %s failed: %s", url, e)
            return None
        except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            logger.warning("Notion API POST %s error: %s", url, e)
            return None
        except Exception as e:
            logger.warning("Notion API POST %s error: %s", url, e)
            return None
    return None


# ---------------------------------------------------------------------------
# Search / fetch
# ---------------------------------------------------------------------------

def search_all_pages() -> list[dict]:
    """Return all pages accessible by the integration."""
    pages: list[dict] = []
    start_cursor = None
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        data = _api_post(f"{_BASE}/search", payload)
        if not data:
            break
        for r in data.get("results", []):
            if r["object"] == "page":
                pages.append(r)
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")
    return pages


def get_page(page_id: str) -> dict | None:
    return _api_get(f"{_BASE}/pages/{page_id}")


def get_blocks(block_id: str, depth: int = 0, max_depth: int = 4) -> list[dict]:
    """Recursively fetch child blocks."""
    if depth > max_depth:
        return []
    blocks: list[dict] = []
    start_cursor = None
    while True:
        url = f"{_BASE}/blocks/{block_id}/children?page_size=100"
        if start_cursor:
            url += f"&start_cursor={start_cursor}"
        data = _api_get(url)
        if not data:
            break
        for b in data.get("results", []):
            blocks.append(b)
            if b.get("has_children") and b.get("type") not in ("child_page", "child_database"):
                b["_children"] = get_blocks(b["id"], depth + 1, max_depth)
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")
        time.sleep(0.05)
    return blocks


def get_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for val in props.values():
        if isinstance(val, dict) and val.get("type") == "title":
            title_arr = val.get("title", [])
            if title_arr:
                return title_arr[0]["plain_text"]
    return "Untitled"


# ---------------------------------------------------------------------------
# Render blocks → HTML
# ---------------------------------------------------------------------------

def _rich_text_to_html(rich_texts: list[dict]) -> str:
    parts = []
    for rt in rich_texts:
        text = rt.get("plain_text", "")
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ann = rt.get("annotations", {})
        href = rt.get("href")
        if ann.get("bold"):
            text = f"<strong>{text}</strong>"
        if ann.get("italic"):
            text = f"<em>{text}</em>"
        if ann.get("strikethrough"):
            text = f"<del>{text}</del>"
        if ann.get("underline"):
            text = f"<u>{text}</u>"
        if ann.get("code"):
            text = f"<code>{text}</code>"
        if href:
            text = f"<a href='{href}' target='_blank'>{text}</a>"
        parts.append(text)
    return "".join(parts)


def _file_url(file_obj: dict | None) -> str | None:
    if not file_obj or not isinstance(file_obj, dict):
        return None
    if file_obj.get("type") == "file":
        f = file_obj.get("file")
        return f.get("url") if f else None
    if file_obj.get("type") == "external":
        e = file_obj.get("external")
        return e.get("url") if e else None
    return None


def _blocks_to_html(blocks: list[dict]) -> str:
    parts: list[str] = []
    for b in blocks:
        btype = b.get("type", "")
        bdata = b.get(btype, {})

        if btype == "paragraph":
            text = _rich_text_to_html(bdata.get("rich_text", []))
            if text:
                parts.append(f"<p>{text}</p>")

        elif btype == "heading_1":
            parts.append(f"<h1>{_rich_text_to_html(bdata.get('rich_text', []))}</h1>")

        elif btype == "heading_2":
            parts.append(f"<h2>{_rich_text_to_html(bdata.get('rich_text', []))}</h2>")

        elif btype == "heading_3":
            parts.append(f"<h3>{_rich_text_to_html(bdata.get('rich_text', []))}</h3>")

        elif btype == "bulleted_list_item":
            text = _rich_text_to_html(bdata.get("rich_text", []))
            inner = _blocks_to_html(b.get("_children", []))
            parts.append(f"<ul><li>{text}{inner}</li></ul>")

        elif btype == "numbered_list_item":
            text = _rich_text_to_html(bdata.get("rich_text", []))
            inner = _blocks_to_html(b.get("_children", []))
            parts.append(f"<ol><li>{text}{inner}</li></ol>")

        elif btype == "to_do":
            text = _rich_text_to_html(bdata.get("rich_text", []))
            checked = "checked" if bdata.get("checked") else ""
            parts.append(f"<p><input type='checkbox' {checked} disabled /> {text}</p>")

        elif btype == "toggle":
            text = _rich_text_to_html(bdata.get("rich_text", []))
            inner = _blocks_to_html(b.get("_children", []))
            parts.append(f"<details><summary>{text}</summary>{inner}</details>")

        elif btype == "code":
            text = _rich_text_to_html(bdata.get("rich_text", []))
            lang = bdata.get("language", "")
            parts.append(f"<pre><code class='{lang}'>{text}</code></pre>")

        elif btype == "quote":
            parts.append(f"<blockquote>{_rich_text_to_html(bdata.get('rich_text', []))}</blockquote>")

        elif btype == "callout":
            text = _rich_text_to_html(bdata.get("rich_text", []))
            icon = bdata.get("icon") or {}
            emoji = icon.get("emoji", "") if icon.get("type") == "emoji" else ""
            inner = _blocks_to_html(b.get("_children", []))
            parts.append(f"<div class='callout'>{emoji} {text}{inner}</div>")

        elif btype == "divider":
            parts.append("<hr/>")

        elif btype == "image":
            url = _file_url(bdata)
            caption = _rich_text_to_html(bdata.get("caption", []))
            if url:
                alt = caption or "image"
                parts.append(f"<img src='{url}' alt='{alt}' />")

        elif btype == "file" or btype == "pdf":
            url = _file_url(bdata)
            name = bdata.get("name", "file")
            if url:
                parts.append(f"<p><a href='{url}' target='_blank'>{name}</a></p>")

        elif btype == "video":
            url = _file_url(bdata)
            if url:
                parts.append(f"<video src='{url}' controls style='max-width:100%'></video>")

        elif btype == "bookmark":
            url = bdata.get("url", "")
            caption = _rich_text_to_html(bdata.get("caption", []))
            parts.append(f"<p><a href='{url}' target='_blank'>{caption or url}</a></p>")

        elif btype == "embed":
            url = bdata.get("url", "")
            parts.append(f"<p><a href='{url}' target='_blank'>[Embed: {url}]</a></p>")

        elif btype == "table":
            if b.get("_children"):
                parts.append("<table border='1' cellpadding='6' cellspacing='0'>")
                for i, row in enumerate(b["_children"]):
                    cells = row.get("table_row", {}).get("cells", [])
                    tag = "th" if i == 0 and bdata.get("has_column_header") else "td"
                    parts.append("<tr>")
                    for cell in cells:
                        parts.append(f"<{tag}>{_rich_text_to_html(cell)}</{tag}>")
                    parts.append("</tr>")
                parts.append("</table>")

        elif btype == "column_list":
            parts.append("<div style='display:flex;gap:20px'>")
            for col in b.get("_children", []):
                parts.append("<div style='flex:1'>")
                parts.append(_blocks_to_html(col.get("_children", [])))
                parts.append("</div>")
            parts.append("</div>")

        elif btype == "child_page":
            child_id = b.get("id", "")
            child_title = bdata.get("title", "Untitled")
            parts.append(
                f"<a href='/notion/render/{child_id}' "
                f"style='display:block;padding:10px 14px;margin:6px 0;border:1px solid #d6e0e8;"
                f"border-radius:8px;background:#f6fbfe;color:#0f766e;font-weight:600;"
                f"text-decoration:none;transition:background 0.15s'"
                f" onmouseover=\"this.style.background='#e7f8fb'\" "
                f" onmouseout=\"this.style.background='#f6fbfe'\">"
                f"📄 {child_title}</a>"
            )

        elif btype == "child_database":
            parts.append(f"<p><strong>[Database: {bdata.get('title', '')}]</strong></p>")

        elif btype == "synced_block":
            parts.append(_blocks_to_html(b.get("_children", [])))

        elif btype == "link_preview":
            url = bdata.get("url", "")
            parts.append(f"<p><a href='{url}' target='_blank'>{url}</a></p>")

        elif "rich_text" in bdata:
            text = _rich_text_to_html(bdata.get("rich_text", []))
            if text:
                parts.append(f"<p>{text}</p>")

        # Children for types not already handled
        if btype not in ("bulleted_list_item", "numbered_list_item", "toggle", "callout",
                         "table", "column_list", "synced_block") and b.get("_children"):
            parts.append(_blocks_to_html(b["_children"]))

    return "\n".join(parts)


def render_page_html(page_id: str) -> str | None:
    """Fetch a Notion page and return a full standalone HTML document (cached)."""
    cached = _cache_get(page_id)
    if cached:
        return cached

    page = get_page(page_id)
    if not page:
        return None

    title = get_page_title(page)
    blocks = get_blocks(page_id)

    # Cover image
    cover_html = ""
    cover = page.get("cover")
    if cover:
        url = _file_url(cover)
        if url:
            cover_html = f"<img src='{url}' alt='cover' style='width:100%;max-height:280px;object-fit:cover;border-radius:0' />"

    body = _blocks_to_html(blocks)

    html = f"""<!doctype html>
<html lang='ko'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <title>{title}</title>
  <style>
    body{{font-family:'Noto Sans KR','Segoe UI',sans-serif;max-width:960px;margin:0 auto;padding:20px;background:#fff;color:#1f2937}}
    h1{{font-size:1.8em;margin:16px 0}}
    h2{{font-size:1.4em;margin:20px 0 10px}}
    h3{{font-size:1.15em;margin:16px 0 8px}}
    img{{max-width:100%;height:auto;border-radius:6px;margin:10px 0}}
    p{{font-size:0.95em;line-height:1.8;margin:6px 0}}
    ul,ol{{padding-left:22px}}
    a{{color:#0f766e;text-decoration:none}}
    table{{border-collapse:collapse;margin:12px 0;width:100%}}
    th{{background:#e5e7eb;padding:8px}}
    td{{padding:8px}}
    blockquote{{border-left:4px solid #9ca3af;margin:12px 0;padding:8px 16px;color:#4b5563}}
    pre{{background:#1f2937;color:#f9fafb;padding:14px;border-radius:8px;overflow-x:auto;font-size:0.85em}}
    code{{font-family:'Fira Code',monospace}}
    .callout{{background:#f3f4f6;border-radius:8px;padding:14px;margin:10px 0}}
    details{{margin:6px 0}}
    summary{{cursor:pointer;font-weight:bold}}
    hr{{border:none;border-top:1px solid #d1d5db;margin:20px 0}}
  </style>
</head>
<body>
{cover_html}
<h1>{title}</h1>
{body}
</body>
</html>"""

    _cache_set(page_id, html)
    return html


# ---------------------------------------------------------------------------
# Text extraction (for RAG ingestion)
# ---------------------------------------------------------------------------

def _blocks_to_text(blocks: list[dict]) -> str:
    """Extract plain text from blocks for RAG indexing."""
    parts: list[str] = []
    for b in blocks:
        btype = b.get("type", "")
        bdata = b.get(btype, {})

        if btype == "child_page":
            title = (bdata.get("title") or "").strip()
            if title:
                parts.append(title)

        if btype == "child_database":
            title = (bdata.get("title") or "").strip()
            if title:
                parts.append(title)

        # Extract rich_text content
        for rt in bdata.get("rich_text", []):
            text = rt.get("plain_text", "").strip()
            if text:
                parts.append(text)

        # Table cells
        if btype == "table" and b.get("_children"):
            for row in b["_children"]:
                for cell in row.get("table_row", {}).get("cells", []):
                    for rt in cell:
                        text = rt.get("plain_text", "").strip()
                        if text:
                            parts.append(text)

        # Recurse
        if b.get("_children"):
            child_text = _blocks_to_text(b["_children"])
            if child_text:
                parts.append(child_text)

    return "\n".join(parts)


def extract_page_text(page_id: str) -> tuple[str, str] | None:
    """Fetch page and return (title, plain_text) for RAG ingestion."""
    page = get_page(page_id)
    if not page:
        return None
    title = get_page_title(page)
    blocks = get_blocks(page_id)
    text = _blocks_to_text(blocks).strip()
    return title, text


def parse_notion_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    normalized = raw_value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning("Failed to parse Notion datetime: %s", raw_value)
        return None


def collect_target_pages(
    root_keywords: Sequence[str] = DEFAULT_FRANCHISE_ROOT_KEYWORDS,
    *,
    max_depth: int = 5,
) -> list[tuple[str, str, str]]:
    pages = search_all_pages()
    root_pages: list[tuple[str, str]] = []
    for page in pages:
        title = get_page_title(page)
        if any(keyword in title for keyword in root_keywords):
            root_pages.append((page["id"], title))

    results: list[tuple[str, str, str]] = []
    seen_page_ids: set[str] = set()

    def _append(page_id: str, root_id: str, root_title: str) -> None:
        if page_id in seen_page_ids:
            return
        seen_page_ids.add(page_id)
        results.append((page_id, root_id, root_title))

    def _iter_child_page_ids(blocks: Sequence[dict[str, Any]]) -> list[str]:
        child_page_ids: list[str] = []
        for block in blocks:
            if block.get("type") == "child_page":
                child_id = block.get("id", "")
                if child_id:
                    child_page_ids.append(child_id)
            nested_blocks = block.get("_children") or []
            if nested_blocks:
                child_page_ids.extend(_iter_child_page_ids(nested_blocks))
        return child_page_ids

    def _collect_child_pages(block_id: str, root_id: str, root_title: str, *, depth: int = 0) -> None:
        if depth > max_depth:
            return
        blocks = get_blocks(block_id, depth=0, max_depth=2)
        for child_id in _iter_child_page_ids(blocks):
            _append(child_id, root_id, root_title)
            _collect_child_pages(child_id, root_id, root_title, depth=depth + 1)

    for root_id, root_title in root_pages:
        _append(root_id, root_id, root_title)
        _collect_child_pages(root_id, root_id, root_title)

    return results


def extract_page_payload(page_id: str) -> dict[str, Any] | None:
    page = get_page(page_id)
    if not page:
        return None

    title = get_page_title(page)
    blocks = get_blocks(page_id)
    content_text = _blocks_to_text(blocks).strip()
    return {
        "page_id": page_id,
        "title": title,
        "url": page.get("url"),
        "last_edited_time": parse_notion_datetime(page.get("last_edited_time")),
        "properties": page.get("properties", {}),
        "content_text": content_text,
    }
