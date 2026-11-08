"""Phantom Hunter evaluation → PHANTOM_EVAL.md

usage: python -m app.phantom.evaluate

1. Funnel: articles → relevant → read → mentions → verified claims → projects.
2. Verifier planted-error test: take real, verified mentions and corrupt one field
   at a time the way an LLM hallucinates (inflate capacity, shift a year, swap the
   developer, invent a quote, mislabel a stage). Catch rate per error type, plus
   the false-rejection rate on the untouched originals.
3. Extraction audit sample: 40 random verified evidence items exported to CSV for
   human review (precision of what survives verification).
4. Score distribution and the announced-vs-real headline.
"""

from __future__ import annotations

import copy
import csv
import random
import re
from collections import Counter
from pathlib import Path

from app.database import SessionLocal
from app.phantom.extract import KNOWN_DEVELOPERS, MAX_CHARS
from app.phantom.models import PhArticle, PhEvidence, PhMention, PhProject
from app.phantom.score import LAYERS
from app.phantom.verify import LAYER_WORDS, norm, verify_mention

ROOT = Path(__file__).resolve().parents[3]
random.seed(7)

FAKE_QUOTES = [
    "The company has signed a 500MW power purchase agreement with the state utility for the campus.",
    "The facility was fully commissioned last month and is now serving hyperscale customers.",
    "Construction of the campus began in January after the foundation stone was laid.",
]


def _mentions_with_articles(db):
    rows = db.query(PhMention, PhArticle).join(PhArticle, PhMention.article_id == PhArticle.id).all()
    return [(m, a) for m, a in rows if a.text]


def planted_errors(db) -> dict:
    results = {k: [0, 0] for k in ("capacity", "target_year", "developer", "fabricated_quote", "wrong_layer")}
    originals = [0, 0]
    for m, a in _mentions_with_articles(db):
        body = a.text[:MAX_CHARS]
        d = copy.deepcopy(m.data)
        d["events"] = [e for e in d.get("events") or [] if e.get("source") != "miner"]
        # originals must stay verified (false rejection check)
        _, v, _ = verify_mention(d, body)
        for f in ("developer", "capacity_mw", "target_year"):
            if d.get(f) not in (None, "") and f in v:
                originals[1] += 1
                originals[0] += int(v[f]["ok"])
        t = norm(body)

        def trial(kind, mutated, field_ok):
            _, vv, _ = verify_mention(mutated, body)
            results[kind][1] += 1
            results[kind][0] += int(not field_ok(vv))

        if d.get("capacity_mw"):
            bad = float(d["capacity_mw"]) * 1.5 + 7
            if f"{bad:g}" not in t:
                trial("capacity", {**d, "capacity_mw": bad, "capacity_text": f"{bad:g}MW"}, lambda vv: vv["capacity_mw"]["ok"])
        if d.get("target_year"):
            y = int(d["target_year"]) + 3
            if str(y) not in t:
                trial("target_year", {**d, "target_year": y}, lambda vv: vv["target_year"]["ok"])
        if d.get("developer"):
            absent = [c for c, al in KNOWN_DEVELOPERS.items() if not any(re.search(rf"\b{re.escape(x)}\b", t) for x in al)]
            if absent:
                trial("developer", {**d, "developer": random.choice(absent)}, lambda vv: vv["developer"]["ok"])
        q = random.choice(FAKE_QUOTES)
        if norm(q) not in t:
            layer = {"500MW": "POWER", "commissioned": "LIVE", "Construction": "BUILDING"}
            lay = next(v for k, v in layer.items() if k in q)
            trial("fabricated_quote", {**d, "events": [{"layer": lay, "detail": "x", "quote": q}]}, lambda vv: vv["events"][0]["ok"])
        for e in d.get("events") or []:
            wrong = next((L for L in ("LIVE", "POWER", "CANCELLED") if not re.search(LAYER_WORDS[L], norm(e.get("quote", "")))), None)
            if wrong:
                trial("wrong_layer", {**d, "events": [{**e, "layer": wrong}]}, lambda vv: vv["events"][0]["ok"])
                break
    caught = sum(c for c, _ in results.values())
    total = sum(n for _, n in results.values())
    return {"by_type": {k: {"caught": c, "planted": n, "rate": round(100 * c / n, 1) if n else None} for k, (c, n) in results.items()},
            "overall": {"caught": caught, "planted": total, "rate": round(100 * caught / total, 1) if total else None},
            "originals_kept": {"kept": originals[0], "checked": originals[1],
                               "rate": round(100 * originals[0] / originals[1], 1) if originals[1] else None}}


