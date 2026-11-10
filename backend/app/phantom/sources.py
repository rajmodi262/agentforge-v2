"""Scouts: find and fetch public news about data-centre projects.

Three independent feeds (Bing News RSS, Google News RSS, GDELT DOC API) are
queried in parallel; results are de-duplicated by URL and title, then each
article page is fetched politely:

* robots.txt is honoured (a disallowed page is kept as its feed summary only),
* the client identifies itself honestly — no browser impersonation,
* at most one request per second per domain, GDELT at most one every 5 s,
* everything is cached in the database, so a page is fetched once.

When a publisher blocks the fetch, the article keeps its headline + feed
summary and is marked text_kind="summary" — weaker evidence, scored as such.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import urllib.parse as up
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "PhantomHunter/0.1 (research prototype; +https://github.com/rajmodi262/agentforge)"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en"}

# ── Regions: where to hunt, and which feed locale to ask for ──
REGIONS = {
    "india": {
        "country": "India",
        "bing_mkt": "en-IN",
        "google": ("en-IN", "IN", "IN:en"),
        "places": ["Mumbai", "Navi Mumbai", "Chennai", "Hyderabad", "Noida", "Pune", "Bengaluru", "Kolkata", "Visakhapatnam", "Ahmedabad"],
        "developers": ["Yotta", "CtrlS", "AdaniConneX", "NTT Data", "STT GDC India", "Sify", "Nxtra", "Princeton Digital Group", "Equinix India", "Reliance Jio data centre", "Colt DCS India", "Digital Connexion"],
    },
    "malaysia": {
        "country": "Malaysia",
        "bing_mkt": "en-MY",
        "google": ("en-MY", "MY", "MY:en"),
        "places": ["Johor", "Johor Bahru", "Kulai", "Sedenak", "Iskandar Puteri", "Cyberjaya", "Kulim", "Negeri Sembilan", "Selangor"],
        "developers": ["YTL", "AirTrunk Johor", "Bridge Data Centres", "Princeton Digital Group Johor", "STACK Infrastructure Malaysia", "Vantage Data Centers Malaysia", "Equinix Johor", "Yondr Johor", "DayOne", "K2 Strategic", "Microsoft Malaysia data centre", "Google Malaysia data centre"],
    },
}

SEED_TEMPLATES = [
    "data centre {place} MW",
    "data center campus {place} megawatt",
    "hyperscale data centre {place}",
]
DEVELOPER_TEMPLATES = ["{dev} data centre MW", "{dev} data center campus"]

# A story is worth extracting only if it is about a data centre AND gives some
# hard detail (capacity, campus, power, construction …).
_DC = re.compile(r"data[\s-]?cent(?:er|re)s?|datacent|hyperscale|colocation|\bDC\b campus", re.I)
_DETAIL = re.compile(r"\b\d+(?:\.\d+)?\s?(?:MW|GW|megawatt|gigawatt)s?\b|campus|acres?|power purchase|PPA|substation|ground[- ]?break|commission|construction", re.I)


@dataclass
class FeedItem:
    url: str
    title: str
    summary: str
    source: str
    published_at: Optional[datetime]
    feed: str
    query: str


@dataclass
class FetchedArticle:
    item: FeedItem
    text: str
    text_kind: str  # "full" | "summary"
    content_hash: str = field(default="")


def is_relevant(title: str, text: str) -> bool:
    blob = f"{title}\n{text[:4000]}"
    return bool(_DC.search(blob) and _DETAIL.search(blob))


def seed_queries(region: str) -> list[str]:
    cfg = REGIONS[region]
    qs = [t.format(place=p) for p in cfg["places"] for t in SEED_TEMPLATES[:2]]
    qs += [t.format(dev=d) for d in cfg["developers"] for t in DEVELOPER_TEMPLATES[:1]]
    return list(dict.fromkeys(qs))


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def normalise_title(t: str) -> str:
    t = re.sub(r"\s[-|–]\s[^-|–]{2,60}$", "", t)  # drop " - Publisher" suffixes
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


# ───────────────────────────── feeds ─────────────────────────────

async def bing_news(client: httpx.AsyncClient, query: str, region: str) -> list[FeedItem]:
    r = await client.get("https://www.bing.com/news/search",
                         params={"q": query, "format": "rss", "setmkt": REGIONS[region]["bing_mkt"]})
    r.raise_for_status()
    out = []
    for e in feedparser.parse(r.text).entries:
        real = up.parse_qs(up.urlparse(e.link).query).get("url", [e.link])[0]
        out.append(FeedItem(url=real, title=_strip_html(e.title), summary=_strip_html(e.get("description", "")),
                            source=(e.get("news_source") or up.urlparse(real).netloc), published_at=_parse_date(e.get("published")),
                            feed="bing", query=query))
    return out


async def google_news(client: httpx.AsyncClient, query: str, region: str) -> list[FeedItem]:
    hl, gl, ceid = REGIONS[region]["google"]
    r = await client.get("https://news.google.com/rss/search", params={"q": query, "hl": hl, "gl": gl, "ceid": ceid})
    r.raise_for_status()
    out = []
    for e in feedparser.parse(r.text).entries:
        src = e.get("source", {}).get("title") if isinstance(e.get("source"), dict) else None
        out.append(FeedItem(url=e.link, title=_strip_html(e.title), summary=_strip_html(e.get("summary", "")),
                            source=src or "Google News", published_at=_parse_date(e.get("published")),
                            feed="google", query=query))
    return out


_gdelt_lock = asyncio.Lock()
_gdelt_last = [0.0]


async def gdelt(client: httpx.AsyncClient, query: str, region: str) -> list[FeedItem]:
    """GDELT allows one request every 5 seconds — serialise and space the calls."""
    async with _gdelt_lock:
        wait = _gdelt_last[0] + 5.5 - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _gdelt_last[0] = time.monotonic()
        r = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params={
            "query": f"{query} sourcelang:english", "mode": "ArtList", "format": "json",
            "maxrecords": "50", "timespan": "24months", "sort": "datedesc",
        })
    if r.status_code != 200 or not r.text.strip().startswith("{"):
        return []
    out = []
    for a in r.json().get("articles", []):
        try:
            d = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            d = None
        out.append(FeedItem(url=a["url"], title=a.get("title", ""), summary="", source=a.get("domain", ""),
                            published_at=d, feed="gdelt", query=query))
    return out


_fc_sems: dict = {}


def _fc_sem() -> asyncio.Semaphore:
    """Firecrawl concurrency limit (free-tier friendly), one per event loop."""
    loop = asyncio.get_running_loop()
    return _fc_sems.setdefault(id(loop), asyncio.Semaphore(4))


async def firecrawl_news(client: httpx.AsyncClient, query: str, region: str) -> list[FeedItem]:
    from app.phantom import firecrawl
    async with _fc_sem():
        return await firecrawl.search(client, query, REGIONS[region]["country"])


FEEDS = {"bing": bing_news, "google": google_news, "gdelt": gdelt, "firecrawl": firecrawl_news}


def default_feeds() -> tuple:
    """Firecrawl when a key is configured (PHANTOM_SEARCH=auto), else the free feeds."""
    from app.config import get_settings
    from app.phantom import firecrawl
    mode = (get_settings().phantom_search or "auto").lower()
    free = ("bing", "google", "gdelt")
    if mode == "feeds" or not firecrawl.enabled():
        return free
    return ("firecrawl", *free) if mode == "both" else ("firecrawl",)


async def search(queries: Iterable[str], region: str, feeds: Optional[Iterable[str]] = None) -> list[FeedItem]:
    """Run every query on every feed; return de-duplicated items (by URL and by title)."""
    feeds = list(feeds) if feeds is not None else list(default_feeds())
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        tasks = [FEEDS[f](client, q, region) for q in queries for f in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    seen_url, seen_title, items = set(), set(), []
    for res in results:
        if isinstance(res, Exception):
            logger.warning(f"[scout] feed error: {res!r}")
            continue
        for it in res:
            t = normalise_title(it.title)
            if not it.url or it.url in seen_url or (t and t in seen_title):
                continue
            seen_url.add(it.url)
            if t:
                seen_title.add(t)
            items.append(it)
    return items


# ───────────────────────────── fetch ─────────────────────────────

_robots: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
_domain_last: dict[str, float] = {}
_domain_lock: dict[str, asyncio.Lock] = {}


async def _allowed(client: httpx.AsyncClient, url: str) -> bool:
    parts = up.urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = await client.get(f"{base}/robots.txt", timeout=8)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            _robots[base] = rp
        except Exception:
            _robots[base] = None  # unreachable robots.txt → be conservative, but don't fail the run
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def _looks_blocked(text: str) -> bool:
    low = text[:600].lower()
    return len(text) < 400 or any(s in low for s in ("access denied", "enable javascript", "captcha", "are you a robot", "403 forbidden"))


async def fetch_article(client: httpx.AsyncClient, item: FeedItem) -> FetchedArticle:
    """Full text when allowed and reachable; otherwise the feed's headline + summary."""
    fallback = f"{item.title}. {item.summary}".strip()
    text, kind = fallback, "summary"
    if item.feed != "google":  # Google News links are JS redirects — keep the summary
        try:
            if await _allowed(client, item.url):
                dom = up.urlparse(item.url).netloc
                lock = _domain_lock.setdefault(dom, asyncio.Lock())
                async with lock:
                    wait = _domain_last.get(dom, 0) + 1.0 - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    _domain_last[dom] = time.monotonic()
                    r = await client.get(item.url, timeout=20)
                if r.status_code == 200:
                    import trafilatura
                    body = trafilatura.extract(r.text, include_comments=False, include_tables=True) or ""
                    if not _looks_blocked(body):
                        text, kind = f"{item.title}\n\n{body}", "full"
        except Exception as e:
            logger.debug(f"[scout] fetch failed {item.url}: {e!r}")
    if kind == "summary":
        body = await firecrawl_read(client, item)
        if body:
            text, kind = f"{item.title}\n\n{body}", "full"
    return FetchedArticle(item=item, text=text, text_kind=kind, content_hash=hashlib.sha256(text.encode()).hexdigest())


async def firecrawl_read(client: httpx.AsyncClient, item: FeedItem) -> Optional[str]:
    """Fallback reader for pages a plain fetch can't get (bot walls, Google News JS redirects).
    The publisher's robots.txt still decides: checked on the final URL after redirects."""
    from app.phantom import firecrawl
    if not firecrawl.enabled():
        return None
    try:
        if item.feed != "google" and not await _allowed(client, item.url):
            return None
        async with _fc_sem():
            page = await firecrawl.scrape(client, item.url)
        if not page or "news.google." in page.final_url or not await _allowed(client, page.final_url):
            return None  # still on Google's redirect page = no publisher article
        body = firecrawl.clean_markdown(page.markdown)
        return None if _looks_blocked(body) else body
    except firecrawl.BudgetExceeded as e:
        logger.info(f"[scout] {e}")
    except Exception as e:
        logger.debug(f"[scout] firecrawl read failed {item.url}: {e!r}")
    return None


async def fetch_all(items: list[FeedItem], concurrency: int = 6) -> list[FetchedArticle]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        async def one(it):
            async with sem:
                return await fetch_article(client, it)
        return await asyncio.gather(*(one(i) for i in items))
