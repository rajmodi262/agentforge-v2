"""Ask the Tracker: questions answered from the project database, with citations.

Retrieval is deliberately simple and inspectable: the question is matched
against projects (name, developer, place, country) and their verified evidence
by keyword overlap, the top projects' facts are packed into the prompt as
numbered sources [S1]…[Sn], and the answer must cite them. Sources the model
cites that don't exist are stripped; the UI links each [S#] to its article.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.database import SessionLocal
from app.phantom.llm import structured
from app.phantom.models import PhArticle, PhEvidence, PhProject

_STOP = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "is", "are", "which", "what", "how", "many", "most", "data",
         "centre", "center", "centres", "centers", "project", "projects", "likely", "be", "will", "real", "me", "show", "list", "give"}


class Answer(BaseModel):
    answer: str = Field(..., description="Direct answer in 2-5 sentences, citing sources like [S1]")
    cited: List[str] = Field(default_factory=list, description="Source ids used, e.g. ['S1','S3']")


def _terms(q: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in _STOP and len(w) > 1]


def retrieve(question: str, k: int = 8) -> List[Dict[str, Any]]:
    terms = _terms(question)
    db = SessionLocal()
    try:
        rows = db.query(PhProject).all()
        scored = []
        for p in rows:
            hay = " ".join(str(x or "") for x in (p.name, p.developer, p.city, p.state, p.country, p.power_partner, p.cooling)).lower()
            s = sum(2 for t in terms if t in hay)
            if any(t in ("phantom", "risk", "risky", "unlikely") for t in terms):
                s += 1 - (p.reality_score or 0)
            if any(t in ("call", "sell", "opportunity", "supplier") for t in terms):
                s += max((c or {}).get("priority", 0) for c in (p.call_segments or {}).values()) / 100 if p.call_segments else 0
            scored.append((s + (p.reality_score or 0) * 0.01, p))
        scored.sort(key=lambda x: -x[0])
        out = []
        for _, p in scored[:k]:
            ev = db.query(PhEvidence).filter(PhEvidence.project_id == p.id, PhEvidence.verified == True).all()  # noqa: E712
            art = {a.id: a for a in db.query(PhArticle).filter(PhArticle.id.in_([e.article_id for e in ev])).all()} if ev else {}
            first = ev[0] if ev else None
            out.append({
                "project_id": str(p.id), "name": p.name, "developer": p.developer, "place": p.city or p.state or p.country,
                "mw": p.capacity_mw, "score": p.reality_score, "stage": p.stage, "weakest": p.weakest_assumption,
                "evidence": [f"[{e.layer}] {e.quote[:200]}" for e in ev[:3]],
                "url": art[first.article_id].url if first and first.article_id in art else None,
                "title": art[first.article_id].title if first and first.article_id in art else None,
            })
        return out
    finally:
        db.close()


async def ask(question: str) -> Dict[str, Any]:
    ctx = retrieve(question)
    if not ctx:
        return {"answer": "The tracker has no projects yet — run a hunt first.", "sources": []}
    lines = []
    for i, c in enumerate(ctx, 1):
        lines.append(f"[S{i}] {c['name']} | developer {c['developer']} | {c['place']} | {c['mw'] or '?'} MW | "
                     f"reality {round((c['score'] or 0) * 100)}% | weakest assumption: {c['weakest']} | evidence: {' / '.join(c['evidence']) or 'none'}")
    sys = ("You answer questions about a database of data-centre projects for energy and infrastructure suppliers. "
           "Use ONLY the sources given. Cite every fact with its source id like [S2]. "
           "If the sources don't answer the question, say so plainly.")
    raw, meta = await structured(sys, f"QUESTION: {question}\n\nSOURCES:\n" + "\n".join(lines), Answer, max_tokens=500, tier="reason", agent="Ask the Tracker")
    valid = {f"S{i}" for i in range(1, len(ctx) + 1)}
    used = sorted({c for c in re.findall(r"\[(S\d+)\]", raw.get("answer", "")) if c in valid} | {c for c in raw.get("cited", []) if c in valid},
                  key=lambda s: int(s[1:]))
    answer = re.sub(r"\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", raw.get("answer", ""))
    return {"answer": answer.strip(), "sources": [{"id": s, **ctx[int(s[1:]) - 1]} for s in used], "tokens": meta["tokens"]}
