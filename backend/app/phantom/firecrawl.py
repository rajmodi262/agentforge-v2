"""Firecrawl scout — web/news search and full-text reading through the Firecrawl API.

Why: the free feeds hit two walls. Google News links are JavaScript redirects (0 of
1,165 could be read), and many publishers block plain HTTP clients, so 83% of the
corpus was headline-only. Firecrawl renders pages like a browser and returns clean
markdown, so the extractor and verifier get the article body instead of a headline.

Rules kept from the free scouts:
* robots.txt is still respected — a page the publisher disallows is never kept, even
  if Firecrawl could fetch it (checked on the final URL after redirects).
* Firecrawl is the fallback for reading: a free direct fetch is tried first, so
  credits are only spent where they buy something.
* Every run has a hard credit budget (PHANTOM_FIRECRAWL_BUDGET, default 150).

Configure with FIRECRAWL_API_KEY in backend/.env. Without a key everything falls
back to the free RSS feeds and direct fetching, exactly as before.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

API = "https://api.firecrawl.dev/v2"
SEARCH_CREDITS_PER_10 = 2   # Firecrawl bills search per 10 results
SCRAPE_CREDITS = 1


def api_key() -> Optional[str]:
    from app.config import get_settings
    return (getattr(get_settings(), "firecrawl_api_key", "") or os.environ.get("FIRECRAWL_API_KEY") or "").strip() or None


def enabled() -> bool:
    return api_key() is not None


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Hard cap on credits for one run. Charged before the call so a run never overspends."""

    def __init__(self, credits: Optional[int] = None):
        from app.config import get_settings
        self.limit = credits if credits is not None else int(getattr(get_settings(), "phantom_firecrawl_budget", 150))
        self.spent = 0
        self.calls = {"search": 0, "scrape": 0}

    def charge(self, kind: str, credits: int) -> None:
        if self.spent + credits > self.limit:
            raise BudgetExceeded(f"Firecrawl budget of {self.limit} credits reached ({self.spent} spent)")
        self.spent += credits
        self.calls[kind] += 1


_default_budget: Optional[Budget] = None


def budget() -> Budget:
    global _default_budget
    if _default_budget is None:
        _default_budget = Budget()
    return _default_budget


def reset_budget(credits: Optional[int] = None) -> Budget:
    global _default_budget
    _default_budget = Budget(credits)
    return _default_budget


def _headers() -> dict:
    return {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"}


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in (None, "%b %d, %Y", "%d %b %Y"):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00")) if fmt is None else datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None  # relative dates ("3 days ago") are left to the article's own metadata


MIN_INTERVAL_S = 6.5   # ≈9 requests/minute: under the free plan's per-minute limit
MAX_429_RETRIES = 4
_pace_lock: dict = {}
_last_call = [0.0]


async def _post(client: httpx.AsyncClient, path: str, payload: dict, timeout: float, b: Budget, kind: str, credits: int) -> httpx.Response:
    """POST with pacing and 429 handling. Credits are only counted for calls that were not rate-limited."""
    import asyncio
    import time
    loop_id = id(asyncio.get_running_loop())
    lock = _pace_lock.setdefault(loop_id, asyncio.Lock())
    if b.spent + credits > b.limit:
        raise BudgetExceeded(f"Firecrawl budget of {b.limit} credits reached ({b.spent} spent)")
    for attempt in range(MAX_429_RETRIES + 1):
        async with lock:  # one request at a time, evenly spaced
            interval = float(os.environ.get("PHANTOM_FIRECRAWL_INTERVAL") or MIN_INTERVAL_S)  # parallel jobs share the plan's rate limit
            wait = _last_call[0] + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call[0] = time.monotonic()
        r = await client.post(f"{API}{path}", headers=_headers(), timeout=timeout, json=payload)
        if r.status_code != 429:
            b.charge(kind, credits)
            return r
        try:
            retry = float((r.json() or {}).get("retry_after_seconds") or 0)
        except Exception:
            retry = 0.0
        retry = retry or float(r.headers.get("retry-after", 0) or 0) or 10.0
        logger.info(f"[firecrawl] 429 rate limit — waiting {retry:.0f}s (attempt {attempt + 1})")
        await asyncio.sleep(retry + 1)
    return r


async def search(client: httpx.AsyncClient, query: str, country: str, limit: int = 10, b: Optional[Budget] = None):
    """News + web results for a query. Returns sources.FeedItem objects (feed="firecrawl")."""
    from app.phantom.sources import FeedItem, _strip_html
    b = b or budget()
    r = await _post(client, "/search", {"query": query, "limit": limit, "sources": [{"type": "news"}, {"type": "web"}],
                                        "location": country, "tbs": "qdr:y"},
                    60, b, "search", SEARCH_CREDITS_PER_10 * max(1, (limit + 9) // 10))
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    out = []
    for kind in ("news", "web"):
        for h in data.get(kind) or []:
            url = h.get("url")
            if not url:
                continue
            out.append(FeedItem(url=url, title=_strip_html(h.get("title") or ""),
                                summary=_strip_html(h.get("snippet") or h.get("description") or ""),
                                source=h.get("source") or httpx.URL(url).host, published_at=_parse_date(h.get("date")),
                                feed="firecrawl", query=query))
    return out


@dataclass
class Page:
    markdown: str
    final_url: str
    title: str
    published_at: Optional[datetime]


async def scrape(client: httpx.AsyncClient, url: str, b: Optional[Budget] = None) -> Optional[Page]:
    """Main-content markdown of one page (follows redirects, renders JavaScript)."""
    b = b or budget()
    r = await _post(client, "/scrape", {"url": url, "formats": ["markdown"], "onlyMainContent": True, "removeBase64Images": True},
                    90, b, "scrape", SCRAPE_CREDITS)
    if r.status_code != 200:
        logger.info(f"[firecrawl] scrape {r.status_code} for {url}")
        return None
    data = (r.json() or {}).get("data") or {}
    meta = data.get("metadata") or {}
    md = data.get("markdown") or ""
    if not md or (meta.get("statusCode") and int(meta["statusCode"]) >= 400):
        return None
    published = meta.get("publishedTime") or meta.get("article:published_time") or meta.get("og:article:published_time")
    return Page(markdown=md, final_url=meta.get("url") or meta.get("sourceURL") or url,
                title=meta.get("title") or meta.get("og:title") or "", published_at=_parse_date(published))


def clean_markdown(md: str) -> str:
    """Drop link targets and image syntax so the verifier sees prose, not URLs."""
    import re
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)              # images
    md = re.sub(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)", r"\1", md)  # links → their text
    md = re.sub(r"^\s*[#>*\-|]+\s*", "", md, flags=re.M)        # headings, quotes, bullets, table pipes
    md = re.sub(r"\*\*|__", "", md)                             # bold markers ("**150MW**" → "150MW")
    return re.sub(r"\n{3,}", "\n\n", md).strip()
