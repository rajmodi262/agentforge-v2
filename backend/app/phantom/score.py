"""Scorer: evidence ladder → reality score, weakest assumption, anomalies, who-to-call.

THE REALITY SCORE IS A TRANSPARENT LOG-ODDS MODEL, NOT A BLACK BOX.

    logit(p) = logit(prior[highest verified layer]) + Σ adjustments

Priors (probability a project at that layer is eventually built) are explicit
ASSUMPTIONS, anchored to public market evidence, and meant to be replaced by
calibrated values once outcome data exists (see `calibrate()`):

    layer        prior  anchor
    ANNOUNCED    0.25   Bernstein: only ~35% of the US pipeline looks credible;
                        withdrawals sit mostly in the announcement layer (SemiAnalysis)
    SITE         0.40   land is a real cost, but plenty of land-banked sites stall
    APPROVED     0.50   permits remove a hurdle, not the power constraint
    POWER        0.75   Capgemini 2026: ~1 in 5 interconnection requests never
                        materialise → ~80% for projects with a grid position
    BUILDING     0.88   construction stops are rare but real (Sightline: delays > cancels)
    LIVE         0.98   at least a first phase is operating

Every adjustment is recorded in `breakdown`, so the UI shows exactly why a
project scored what it did — and the "weakest assumption" is the single
missing piece of evidence whose presence would raise the score the most.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

LAYERS = ["ANNOUNCED", "SITE", "APPROVED", "POWER", "BUILDING", "LIVE"]
PRIOR = {0: 0.25, 1: 0.40, 2: 0.50, 3: 0.75, 4: 0.88, 5: 0.98}
NEG = {"CANCELLED": None, "DELAYED": -0.6, "OPPOSITION": -0.5, "SCALED_DOWN": -0.3}

logit = lambda p: math.log(p / (1 - p))  # noqa: E731
sigmoid = lambda x: 1 / (1 + math.exp(-x))  # noqa: E731


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def stage_of(events: List[Dict[str, Any]]) -> int:
    idx = [LAYERS.index(e["layer"]) for e in events if e.get("layer") in LAYERS]
    return max(idx) if idx else 0


def reality(p: Dict[str, Any], now: Optional[datetime] = None) -> Tuple[float, List[Dict[str, Any]]]:
    """Return (probability, breakdown). `p` is a resolved project (resolve.canonicalise output)."""
    now = now or _now()
    events = p.get("events") or []
    layers = {e["layer"] for e in events}
    stage = stage_of(events)
    br: List[Dict[str, Any]] = [{"term": f"Evidence layer: {LAYERS[stage]}", "delta": None, "value": PRIOR[stage],
                                 "why": f"prior for a project whose highest verified evidence is {LAYERS[stage]}"}]
    if "CANCELLED" in layers:
        br.append({"term": "Cancelled", "delta": None, "value": 0.03, "why": "a verified source reports the project cancelled or withdrawn"})
        return 0.03, br
    x = logit(PRIOR[stage])

    def add(term: str, delta: float, why: str):
        nonlocal x
        x += delta
        br.append({"term": term, "delta": round(delta, 2), "why": why})

    n_src = len(p.get("article_ids") or [])
    if n_src <= 1:
        add("Single source", -0.3, "only one article reports this project")
    elif n_src >= 3:
        add(f"{n_src} independent sources", +0.3, "corroborated by three or more articles")

    kinds = p.get("text_kinds") or []
    if kinds and all(k == "summary" for k in kinds):
        add("Headline-only evidence", -0.2, "publishers blocked full text; evidence comes from headlines and summaries")

    if "FINANCED" in layers and stage < 5:
        add("Financing secured", +0.4, "a verified source reports a loan / debt facility / capital raise for the project")

    if stage < 3 and p.get("power_partner"):
        add(f"Named power partner ({p['power_partner']})", +0.4, "a utility or supplier is named, short of a verified agreement")

    for neg, d in NEG.items():
        if neg in layers and d is not None:
            add(neg.replace("_", " ").title(), d, f"a verified source reports {neg.lower().replace('_', ' ')}")

    last = _aware(p.get("last_seen"))
    if stage < 5 and last and (now - last).days > 540:
        add("Gone quiet", -0.5, f"no news for {(now - last).days // 30} months")

    ty = p.get("target_year")
    if stage < 5 and ty and ty < now.year:
        add("Target date passed", -0.5, f"was due in {ty} and no evidence it is live")

    return round(sigmoid(x), 3), br


def weakest_assumption(p: Dict[str, Any]) -> Dict[str, Any]:
    """The single missing piece of evidence that matters most right now (counterfactual).

    Candidates are limited to what an analyst would chase next — the next rung of
    the ladder, secured power (the binding constraint for data centres), a second
    source, and full-text access — and the one with the biggest score uplift wins.
    Jumping straight to "not live yet" would be true but useless.
    """
    base, _ = reality(p)
    stage = stage_of(p.get("events") or [])
    candidates = []
    next_layer = LAYERS[stage + 1] if stage < 5 else None

    def try_fix(label: str, mutate):
        q = {**p, "events": list(p.get("events") or []), "article_ids": list(p.get("article_ids") or []), "text_kinds": list(p.get("text_kinds") or [])}
        mutate(q)
        s, _ = reality(q)
        candidates.append({"assumption": label, "uplift": round(s - base, 3)})

    labels = {
        "SITE": "No verified evidence that land or a site has been secured",
        "APPROVED": "No verified evidence of permits or government approval",
        "POWER": "No verified evidence that power is secured (PPA, grid connection or substation)",
        "BUILDING": "No verified evidence that construction has started",
        "LIVE": "No verified evidence that any phase is operational yet",
    }
    if stage < 3:
        try_fix(labels["POWER"], lambda q: q["events"].append({"layer": "POWER"}))
    if next_layer and next_layer != "POWER":
        try_fix(labels[next_layer], lambda q: q["events"].append({"layer": next_layer}))
    if len(p.get("article_ids") or []) <= 1:
        try_fix("Only one source reports this project — it is uncorroborated",
                lambda q: q["article_ids"].extend(["x", "y"]))
    kinds = p.get("text_kinds") or []
    if kinds and all(k == "summary" for k in kinds):
        try_fix("Evidence comes only from headlines (full articles were not accessible)",
                lambda q: q.__setitem__("text_kinds", ["full"]))
    if not candidates:
        return {"assumption": "Project is live — remaining risk is in later phases, not the first", "uplift": 0.0}
    return max(candidates, key=lambda c: c["uplift"])


# ───────────────────────────── Anomaly Watch ─────────────────────────────

def anomalies(p: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now()
    out = []
    caps = [c for c in p.get("capacities") or [] if c.get("mw")]
    same_basis = {}
    for c in caps:
        same_basis.setdefault(c.get("basis") or "unknown", []).append(c)
    for basis, cs in same_basis.items():
        lo, hi = min(c["mw"] for c in cs), max(c["mw"] for c in cs)
        if lo and hi / lo > 1.35:
            first, last = sorted(cs, key=lambda c: (_aware(c["published"]) or now))[0], sorted(cs, key=lambda c: (_aware(c["published"]) or now))[-1]
            direction = "cut" if last["mw"] < first["mw"] else "raised"
            out.append({"kind": "capacity_conflict", "severity": "high" if direction == "cut" else "medium",
                        "message": f"Capacity {direction}: sources report {lo:g}–{hi:g} MW ({basis} basis)",
                        "details": {"values": [{"mw": c["mw"], "published": str(c["published"])} for c in cs]}})
    years = sorted([(_aware(d) or now, y) for d, y in p.get("target_years") or []])
    if len(years) >= 2 and years[-1][1] > years[0][1]:
        out.append({"kind": "date_slip", "severity": "high",
                    "message": f"Target date slipped from {years[0][1]} to {years[-1][1]}",
                    "details": {"years": [y for _, y in years]}})
    for e in p.get("events") or []:
        if e.get("layer") in NEG:
            out.append({"kind": "negative_signal", "severity": "high",
                        "message": f"{e['layer'].replace('_', ' ').title()}: {e.get('detail') or ''}".strip(),
                        "details": {"quote": e.get("quote"), "article_id": str(e.get("article_id"))}})
    stage = stage_of(p.get("events") or [])
    last = _aware(p.get("last_seen"))
    if stage < 5 and last and (now - last).days > 365:
        out.append({"kind": "stale", "severity": "low", "message": f"No news for {(now - last).days // 30} months", "details": {}})
    ty = p.get("target_year")
    if stage < 5 and ty and ty < now.year:
        out.append({"kind": "target_passed", "severity": "medium", "message": f"Target year {ty} has passed with no evidence it is live", "details": {}})
    return out


# ───────────────────────────── Who to call ─────────────────────────────

SEGMENTS = {
    "power": "Power & IPPs",
    "electrical": "Electrical equipment (transformers, switchgear, UPS)",
    "cooling": "Cooling & thermal",
}


def _timing(p: Dict[str, Any], now: datetime) -> Tuple[float, str]:
    ty = p.get("target_year")
    if not ty:
        return 0.6, "no target date published"
    gap = ty - now.year
    if gap < 0:
        return 0.2, f"target {ty} already passed"
    if gap == 0:
        return 0.5, f"due {ty} — most suppliers already chosen"
    if gap <= 2:
        return 1.0, f"due {ty} — inside the 12–24 month window where specs are set"
    return 0.7, f"due {ty} — early, good time to shape the design"


def who_to_call(p: Dict[str, Any], score: float, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Priority 0–100 per buyer segment, with the reasons a salesperson would want."""
    now = now or _now()
    stage = stage_of(p.get("events") or [])
    mw = p.get("capacity_mw") or 0
    size = min(1.0, math.log1p(mw) / math.log1p(500)) if mw else 0.4
    timing, why_t = _timing(p, now)
    out = {}

    def seg(key, open_factor, reasons):
        pr = round(100 * score * timing * size * open_factor)
        out[key] = {"segment": SEGMENTS[key], "priority": pr, "reasons": reasons + [why_t]}

    if not p.get("power_partner") and stage <= 3:
        seg("power", 1.0, ["no energy partner named yet", f"at {LAYERS[stage]} stage"])
    elif p.get("power_partner"):
        seg("power", 0.2, [f"power partner already named: {p['power_partner']}"])
    if 1 <= stage <= 3:
        seg("electrical", 1.0, ["pre-construction — electrical specs are set 12–18 months before ground-break"])
    elif stage == 0:
        seg("electrical", 0.5, ["still at announcement — design not started"])
    else:
        seg("electrical", 0.3, [f"already {LAYERS[stage]} — main package likely awarded"])
    dense = p.get("ai_density")
    if not p.get("cooling") and stage <= 4:
        seg("cooling", 1.0 if dense else 0.6, (["built for AI / high-density racks"] if dense else []) + ["cooling approach not disclosed"])
    else:
        seg("cooling", 0.3, [f"cooling already disclosed: {p.get('cooling')}"] if p.get("cooling") else ["live"])
    return out


def calibrate(projects: List[Dict[str, Any]], outcomes: Dict[str, bool]) -> Dict[str, Any]:
    """Reliability check once outcomes exist: bucket predicted scores, compare to realised build rates.

    `outcomes` maps project name → True (built / live) / False (cancelled). Returns per-bucket
    predicted vs observed rates and the Brier score — the test of whether "0.8 means 80%".
    """
    pairs = [(p["reality_score"], outcomes[p["name"]]) for p in projects if p["name"] in outcomes]
    if not pairs:
        return {"n": 0}
    buckets = {}
    for s, y in pairs:
        b = min(4, int(s * 5))
        buckets.setdefault(b, []).append((s, y))
    table = [{"bucket": f"{b * 20}-{b * 20 + 20}%", "n": len(v), "predicted": round(sum(s for s, _ in v) / len(v), 3),
              "observed": round(sum(y for _, y in v) / len(v), 3)} for b, v in sorted(buckets.items())]
    brier = sum((s - y) ** 2 for s, y in pairs) / len(pairs)
    return {"n": len(pairs), "brier": round(brier, 4), "table": table}