def claim_tally(verifications) -> tuple:
    """(verified, checked) over every individual claim — fields and events alike. Used by the
    eval report AND the dashboard so both always quote the same number."""
    total = ok = 0
    for ver in verifications:
        for k, v in (ver or {}).items():
            if k in ("events", "mined", "country", "project_name"):
                continue
            if isinstance(v, dict):
                total += 1
                ok += int(v.get("ok", False))
        for e in (ver or {}).get("events", []):
            total += 1
            ok += int(e.get("ok", False))
    return ok, total


def funnel(db) -> dict:
    kinds = Counter(k for (k,) in db.query(PhArticle.text_kind).all())
    mentions = db.query(PhMention).all()
    claims_ok, claims_total = claim_tally(m.verification for m in mentions)
    projects = db.query(PhProject).all()
    return {
        "articles": sum(kinds.values()), "full_text": kinds.get("full", 0), "headline_only": kinds.get("summary", 0),
        "relevant": db.query(PhArticle).filter(PhArticle.relevant == True).count(),  # noqa: E712
        "read": db.query(PhArticle).filter(PhArticle.extracted == True).count(),  # noqa: E712
        "mentions": len(mentions), "claims": claims_total, "claims_verified": claims_ok,
        "projects": len(projects),
        "announced_mw": round(sum(p.capacity_mw or 0 for p in projects)),
        "reality_mw": round(sum((p.capacity_mw or 0) * (p.reality_score or 0) for p in projects)),
        "stages": Counter(LAYERS[p.stage or 0] for p in projects),
        "score_bands": Counter(("≥70% likely" if (p.reality_score or 0) >= 0.7 else "45–70% at risk" if (p.reality_score or 0) >= 0.45 else "<45% phantom risk") for p in projects),
        "evidence_sources": Counter("miner" if (e.detail or "").endswith("(stage language in the article)") else "llm" for e in db.query(PhEvidence).all()),
    }


def audit_sample(db, n: int = 40, seed: int = 7, name: str = "PHANTOM_AUDIT_SAMPLE.csv", exclude: Path | None = None) -> Path:
    ev = db.query(PhEvidence, PhProject, PhArticle).join(PhProject, PhEvidence.project_id == PhProject.id) \
        .join(PhArticle, PhEvidence.article_id == PhArticle.id).all()
    if exclude and exclude.exists():  # a fresh sample must not reuse items the rules were tuned on
        seen = {r["quote"] for r in csv.DictReader(open(exclude, encoding="utf-8"))}
        ev = [x for x in ev if x[0].quote not in seen]
    sample = random.Random(seed).sample(ev, min(n, len(ev)))
    path = ROOT / name
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["project", "layer", "quote", "source", "url", "layer_correct (y/n)", "quote_is_about_this_project (y/n)", "notes"])
        for e, p, a in sample:
            w.writerow([p.name, e.layer, e.quote, a.source, a.url, "", "", ""])
    return path


def audit_section() -> list:
    import json
    f = ROOT / "phantom_audit_results.json"
    head = ["## 3. Audit of verified evidence (precision)", "",
            "The verifier proves a quote *exists* and *fits its stage*; it cannot prove the stage label is the best one or that "
            "the quote is about *this* project. So random verified evidence items were reviewed by hand: is the stage right, "
            "and is the quote about this project?", ""]
    if not f.exists():
        return head + ["_Not audited yet._"]
    a = json.loads(f.read_text(encoding="utf-8"))
    r1, r2 = a["round1_before_fixes"], a["round2_fresh_after_fixes"]
    pct = lambda r: f"{round(100 * r['correct'] / r['n'], 1)}%"  # noqa: E731
    return head + [
        "| | Round 1 (before fixes) | Round 2 (fresh sample, after fixes) |", "|---|---|---|",
        f"| Fully correct | {r1['correct']}/{r1['n']} ({pct(r1)}) | **{r2['correct']}/{r2['n']} ({pct(r2)})** |",
        f"| Stage too low (conservative) | {r1['under']} | {r2['under']} |",
        f"| Stage too high (dangerous) | {r1['over']} | {r2['over']} |",
        f"| Not real evidence / wrong project | {r1['other']} | {r2['other']} |", "",
        "Round 1 drove four rule fixes (network \"interconnected\" ≠ power; future tense never proves LIVE; upgrade an "
        "under-labelled event when its own quote states a higher stage; \"TM Nxera\" = Telekom Malaysia). Round 2 is a "
        "**fresh sample** that excluded every round-1 item, so its number is not inflated by tuning. Its findings "
        "(\"seeks a loan\", \"will acquire land\", \"secured 264 acres\", \"solar deal with TNB\") were then fixed and "
        "turned into regression tests. Most remaining errors are *conservative* — the system under-states a project's "
        "stage more often than it over-states it, the safe direction for a sales tool.", "",
        "Labels are a first pass by an AI assistant (Claude) and should be confirmed by the team: "
        "`PHANTOM_AUDIT_SAMPLE_round1.csv`, `PHANTOM_AUDIT_SAMPLE_round2.csv`. "
        "The weakness still visible: a real quote about a *different* project in the same article (1–2 per 40)."]


