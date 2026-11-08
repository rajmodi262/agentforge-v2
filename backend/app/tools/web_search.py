"""AgentForge AI — Web Search Tool

Provider order:
1. Brave Search API (full web results) — when BRAVE_SEARCH_API_KEY is set
2. Wikipedia API (keyless, live encyclopedic grounding) — default fallback
3. Clearly-labelled placeholders — only if both live sources fail
"""

import re
import logging
from typing import List, Dict
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


from tenacity import retry, wait_exponential, stop_after_attempt

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3), reraise=True)
async def _execute_search(query: str, count: int) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": settings.brave_search_api_key,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()

async def web_search(query: str, count: int = 5) -> List[Dict[str, str]]:
    """Search the web using Brave Search API.

    Args:
        query: Search query string
        count: Number of results to return (max 10)

    Returns:
        List of {title, url, description} dicts
    """
    if not settings.brave_search_api_key:
        return await _wikipedia_or_placeholder(query, count)

    try:
        data = await _execute_search(query, count)
        results = []
        for item in data.get("web", {}).get("results", [])[:count]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            })

        logger.info(f"Brave Search: '{query}' → {len(results)} results")
        return results

    except Exception as e:
        logger.error(f"Brave Search error (after retries): {e}")
        return await _wikipedia_or_placeholder(query, count)


_STOP_WORDS = {
    "what", "which", "who", "whom", "how", "why", "when", "where", "is", "are", "was", "were",
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "do", "does", "did", "can",
    "could", "should", "would", "will", "be", "our", "we", "us", "their", "they", "this", "that",
    "these", "those", "with", "by", "from", "at", "as", "exact", "main", "key", "top", "most",
    "direct", "there", "any", "it", "its", "into", "about", "between", "much", "many",
    # finance jargon that matches unrelated encyclopedia pages
    "tam", "sam", "som", "cagr", "like", "size", "estimated", "current", "potential",
}


def _keywords(query: str, limit: int = 6) -> str:
    """Turn a natural-language question into a compact keyword query."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", query)
    kept = [w for w in words if w.lower() not in _STOP_WORDS]
    return " ".join(kept[:limit]) or query[:80]


async def _wikipedia_search(query: str, count: int) -> List[Dict[str, str]]:
    """Keyless live search over Wikipedia, returning intro extracts as descriptions."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": _keywords(query), "gsrlimit": count,
                "prop": "extracts|info", "exintro": 1, "explaintext": 1,
                "exsentences": 4, "inprop": "url",
            },
            headers={"User-Agent": "AgentForge-AI/1.0 (https://github.com/rajmodi262/agentforge)"},
            timeout=10.0,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    ordered = sorted(pages.values(), key=lambda p: p.get("index", 0))
    # Relevance gate: drop pages that share no meaningful keyword with the query
    terms = [w.lower() for w in _keywords(query).split() if len(w) >= 4]
    if terms:
        ordered = [
            p for p in ordered
            if any(t in f"{p.get('title', '')} {p.get('extract', '')}".lower() for t in terms)
        ]
    return [
        {
            "title": p.get("title", ""),
            "url": p.get("fullurl", ""),
            "description": (p.get("extract") or "").strip()[:700],
            "source": "wikipedia",
        }
        for p in ordered if p.get("extract")
    ]


async def _wikipedia_or_placeholder(query: str, count: int) -> List[Dict[str, str]]:
    try:
        results = await _wikipedia_search(query, count)
        logger.info(f"Wikipedia search: '{_keywords(query)}' → {len(results)} results")
        return results  # live source answered; an empty list is an honest "no match"
    except Exception as e:
        logger.warning(f"Wikipedia search failed: {e}")
    return _mock_search(query)


def _mock_search(query: str) -> List[Dict[str, str]]:
    """Return clearly-labelled placeholder results when no Brave key is set.

    These are NOT real search results. They are explicitly marked so the LLM
    does not present them as verified facts. Set BRAVE_SEARCH_API_KEY for real data.
    """
    note = "[PLACEHOLDER — no live search configured; do not cite as fact]"
    return [
        {
            "title": f"{note} Market overview: {query}",
            "url": "https://example.com/placeholder",
            "description": (
                f"Illustrative placeholder for '{query}'. No real figures available "
                f"because no live search source was reachable. Treat market size/growth as unknown."
            ),
        },
        {
            "title": f"{note} Competitive landscape: {query}",
            "url": "https://example.com/placeholder",
            "description": (
                f"Illustrative placeholder for competitors in the '{query}' space. "
                f"Real competitor data requires a configured search provider."
            ),
        },
    ]
