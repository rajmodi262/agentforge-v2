"""Backtest calibration — does a 75% reality score mean 75%?

Without outcome labels the layer priors were stated assumptions. This replays history:

1. Take every mention published on or before CUTOFF (30 Jun 2024) and resolve + score the
   projects exactly as the system would have then (`score.reality(..., now=CUTOFF)`).
2. Look at what the evidence says *after* the cutoff (news found by the regular hunt and by
   the Firecrawl outcome scout, `targeted.py outcomes`):
     progressed = verified BUILDING or LIVE evidence by now
     stalled    = cancelled / delayed, or no verified construction-or-later evidence 2+ years on
3. Compare predicted scores with what happened: reliability table + Brier score.

Honest limits: "no verified progress" is absence of evidence, not proof of failure, so the
observed build rate is a lower bound; the sample is small (projects old enough to judge).

    python -m app.phantom.backtest
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.phantom import score as S
from app.phantom.targeted import CUTOFF

PROGRESS = {"BUILDING", "LIVE"}
NEGATIVE = {"CANCELLED", "DELAYED"}


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def run(mentions: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.phantom.resolve import resolve
    if mentions is None:
        from app.database import SessionLocal
        from app.phantom.pipeline import _load_mentions
        db = SessionLocal()
        try:
            mentions = _load_mentions(db)
        finally:
            db.close()
    for m in mentions:
        m["published"] = _aware(m.get("published"))
    before = [m for m in mentions if m["published"] and m["published"] <= CUTOFF]
    then = resolve([dict(m) for m in before])
    now = resolve([dict(m) for m in mentions])
    owner = {mid: c for c in now for mid in c["mention_ids"]}
    rows = []
    for c in then:
        cur = next((owner[i] for i in c["mention_ids"] if i in owner), None)
        if cur is None:
            continue
        p_then, _ = S.reality(c, now=CUTOFF)
        stage_then = S.stage_of(c["events"])
        later = [e for e in cur["events"] if _aware(e.get("published")) and _aware(e["published"]) > CUTOFF]
        layers_later = {e["layer"] for e in later}
        stage_now = S.stage_of(cur["events"])
        progressed = bool(layers_later & PROGRESS) or (stage_then >= 4 and stage_now >= 4)
        if layers_later & {"CANCELLED"}:
            progressed = False
        rows.append({"name": c["name"], "developer": c["developer"], "country": c["country"], "reality_score": round(p_then, 3),
                     "stage_then": S.LAYERS[stage_then], "stage_now": S.LAYERS[stage_now], "progressed": progressed,
                     "news_after_cutoff": len({e["article_id"] for e in later}),
                     "negative_after": sorted(layers_later & NEGATIVE)})
    rows = [r for r in rows if r["country"] in ("India", "Malaysia")]
    outcomes = {r["name"]: r["progressed"] for r in rows}
    early = [r for r in rows if r["stage_then"] not in ("BUILDING", "LIVE")]
    return {"cutoff": CUTOFF.date().isoformat(), "rows": rows,
            "all": S.calibrate(rows, outcomes),
            "pre_construction": S.calibrate(early, {r["name"]: r["progressed"] for r in early}),
            "with_news_after": sum(1 for r in rows if r["news_after_cutoff"])}


def section(res: Dict[str, Any] = None) -> List[str]:
    res = res or run()
    a, e = res["all"], res["pre_construction"]
    if not a.get("n"):
        return ["", "## 6. Calibration backtest", "", "_Not enough projects older than the cutoff yet._"]

    def table(r):
        return ["| Predicted score bucket | Projects | Mean predicted | Observed progressed |", "|---|---|---|---|",
                *[f"| {t['bucket']} | {t['n']} | {t['predicted']:.0%} | {t['observed']:.0%} |" for t in r["table"]]]
    base_rate = sum(r["progressed"] for r in res["rows"]) / len(res["rows"])
    return [
        "", "## 6. Calibration backtest: does the score mean what it says?", "",
        f"Every project first seen by **{res['cutoff']}** was re-scored using only the evidence published up to that date, "
        "then compared with what verified evidence shows since (regular hunt + Firecrawl outcome scout). "
        "*Progressed* = verified BUILDING or LIVE evidence; otherwise counted as not progressed.", "",
        f"**All {a['n']} projects** — Brier score **{a['brier']}** (lower is better; always guessing the base rate of "
        f"{base_rate:.0%} would score {round(base_rate * (1 - base_rate), 4)}). {res['with_news_after']} had news after the cutoff.", "",
        *table(a), "",
        f"**The real test — {e.get('n', 0)} projects not yet under construction at the cutoff** — Brier {e.get('brier', '—')}:", "",
        *(table(e) if e.get("n") else ["_none_"]), "",
        "Limits: small sample; *not progressed* includes projects that may be progressing without coverage, so observed rates are a lower bound. "
        "With more history this table is how the layer priors would be re-fitted.",
    ]


def main():
    res = run()
    for r in sorted(res["rows"], key=lambda r: -r["reality_score"]):
        print(f"{r['reality_score']:.2f} {r['stage_then']:9} -> {r['stage_now']:9} {'✓' if r['progressed'] else '·'} news={r['news_after_cutoff']:2} {r['name'][:60]}")
    print({k: v for k, v in res.items() if k != "rows"})


if __name__ == "__main__":
    main()
