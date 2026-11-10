"""Re-read headline-only articles in full through Firecrawl.

83% of the stored corpus is headline + summary only (Google News JS redirects,
publishers blocking plain clients). This picks the headline-only articles most likely
to matter (relevant AND naming a known developer or a facility code, newest first),
re-reads them through Firecrawl, and queues them for re-extraction.

    python -m app.phantom.refetch --dry-run          # list candidates, spend nothing
    python -m app.phantom.refetch 10                 # pilot: 10 articles (~10 credits)
    python -m app.phantom.refetch 300                # then re-extract + rebuild:
    python -m app.phantom.run_extract && python -c "from app.phantom.pipeline import rebuild_projects; print(rebuild_projects())"

A re-read article keeps its id and URL; its old headline-only mentions are deleted so
the extractor reads the full text from scratch. robots.txt is respected (see firecrawl.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from typing import List

import httpx

from app.database import SessionLocal
from app.phantom import firecrawl
from app.phantom.models import PhArticle, PhMention
from app.phantom.resolve import facility_code
from app.phantom.sources import HEADERS, FeedItem, firecrawl_read
from app.phantom.store import _names_a_project


def candidates(limit: int) -> List[PhArticle]:
    db = SessionLocal()
    try:
        rows = (db.query(PhArticle).filter(PhArticle.relevant == True, PhArticle.text_kind == "summary")  # noqa: E712
                .order_by(PhArticle.published_at.desc()).all())
        rows = [r for r in rows if _names_a_project(r)]
        rows.sort(key=lambda r: (not facility_code(r.title), -(r.published_at.timestamp() if r.published_at else 0)))
        for r in rows:
            db.expunge(r)
        return rows[:limit]
    finally:
        db.close()


def _save(article_id, title: str, body: str) -> None:
    db = SessionLocal()
    try:
        a = db.query(PhArticle).filter(PhArticle.id == article_id).first()
        if not a:
            return
        text = f"{title}\n\n{body}"
        a.text, a.text_kind, a.content_hash, a.extracted = text, "full", hashlib.sha256(text.encode()).hexdigest(), False
        db.query(PhMention).filter(PhMention.article_id == article_id).delete()
        db.commit()
    finally:
        db.close()


async def run(limit: int) -> dict:
    todo = candidates(limit)
    b = firecrawl.reset_budget(limit + 5)  # one scrape credit each, small margin
    got, failed, t0 = 0, 0, time.time()
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for i, a in enumerate(todo, 1):
            item = FeedItem(url=a.url, title=a.title, summary="", source=a.source or "", published_at=a.published_at,
                            feed=a.feed or "", query=a.query or "")
            body = await firecrawl_read(client, item)
            if body:
                _save(a.id, a.title, body)
                got += 1
            else:
                failed += 1
            print(f"[{i}/{len(todo)}] {'FULL ' if body else 'miss '} {len(body or ''):6} chars | {a.feed:6} | {a.title[:70]}", flush=True)
            if b.spent >= b.limit - 1:
                print("budget reached — stopping", flush=True)
                break
    return {"attempted": got + failed, "full_text": got, "failed": failed, "credits": b.spent, "minutes": round((time.time() - t0) / 60, 1)}


def main(argv: List[str]) -> None:
    if "--dry-run" in argv:
        rows = candidates(10_000)
        print(f"{len(rows)} headline-only relevant articles name a project; first 15:")
        for r in rows[:15]:
            print(f"  {r.feed:6} {r.published_at:%Y-%m-%d} {r.title[:90]}" if r.published_at else f"  {r.feed:6} {r.title[:90]}")
        return
    if not firecrawl.enabled():
        sys.exit("FIRECRAWL_API_KEY is not set in backend/.env")
    limit = int(next((a for a in argv if a.isdigit()), "10"))
    print(asyncio.run(run(limit)))


if __name__ == "__main__":
    main(sys.argv[1:])
