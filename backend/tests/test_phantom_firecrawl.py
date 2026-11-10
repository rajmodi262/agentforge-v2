"""Firecrawl scout — parsing, credit budget, robots and redirect guards. No network: a fake API."""

import asyncio
import json

import httpx
import pytest

from app.phantom import firecrawl, sources
from app.phantom.sources import FeedItem


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _item(url="https://news.example.com/a", feed="bing"):
    return FeedItem(url=url, title="AirTrunk JHB2 signs PPA", summary="", source="x", published_at=None, feed=feed, query="q")


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(firecrawl, "api_key", lambda: "fc-test")
    monkeypatch.setattr(firecrawl, "MIN_INTERVAL_S", 0)
    sources._robots.clear()
    firecrawl.reset_budget(50)


ARTICLE = "# AirTrunk JHB2\n\n![logo](x.png) AirTrunk **signed** a [power purchase agreement](https://x) with TNB for its 150MW JHB2 campus in Johor. " * 5


def test_search_parses_news_and_web_and_charges_credits(key):
    def handler(req):
        assert req.url.path == "/v2/search" and req.headers["Authorization"] == "Bearer fc-test"
        assert json.loads(req.content)["location"] == "Malaysia"
        return httpx.Response(200, json={"success": True, "data": {
            "news": [{"title": "JHB2 PPA", "url": "https://news.example.com/a", "snippet": "AirTrunk...", "date": "2026-10-01T00:00:00Z"}],
            "web": [{"title": "JHB2", "url": "https://web.example.com/b", "description": "campus"}]}})

    async def go():
        async with _client(handler) as c:
            return await firecrawl.search(c, "AirTrunk JHB2", "Malaysia", limit=10)
    items = asyncio.run(go())
    assert [i.feed for i in items] == ["firecrawl", "firecrawl"] and items[0].published_at.year == 2026
    assert firecrawl.budget().spent == 2


def test_budget_is_a_hard_cap(key):
    firecrawl.reset_budget(2)
    b = firecrawl.budget()
    b.charge("scrape", 1)
    b.charge("scrape", 1)
    with pytest.raises(firecrawl.BudgetExceeded):
        b.charge("scrape", 1)


def test_clean_markdown_keeps_prose_for_the_verifier():
    md = firecrawl.clean_markdown(ARTICLE)
    assert "signed a power purchase agreement with TNB" in md and "](" not in md and "**" not in md


def _robots_and_scrape(robots_txt, final_url="https://news.example.com/a"):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_txt)
        if req.url.host == "api.firecrawl.dev":
            return httpx.Response(200, json={"success": True, "data": {"markdown": ARTICLE, "metadata": {"url": final_url, "statusCode": 200}}})
        return httpx.Response(404)
    return handler


def test_firecrawl_read_returns_clean_full_text(key):
    async def go():
        async with _client(_robots_and_scrape("User-agent: *\nAllow: /")) as c:
            return await sources.firecrawl_read(c, _item())
    body = asyncio.run(go())
    assert body and "150MW JHB2 campus" in body


def test_robots_disallow_is_respected_even_through_firecrawl(key):
    async def go():
        async with _client(_robots_and_scrape("User-agent: *\nDisallow: /")) as c:
            return await sources.firecrawl_read(c, _item())
    assert asyncio.run(go()) is None
    assert firecrawl.budget().spent == 0          # nothing was bought for a disallowed page


def test_google_redirect_page_is_not_an_article(key):
    async def go():
        async with _client(_robots_and_scrape("", final_url="https://news.google.com/rss/articles/abc")) as c:
            return await sources.firecrawl_read(c, _item("https://news.google.com/rss/articles/abc", feed="google"))
    assert asyncio.run(go()) is None


def test_default_feeds_follow_the_key(monkeypatch):
    monkeypatch.setattr(firecrawl, "api_key", lambda: None)
    assert sources.default_feeds() == ("bing", "google", "gdelt")
    monkeypatch.setattr(firecrawl, "api_key", lambda: "fc-test")
    assert sources.default_feeds() == ("firecrawl",)


def test_rate_limit_waits_retries_and_is_not_charged(key, monkeypatch):
    calls = []

    async def no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"success": False, "retry_after_seconds": 7})
        return httpx.Response(200, json={"success": True, "data": {"markdown": ARTICLE, "metadata": {"url": "https://x.example/a", "statusCode": 200}}})

    async def go():
        async with _client(handler) as c:
            return await firecrawl.scrape(c, "https://x.example/a")
    page = asyncio.run(go())
    assert page and len(calls) == 3
    assert firecrawl.budget().spent == 1          # two rate-limited attempts cost nothing
