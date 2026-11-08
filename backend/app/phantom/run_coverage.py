"""Ablation: what does the Coverage agent add over the fixed seed queries?

usage: python -m app.phantom.run_coverage

Snapshot the projects → let the Coverage agent write follow-up queries from
what was found (single-source projects, missing capacity / stage, unseen
developers) → scout + extract only the new articles → rebuild → diff.
Writes the result to phantom_coverage.json (read by evaluate.py).
"""

import asyncio
import json
from pathlib import Path

from app.database import SessionLocal, init_db
from app.phantom.extract import extract_article
from app.phantom.models import PhProject
from app.phantom.pipeline import project_gaps, rebuild_projects, unseen_developers
from app.phantom.sources import fetch_all, search
from app.phantom.store import pending_articles, save_articles, save_mentions

OUT = Path(__file__).resolve().parents[3] / "phantom_coverage.json"


def snapshot():
    db = SessionLocal()
    try:
        return {p.name: {"sources": p.n_sources, "stage": p.stage, "score": p.reality_score} for p in db.query(PhProject).all()}
    finally:
        db.close()


async def main():
    init_db()
    before = snapshot()
    queries = {r: list(dict.fromkeys(project_gaps(20) + unseen_developers(r)))[:16] for r in ("malaysia", "india")}
    found = {}
    for region, qs in queries.items():
        items = await search(qs, region, feeds=("bing", "google"))
        fetched = await fetch_all(items, concurrency=8)
        found[region] = save_articles(fetched)
        print(region, len(qs), "queries →", len(items), "items →", found[region], flush=True)
    todo = pending_articles(400)
    print("extracting", len(todo), "new articles", flush=True)
    for i, a in enumerate(todo, 1):
        try:
            r = await extract_article(a["title"], a["text"], str(a["published"]) if a["published"] else None)
            await asyncio.to_thread(save_mentions, a["id"], r["mentions"], r["meta"].get("model") or "")
        except Exception as e:
            print("  error", repr(e)[:100], flush=True)
        if i % 10 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
    rebuild_projects()
    after = snapshot()
    new = [n for n in after if n not in before]
    more_sources = [n for n in after if n in before and after[n]["sources"] > before[n]["sources"]]
    upgraded = [n for n in after if n in before and after[n]["stage"] > before[n]["stage"]]
    result = {"queries": queries, "articles": found, "new_articles_read": len(todo),
              "projects_before": len(before), "projects_after": len(after),
              "new_projects": new, "more_sources": more_sources, "stage_upgrades": upgraded}
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items() if k != "queries"}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
