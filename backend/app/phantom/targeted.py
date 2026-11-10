"""Targeted Firecrawl scouting — three jobs beyond the general hunt.

    python -m app.phantom.targeted gaps        # recall gaps: sites the recall check says we missed
    python -m app.phantom.targeted official    # official sources: approvals, clearances, utility & investment notices
    python -m app.phantom.targeted outcomes    # what happened to projects first seen before the backtest cutoff

Each job writes search queries, runs them through Firecrawl search, reads the hits
(direct fetch first, Firecrawl fallback, robots.txt respected) and stores them as normal
articles (feed = gaps | official | outcomes). The extractor and verifier then treat them
exactly like any other source: nothing is trusted because of where it came from.

Credit budget per job: PHANTOM_FIRECRAWL_BUDGET (or --budget N). Jobs can run in
parallel; set PHANTOM_FIRECRAWL_INTERVAL so their combined rate stays under the plan limit.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from app.phantom import firecrawl
from app.phantom.sources import fetch_all, is_relevant, search
from app.phantom.store import save_articles

CUTOFF = datetime(2024, 6, 30, tzinfo=timezone.utc)   # backtest: score as of this date, outcome after it
ROOT = Path(__file__).resolve().parents[3]

# Official / primary domains: governments, investment agencies, utilities, regulators, exchanges
OFFICIAL = {
    "india": ["pib.gov.in", "parivesh.nic.in", "investindia.gov.in", "maharashtra.gov.in", "telangana.gov.in",
              "tn.gov.in", "up.gov.in", "ap.gov.in", "mahadiscom.in", "bseindia.com", "nseindia.com"],
    "malaysia": ["mida.gov.my", "tnb.com.my", "johor.gov.my", "investselangor.my", "iskandarmalaysia.com.my",
                 "bursamalaysia.com", "mdec.my"],
}
OFFICIAL_TOPICS = {
    "india": ["data centre approved state cabinet MW", "data centre policy approval investment data center",
              "data center environmental clearance MW", "data centre land allotment acres", "data centre power supply MW substation"],
    "malaysia": ["data centre approved investment MW", "data centre electricity supply agreement MW",
                 "data centre green lane approval", "data centre land acquisition acres Johor", "data centre MIDA approved projects"],
}


def _q(developer, project, place) -> str:
    """Short search query: developer + project + place, without parentheses or repeated words."""
    import re as _re
    words, seen = [], set()
    for w in _re.sub(r"\([^)]*\)", " ", f"{developer or ''} {project or ''} {place or ''} data centre").split():
        k = w.lower().strip(",.")
        if k and k not in seen:
            seen.add(k)
            words.append(w)
    return " ".join(words)


def gap_queries() -> Dict[str, List[str]]:
    from app.phantom.recall import load_reference, match, projects_from_db
    rows = match(load_reference(), projects_from_db())
    out: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        if r["pipeline"] and r["verdict"] in ("missing", "other_site", "place_unknown"):
            region = "india" if r["country"] == "India" else "malaysia"
            out[region].append(_q(r["developer"], r["project"], r["city"]))
    out["india"] += ["Kolkata data centre MW hyperscale", "New Town Kolkata data centre campus", "West Bengal data centre MW investment"]
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def official_queries() -> Dict[str, List[str]]:
    return {region: [f"{topic} site:{dom}" for dom in doms[:4] for topic in OFFICIAL_TOPICS[region][:2]]
            + [f"{topic} site:{doms[i % len(doms)]}" for i, topic in enumerate(OFFICIAL_TOPICS[region][2:], start=4)]
            for region, doms in OFFICIAL.items()}


def outcome_projects() -> List[Dict]:
    from app.database import SessionLocal
    from app.phantom.models import PhProject
    db = SessionLocal()
    try:
        return [{"id": str(p.id), "name": p.name, "developer": p.developer, "city": p.city, "state": p.state, "country": p.country}
                for p in db.query(PhProject).filter(PhProject.first_seen <= CUTOFF).all()]
    finally:
        db.close()


def outcome_queries() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = defaultdict(list)
    for p in outcome_projects():
        region = "india" if p["country"] == "India" else "malaysia"
        where = p["city"] or p["state"] or ""
        out[region].append(_q(p["developer"], p["name"], where))
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


JOBS = {"gaps": gap_queries, "official": official_queries, "outcomes": outcome_queries}


async def run(job: str, budget: int) -> Dict:
    queries = JOBS[job]()
    firecrawl.reset_budget(budget)
    stats = {"job": job, "queries": sum(len(v) for v in queries.values()), "found": 0, "relevant": 0, "full_text": 0, "new": 0}
    for region, qs in queries.items():
        try:
            items = await search(qs, region, feeds=("firecrawl",))
        except firecrawl.BudgetExceeded:
            items = []
        items = [replace(i, feed=job) for i in items]
        stats["found"] += len(items)
        # read only what can matter: the headline/snippet already looks like data-centre project news
        keep = [i for i in items if is_relevant(i.title, i.summary) or job == "official"]
        fetched = await fetch_all(keep, concurrency=3)
        saved = await asyncio.to_thread(save_articles, fetched)
        stats["relevant"] += sum(1 for a in fetched if is_relevant(a.item.title, a.text))
        stats["full_text"] += sum(1 for a in fetched if a.text_kind == "full")
        stats["new"] += saved["new"]
    b = firecrawl.budget()
    stats.update(credits=b.spent, calls=b.calls)
    (ROOT / f"phantom_targeted_{job}.json").write_text(json.dumps({**stats, "queries_by_region": queries}, indent=2, default=str), encoding="utf-8")
    return stats


def main(argv: List[str]) -> None:
    job = next((a for a in argv if a in JOBS), None)
    if not job:
        sys.exit(f"usage: python -m app.phantom.targeted {'|'.join(JOBS)} [--budget N] [--dry-run]")
    if "--dry-run" in argv:
        for region, qs in JOBS[job]().items():
            print(f"{region}: {len(qs)} queries")
            for q in qs[:8]:
                print("  ", q)
        return
    if not firecrawl.enabled():
        sys.exit("FIRECRAWL_API_KEY is not set in backend/.env")
    budget = int(argv[argv.index("--budget") + 1]) if "--budget" in argv else 120
    print(asyncio.run(run(job, budget)))


if __name__ == "__main__":
    main(sys.argv[1:])
