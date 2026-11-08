"""Persistence helpers for Phantom Hunter (blocking SQLAlchemy — call via asyncio.to_thread)."""

from __future__ import annotations

from typing import Iterable, List

from app.database import SessionLocal
from app.phantom.models import PhArticle, PhMention
from app.phantom.sources import FetchedArticle, is_relevant, normalise_title


def save_articles(fetched: Iterable[FetchedArticle]) -> dict:
    """Insert new articles (skip URLs / titles / bodies we already have). Returns counts."""
    db = SessionLocal()
    new = dup = 0
    try:
        known_urls = {u for (u,) in db.query(PhArticle.url).all()}
        known_hash = {h for (h,) in db.query(PhArticle.content_hash).all()}
        known_titles = {normalise_title(t) for (t,) in db.query(PhArticle.title).all()}
        for a in fetched:
            t = normalise_title(a.item.title)
            if a.item.url in known_urls or a.content_hash in known_hash or (t and t in known_titles):
                dup += 1
                continue
            db.add(PhArticle(
                url=a.item.url[:1000], title=a.item.title[:500], source=(a.item.source or "")[:200], feed=a.item.feed,
                query=a.item.query[:300], published_at=a.item.published_at, text=a.text, text_kind=a.text_kind,
                content_hash=a.content_hash, relevant=is_relevant(a.item.title, a.text),
            ))
            known_urls.add(a.item.url); known_hash.add(a.content_hash); known_titles.add(t)
            new += 1
        db.commit()
    finally:
        db.close()
    return {"new": new, "duplicates": dup}


def _names_a_project(r: PhArticle) -> bool:
    """Headline-only items are worth an LLM call only if they name a known developer or a facility code."""
    import re
    from app.phantom.extract import KNOWN_DEVELOPERS
    from app.phantom.resolve import facility_code
    from app.phantom.verify import norm
    t = norm(f"{r.title}. {r.text}")
    return bool(facility_code(r.title)) or any(re.search(rf"\b{re.escape(a)}\b", t) for al in KNOWN_DEVELOPERS.values() for a in al)


def pending_articles(limit: int = 1000) -> List[dict]:
    db = SessionLocal()
    try:
        rows = (db.query(PhArticle).filter(PhArticle.relevant == True, PhArticle.extracted == False)  # noqa: E712
                .order_by(PhArticle.text_kind.asc(), PhArticle.published_at.desc()).all())
        rows = [r for r in rows if r.text_kind == "full" or _names_a_project(r)][:limit]
        return [{"id": r.id, "title": r.title, "text": r.text, "published": r.published_at, "kind": r.text_kind} for r in rows]
    finally:
        db.close()


def save_mentions(article_id, mentions: List[dict], model: str) -> int:
    db = SessionLocal()
    try:
        art = db.query(PhArticle).filter(PhArticle.id == article_id).first()
        for m in mentions:
            db.add(PhMention(article_id=article_id, data=m["data"], verification=m["verification"],
                             verified_ratio=m["verified_ratio"], model=model))
        if art:
            art.extracted = True
        db.commit()
        return len(mentions)
    finally:
        db.close()
