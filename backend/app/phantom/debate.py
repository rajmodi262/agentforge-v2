"""Bull vs Bear: two agents argue whether a project will really be built.

Both agents see ONLY the project's verified evidence (numbered E1…En) and must
cite evidence ids for every point; a Judge then gives a verdict. Points whose
citations don't exist are discarded — the same "no source, no claim" rule as
the verifier. The debate does not change the reality score (that stays a
transparent model); it explains it and surfaces risks the numbers miss.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.phantom.llm import structured


class Point(BaseModel):
    claim: str = Field(..., description="One concise argument")
    cites: List[str] = Field(default_factory=list, description="Evidence ids that support it, e.g. ['E2']")


class Side(BaseModel):
    points: List[Point] = Field(default_factory=list)


class Verdict(BaseModel):
    verdict: str = Field(..., description="LIKELY BUILT, AT RISK, or LIKELY PHANTOM")
    reasoning: str = Field(..., description="Two or three sentences weighing both sides")
    watch_for: str = Field(..., description="The single next piece of evidence that would change your mind")


def evidence_brief(project: Dict[str, Any], evidence: List[Dict[str, Any]]) -> str:
    lines = [f"PROJECT: {project['name']} — developer {project.get('developer') or 'unknown'}, "
             f"{project.get('city') or project.get('country') or 'location unknown'}, "
             f"{project.get('capacity_mw') or '?'} MW ({project.get('capacity_basis') or 'basis unknown'}), "
             f"target {project.get('target_year') or 'not stated'}, power partner {project.get('power_partner') or 'none named'}.",
             f"Transparent reality score: {round((project.get('reality_score') or 0) * 100)}% (highest verified layer: {project.get('stage_name')}).",
             "VERIFIED EVIDENCE:"]
    for i, e in enumerate(evidence, 1):
        lines.append(f"E{i} [{e['layer']}] ({str(e.get('event_date') or '')[:10]}) \"{(e.get('quote') or '')[:300]}\"")
    return "\n".join(lines)


def _keep_cited(points: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    valid = {f"E{i}" for i in range(1, n + 1)}
    kept = []
    for p in points:
        cites = [c.strip().upper() for c in p.get("cites") or [] if isinstance(c, str)]
        cites = [c if c.startswith("E") else f"E{c}" for c in cites]
        ok = [c for c in cites if c in valid]
        if ok:
            kept.append({"claim": p.get("claim", "")[:400], "cites": ok})
    return kept


async def run_debate(project: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    brief = evidence_brief(project, evidence)
    n = len(evidence)
    bull_sys = ("You are the BULL analyst at a data-centre intelligence firm. Argue that this project WILL be built. "
                "Use only the evidence given; cite evidence ids (E1, E2…) for every point. 2–4 points.")
    bear_sys = ("You are the BEAR analyst at a data-centre intelligence firm. Argue that this project is AT RISK or a PHANTOM "
                "(announced but unlikely to be built). Use the evidence given AND the evidence that is missing — "
                "e.g. no power agreement, single source, passed deadlines. Cite evidence ids for points that rely on evidence. 2–4 points.")
    bull, m1 = await structured(bull_sys, brief, Side, max_tokens=700, tier="reason", agent="Bull")
    bear, m2 = await structured(bear_sys, brief + "\n\nThe BULL argued:\n" + "\n".join(f"- {p.get('claim')}" for p in bull.get("points", [])), Side, max_tokens=700, tier="reason", agent="Bear")
    bull_pts = _keep_cited(bull.get("points", []), n)
    # Bear may argue from *missing* evidence (no citation possible) — keep those, labelled as such
    bear_pts = _keep_cited(bear.get("points", []), n) + [
        {"claim": p.get("claim", "")[:400], "cites": [], "from_missing_evidence": True}
        for p in bear.get("points", []) if not p.get("cites") and re.search(r"\bno\b|missing|lack|absent|without|only one|single|unclear|not (?:yet|been)", p.get("claim", ""), re.I)
    ]
    judge_sys = ("You are the JUDGE. Weigh the Bull and Bear arguments against the evidence and give a verdict: "
                 "LIKELY BUILT, AT RISK, or LIKELY PHANTOM.")
    judge_in = (brief + "\n\nBULL:\n" + "\n".join(f"- {p['claim']} {p['cites']}" for p in bull_pts)
                + "\n\nBEAR:\n" + "\n".join(f"- {p['claim']} {p['cites'] or '(missing evidence)'}" for p in bear_pts))
    verdict, m3 = await structured(judge_sys, judge_in, Verdict, max_tokens=400, tier="reason", agent="Judge")
    v = str(verdict.get("verdict", "AT RISK")).upper()
    v = next((x for x in ("LIKELY BUILT", "LIKELY PHANTOM", "AT RISK") if x in v), "AT RISK")
    return {"bull": bull_pts, "bear": bear_pts, "verdict": v, "reasoning": verdict.get("reasoning", ""),
            "watch_for": verdict.get("watch_for", ""), "evidence_ids": [f"E{i}" for i in range(1, n + 1)],
            "tokens": m1["tokens"] + m2["tokens"] + m3["tokens"]}