def coverage_section() -> list:
    import json
    f = ROOT / "phantom_coverage.json"
    if not f.exists():
        return ["", "## 4. Coverage-agent ablation", "", "_Not run yet — `python -m app.phantom.run_coverage`._"]
    c = json.loads(f.read_text(encoding="utf-8"))
    q = sum(len(v) for v in c["queries"].values())
    return ["", "## 4. Coverage-agent ablation — what the agentic loop adds", "",
            "After the fixed seed queries, the Coverage agent read the results and wrote its own follow-up searches "
            "(single-source projects, missing capacity or stage evidence, developers never seen).", "",
            "| | Value |", "|---|---|",
            f"| Follow-up queries written by the agent | {q} |",
            f"| New articles read | {c['new_articles_read']} |",
            f"| Projects before → after | {c['projects_before']} → {c['projects_after']} |",
            f"| Net new projects | +{c['projects_after'] - c['projects_before']} |",
            f"| Existing projects that gained sources | {len(c['more_sources'])} |",
            f"| Projects moved up the evidence ladder | {len(c['stage_upgrades'])} |", "",
            "Examples of queries it wrote: " + "; ".join(f"`{x}`" for x in list(dict.fromkeys(q for v in c["queries"].values() for q in v))[:6])]


def main():
    db = SessionLocal()
    try:
        fn, pe = funnel(db), planted_errors(db)
        audit = None  # audit samples are drawn deliberately (round 1 / round 2), not on every run
    finally:
        db.close()
    o = pe["overall"]
    lines = [
        "# Phantom Hunter — Evaluation", "",
        "Generated by `python -m app.phantom.evaluate`. Every number below is computed from the stored data.", "",
        "## 1. Funnel", "",
        "| Stage | Count |", "|---|---|",
        f"| Articles collected | {fn['articles']} ({fn['full_text']} full text, {fn['headline_only']} headline-only) |",
        f"| Relevant (data centre + hard detail) | {fn['relevant']} |",
        f"| Read by the Extractor | {fn['read']} |",
        f"| Project mentions extracted | {fn['mentions']} |",
        f"| Claims checked by the Verifier | {fn['claims']} |",
        f"| Claims that survived verification | {fn['claims_verified']} ({round(100 * fn['claims_verified'] / fn['claims'], 1) if fn['claims'] else '—'}%) |",
        f"| Resolved projects (India + Malaysia) | {fn['projects']} |",
        f"| Announced capacity (projects with a stated MW) | {fn['announced_mw']:,} MW |",
        f"| Reality-weighted capacity | {fn['reality_mw']:,} MW ({round(100 * fn['reality_mw'] / fn['announced_mw']) if fn['announced_mw'] else 0}% of announced) |",
        "", "Projects by highest verified evidence layer: " + ", ".join(f"{k} {v}" for k, v in fn["stages"].most_common()),
        "", "Reality-score bands: " + ", ".join(f"{k}: {v}" for k, v in fn["score_bands"].most_common()),
        "", "Evidence items by origin: " + ", ".join(f"{k}: {v}" for k, v in fn["evidence_sources"].items()),
        "", "## 2. Verifier planted-error test", "",
        "Real verified mentions were corrupted one field at a time, the way LLMs hallucinate, and re-verified against their article.", "",
        "| Planted error | Planted | Caught | Catch rate |", "|---|---|---|---|",
        *[f"| {k.replace('_', ' ')} | {v['planted']} | {v['caught']} | {v['rate']}% |" for k, v in pe["by_type"].items() if v["planted"]],
        f"| **All** | **{o['planted']}** | **{o['caught']}** | **{o['rate']}%** |", "",
        f"False rejections: of {pe['originals_kept']['checked']} untouched verified fields, {pe['originals_kept']['kept']} stayed verified ({pe['originals_kept']['rate']}%).", "",
        "What the verifier can NOT catch: a quote that is real and fits its layer but is about a *different* project in the same article. "
        "The audit sample below measures that.", "",
        *audit_section(),
        *coverage_section(),
        "", "## 5. What is not measured yet (and how it would be)", "",
        "- **Calibration of the reality score.** It needs outcomes (built vs cancelled) for scored projects. `score.calibrate()` computes the reliability table and Brier score once those labels exist; until then the layer priors are stated assumptions, not fitted values.",
        "- **Recall** (projects the scouts never found). Measurable against an analyst's list for one region.",
    ]
    out = ROOT / "PHANTOM_EVAL.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
