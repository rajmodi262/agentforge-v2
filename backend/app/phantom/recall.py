"""Recall check — how many real projects did Phantom Hunter miss?

The reference list (PHANTOM_RECALL_REFERENCE.csv) was built independently of the hunt:
project lists on Wikipedia, Black Ridge Research, Mordor Intelligence and Data Center
Knowledge, extracted with Firecrawl and cleaned by hand (one row per site, with its source).

Each reference project is matched to our resolved projects:

* found          — same developer group AND same state
* place unknown  — same developer group, our project has no stated location
* other site     — developer tracked in that country, but not at this site
* missing        — developer never seen in that country

"Pipeline" rows (announced / under construction, or dated 2025+) are what Phantom Hunter
is built to track; long-operational sites are reported separately.

    python -m app.phantom.recall
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.phantom.resolve import canonical_developer, facility_code

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "PHANTOM_RECALL_REFERENCE.csv"

# Brands that are the same company (parent ↔ data-centre arm, JV, operating name)
GROUPS = [
    {"Airtel", "Nxtra"},
    {"Adani", "Adani Enterprises", "AdaniConneX"},
    {"DayOne", "GDS", "DayOne (GDS)"},
    {"Google", "Pearl Computing Malaysia", "Pearl Computing Malaysia (Google)"},
    {"Digital Realty", "Digital Connexion"},
    {"Telekom Malaysia", "TM Nxera"},
    {"STT GDC", "ST Telemedia Global Data Centres"},
]
LABELS = {"found": "✅ found", "place_unknown": "🟡 found, location not stated", "other_site": "🟠 developer tracked, not this site",
          "missing": "❌ missing"}


def dev_key(name: Optional[str]) -> Optional[str]:
    c = canonical_developer(name) if name else None
    if not c:
        return None
    for g in GROUPS:
        if c in g or (name or "") in g:
            return sorted(g)[0]
    return c


def is_pipeline(ref: Dict[str, Any]) -> bool:
    return ref["status"] != "operational" or (ref.get("year") or "") >= "2025"


def load_reference(path: Path = REFERENCE) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def match(reference: List[Dict[str, Any]], projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """projects: dicts with name, developer, state, country, capacity_mw, stage_name, reality_score."""
    ours = [{**p, "_dev": dev_key(p.get("developer")) or dev_key(p.get("name"))} for p in projects]
    out = []
    for r in reference:
        dk = dev_key(r["developer"])
        same_dev = [p for p in ours if p["_dev"] and p["_dev"] == dk and p.get("country") == r["country"]]
        # a facility code is identity: our "AirTrunk JHB1" is not the reference "JHB2" even in the same state
        code = facility_code(r["project"])
        here = [p for p in same_dev if (p.get("state") or "") == r["state"]
                and not (code and facility_code(p["name"]) and facility_code(p["name"]) != code)]
        unplaced = [p for p in same_dev if not p.get("state") or p.get("state") == "Place not stated"]
        if here:
            verdict, hits = "found", here
        elif unplaced:
            verdict, hits = "place_unknown", unplaced
        elif same_dev:
            verdict, hits = "other_site", same_dev
        else:
            verdict, hits = "missing", []
        best = max(hits, key=lambda p: (p.get("capacity_mw") or 0)) if hits else None
        out.append({**r, "verdict": verdict, "pipeline": is_pipeline(r), "n_matches": len(hits),
                    "our_project": best["name"] if best else None,
                    "our_stage": best.get("stage_name") if best else None,
                    "our_score": best.get("reality_score") if best else None})
    return out


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rates(sub):
        n = len(sub)
        c = Counter(r["verdict"] for r in sub)
        return {"n": n, **{k: c.get(k, 0) for k in LABELS},
                "strict": round(100 * c.get("found", 0) / n, 1) if n else 0.0,
                "lenient": round(100 * (c.get("found", 0) + c.get("place_unknown", 0)) / n, 1) if n else 0.0}
    return {"all": rates(rows), "pipeline": rates([r for r in rows if r["pipeline"]]),
            "india": rates([r for r in rows if r["country"] == "India"]),
            "malaysia": rates([r for r in rows if r["country"] == "Malaysia"])}


def projects_from_db() -> List[Dict[str, Any]]:
    from app.database import SessionLocal
    from app.phantom.models import PhProject
    from app.phantom.score import LAYERS
    db = SessionLocal()
    try:
        return [{"name": p.name, "developer": p.developer, "state": p.state, "country": p.country, "capacity_mw": p.capacity_mw,
                 "stage_name": LAYERS[p.stage or 0], "reality_score": p.reality_score} for p in db.query(PhProject).all()]
    finally:
        db.close()


def recall_section(rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    if rows is None:
        if not REFERENCE.exists():
            return ["", "## 5. Recall", "", "_No reference list yet (PHANTOM_RECALL_REFERENCE.csv)._"]
        rows = match(load_reference(), projects_from_db())
    s = summarise(rows)
    srcs = sorted({r["source"] for r in rows})
    line = lambda k, label: (f"| {label} | {s[k]['n']} | {s[k]['found']} | {s[k]['place_unknown']} | {s[k]['other_site']} | "  # noqa: E731
                             f"{s[k]['missing']} | **{s[k]['strict']}%** | {s[k]['lenient']}% |")
    miss = [r for r in rows if r["verdict"] in ("missing", "other_site") and r["pipeline"]]
    return [
        "", "## 5. Recall: how many real projects did the scouts miss?", "",
        f"An independent reference list of {len(rows)} India and Malaysia data-centre sites was built from published lists "
        f"({', '.join(srcs)}), extracted with Firecrawl and checked by hand: `PHANTOM_RECALL_REFERENCE.csv`. "
        "Each site is matched to our projects by developer (parent/JV brands grouped) and state.", "",
        "| Slice | Sites | Found | Found, no location | Developer tracked, other site | Missing | Recall (strict) | Recall (incl. no location) |",
        "|---|---|---|---|---|---|---|---|",
        line("all", "All"), line("pipeline", "**Pipeline** (announced / building / 2025+)"),
        line("india", "India"), line("malaysia", "Malaysia"), "",
        "**Missed pipeline sites** (what the next scouting round should chase):", "",
        *[f"- {r['developer']}: {r['project']} ({r['city']}) — {LABELS[r['verdict']]}" for r in miss], "",
        "Caveats: the reference list is small and biased towards big, well-reported operators, so recall on smaller "
        "projects is probably lower; a developer+state match can be a different building on the same campus.",
    ]


def main():
    rows = match(load_reference(), projects_from_db())
    for r in rows:
        print(f"{r['ref_id']} {LABELS[r['verdict']]:32} {r['developer'][:28]:28} {r['project'][:40]:40} -> {r['our_project'] or ''}")
    print(summarise(rows))


if __name__ == "__main__":
    main()
