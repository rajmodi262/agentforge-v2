"""The hunt: a LangGraph state machine over the Phantom Hunter agents.

    plan ─► scout ─► extract ─► resolve+score ─► coverage ─┬─► scout (next round)
                                                           └─► finish

The loop is what makes the Scout an agent rather than a fixed script: after
each round the Coverage agent inspects what was found — projects backed by a
single source, projects missing capacity or stage evidence, known developers
not yet seen — and writes the next round's search queries itself. It stops
when there's nothing worth chasing or the round budget is spent.

`rebuild_projects()` is the deterministic half (resolve → score → anomalies →
who-to-call → save); it can be re-run at any time from stored mentions.
"""

from __future__ import annotations

import asyncio
import uuid
import logging
import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.database import SessionLocal
from app.phantom import score as S
from app.phantom.extract import MAX_CHARS, extract_article, gazetteer_developer, mine_evidence, project_sentences, upgrade_events
from app.phantom.geo import coords, infer_country, resolve_place
from app.phantom.models import PhAnomaly, PhArticle, PhEvidence, PhMention, PhProject, PhRun
from app.phantom.resolve import resolve
from app.phantom.verify import event_fits, norm, quote_found
from app.phantom.sources import REGIONS, fetch_all, search, seed_queries
from app.phantom.store import pending_articles, save_articles, save_mentions
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


# ───────────────────────── deterministic rebuild ─────────────────────────

def _load_mentions(db) -> List[Dict[str, Any]]:
    rows = db.query(PhMention, PhArticle).join(PhArticle, PhMention.article_id == PhArticle.id).all()
    out = []
    for m, a in rows:
        d = dict(m.data or {})
        # Re-mine evidence from the stored article on every rebuild: the miner is deterministic,
        # so improving it upgrades all historical data without another LLM call.
        body = (a.text or "")[:MAX_CHARS]
        if not body and d.get("_frozen"):
            # Seeded snapshot (app/phantom/seed.py): article bodies are not redistributed, so there is
            # nothing to re-check against — use the events as they were verified when exported.
            out.append({"id": m.id, "data": d, "published": a.published_at, "article_id": a.id, "text_kind": a.text_kind})
            continue
        # Re-verify stored LLM events with today's rules (stricter rules apply retroactively)
        tn = norm(body)
        llm_events = [e for e in d.get("events") or [] if e.get("source") != "miner"
                      and quote_found(e.get("quote"), tn)[0] and event_fits(e.get("layer"), e.get("quote", ""))]
        if not d.get("developer"):
            dev = gazetteer_developer(f"{a.title}. {body}", d.get("project_name"))
            if dev:
                d["developer"], d["_developer_from"] = dev, "gazetteer"
        llm_events = llm_events + upgrade_events(llm_events)
        d["events"] = llm_events + mine_evidence({**d, "events": llm_events}, body)
        d["context"] = project_sentences(d, body)[:3]
        # the mention's own place first, then the article as a whole
        inferred = infer_country(d.get("city"), d.get("state"), d.get("project_name"), *(d.get("context") or [])) \
            or infer_country(a.title, (a.text or "")[:3000])
        if inferred:
            d["country"] = inferred  # trust evidence over the model's guess (it said "Indonesia" for Jakarta correctly too)
        elif d.get("country") not in {r["country"] for r in REGIONS.values()}:
            d["country"] = d.get("country")  # out of scope — dropped later
        out.append({"id": m.id, "data": d, "published": a.published_at, "article_id": a.id, "text_kind": a.text_kind})
    return out


def rebuild_projects() -> Dict[str, Any]:
    """Resolve all stored mentions into projects and (re)score them. Idempotent."""
    db = SessionLocal()
    try:
        mentions = _load_mentions(db)
        clusters = resolve(mentions)
        old_debates = {p.name: p.debate for p in db.query(PhProject).filter(PhProject.debate != None).all()}  # noqa: E711
        db.query(PhAnomaly).delete(); db.query(PhEvidence).delete()
        db.query(PhMention).update({PhMention.project_id: None})
        db.query(PhProject).delete()
        db.flush()
        now = datetime.now(timezone.utc)
        n_anom = 0
        in_scope = {r["country"] for r in REGIONS.values()}
        from app.phantom.geo import PLACES
        for c in clusters:  # a known place settles the country
            if c["place"] in PLACES:
                c["country"] = PLACES[c["place"]][1]
        clusters = [c for c in clusters if c["country"] in in_scope]
        for c in clusters:
            reality, breakdown = S.reality(c, now)
            weak = S.weakest_assumption(c)
            stage = S.stage_of(c["events"])
            place, state, lat, lon = coords(c["place"], c["country"])
            # stable id across rebuilds: derived from the cluster's earliest mention
            stable_id = uuid.uuid5(uuid.NAMESPACE_URL, f"phantom:{min(str(i) for i in c['mention_ids'])}")
            proj = PhProject(
                id=stable_id, name=c["name"], developer=c["developer"], city=place, state=state, country=c["country"], lat=lat, lon=lon,
                capacity_mw=c["capacity_mw"], capacity_basis=c["capacity_basis"], target_year=c["target_year"],
                power_partner=c["power_partner"], power_source=c["power_source"], cooling=c["cooling"], ai_density=c["ai_density"],
                stage=stage, reality_score=reality, score_breakdown=breakdown,
                weakest_assumption=f"{weak['assumption']} (would lift the score by {round(weak['uplift'] * 100)} pts)" if weak["uplift"] else weak["assumption"],
                call_segments=S.who_to_call(c, reality, now), n_sources=len(c["article_ids"]),
                first_seen=c["first_seen"], last_seen=c["last_seen"], debate=old_debates.get(c["name"]),
            )
            db.add(proj)
            db.flush()
            db.query(PhMention).filter(PhMention.id.in_(c["mention_ids"])).update({PhMention.project_id: proj.id}, synchronize_session=False)
            for e in c["events"]:
                db.add(PhEvidence(project_id=proj.id, article_id=e["article_id"], layer=e["layer"], detail=e.get("detail"),
                                  quote=e.get("quote"), event_date=e.get("published"), verified=True))
            for a in S.anomalies(c, now):
                db.add(PhAnomaly(project_id=proj.id, **a))
                n_anom += 1
        db.commit()
        return {"projects": len(clusters), "mentions": len(mentions), "anomalies": n_anom}
    finally:
        db.close()


def project_gaps(limit: int = 12) -> List[str]:
    """Coverage agent (deterministic part): queries that would strengthen weak projects."""
    db = SessionLocal()
    try:
        qs = []
        for p in db.query(PhProject).order_by(PhProject.capacity_mw.desc().nullslast()).all():
            where = p.city or p.state or p.country or ""
            if p.n_sources <= 1 or not p.capacity_mw or p.stage == 0:
                qs.append(f"{p.developer or ''} {where} data centre".strip())
            if p.n_sources <= 1 and p.stage < 3:
                qs.append(f"{p.developer or ''} {where} data centre power supply".strip())
        return list(dict.fromkeys(q for q in qs if len(q) > 12))[:limit]
    finally:
        db.close()


def unseen_developers(region: str) -> List[str]:
    db = SessionLocal()
    try:
        seen = {(d or "").lower() for (d,) in db.query(PhProject.developer).all()}
        return [f"{d} data centre MW" for d in REGIONS[region]["developers"] if not any(d.lower().split()[0] in s for s in seen)]
    finally:
        db.close()


# ───────────────────────── the LangGraph hunt ─────────────────────────

class HuntState(TypedDict):
    run_id: str
    region: str
    round: int
    max_rounds: int
    queries: List[str]
    log: Annotated[List[str], operator.add]
    stats: Dict[str, Any]


async def _emit(state: HuntState, agent: str, msg: str, kind: str = "agent_thinking"):
    await ws_manager.broadcast(f"hunt-{state['run_id']}", {"type": kind, "agent": agent, "content": msg})


async def plan_node(state: HuntState) -> dict:
    qs = state["queries"] or seed_queries(state["region"])
    await _emit(state, "Planner", f"Round {state['round'] + 1}: {len(qs)} searches across Bing News, Google News and GDELT")
    return {"queries": qs, "log": [f"plan round {state['round'] + 1}: {len(qs)} queries"]}


async def scout_node(state: HuntState) -> dict:
    items = await search(state["queries"], state["region"])
    await _emit(state, "Scouts", f"Found {len(items)} unique articles — fetching full text where publishers allow it")
    fetched = await fetch_all(items, concurrency=8)
    saved = await asyncio.to_thread(save_articles, fetched)
    full = sum(1 for a in fetched if a.text_kind == "full")
    await _emit(state, "Scouts", f"Saved {saved['new']} new articles ({full} full text, {len(fetched) - full} headline-only); {saved['duplicates']} already known")
    return {"log": [f"scout: {len(items)} items, {saved['new']} new"], "stats": {**state["stats"], f"round{state['round'] + 1}_new": saved["new"]}}


async def extract_node(state: HuntState) -> dict:
    todo = await asyncio.to_thread(pending_articles, 400)
    n_m = 0
    for i, a in enumerate(todo, 1):
        try:
            r = await extract_article(a["title"], a["text"], str(a["published"]) if a["published"] else None, state["region"])
            n_m += await asyncio.to_thread(save_mentions, a["id"], r["mentions"], r["meta"].get("model") or "")
        except Exception as e:
            logger.warning(f"[hunt] extract failed: {e!r}")
        if i % 5 == 0 or i == len(todo):
            await _emit(state, "Extractor", f"Read {i}/{len(todo)} articles — {n_m} verified project mentions so far")
    return {"log": [f"extract: {len(todo)} articles, {n_m} mentions"]}


async def resolve_node(state: HuntState) -> dict:
    res = await asyncio.to_thread(rebuild_projects)
    await _emit(state, "Resolver", f"{res['mentions']} mentions resolved into {res['projects']} projects; Anomaly Watch flagged {res['anomalies']}")
    return {"log": [f"resolve: {res}"], "stats": {**state["stats"], **res}}


async def coverage_node(state: HuntState) -> dict:
    gaps = await asyncio.to_thread(project_gaps)
    unseen = await asyncio.to_thread(unseen_developers, state["region"])
    nxt = list(dict.fromkeys(gaps + unseen))[:14]
    await _emit(state, "Coverage", (f"Next round will chase {len(nxt)} gaps: e.g. " + "; ".join(nxt[:3])) if nxt else "Coverage looks complete — stopping")
    return {"queries": nxt, "round": state["round"] + 1, "log": [f"coverage: {len(nxt)} follow-up queries"]}


def _continue(state: HuntState) -> str:
    return "plan" if state["queries"] and state["round"] < state["max_rounds"] else END


def build_hunt_graph():
    g = StateGraph(HuntState)
    for name, fn in (("plan", plan_node), ("scout", scout_node), ("extract", extract_node), ("resolve", resolve_node), ("coverage", coverage_node)):
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "scout")
    g.add_edge("scout", "extract")
    g.add_edge("extract", "resolve")
    g.add_edge("resolve", "coverage")
    g.add_conditional_edges("coverage", _continue, {"plan": "plan", END: END})
    return g.compile()


hunt_graph = build_hunt_graph()


async def run_hunt(run_id: str, region: str, max_rounds: int = 2, queries: Optional[List[str]] = None) -> Dict[str, Any]:
    state: HuntState = {"run_id": run_id, "region": region, "round": 0, "max_rounds": max_rounds,
                        "queries": queries or [], "log": [], "stats": {}}
    try:
        final = await hunt_graph.ainvoke(state, {"recursion_limit": 40})
        status, stats, log = "completed", final["stats"], final["log"]
    except Exception as e:
        logger.exception("[hunt] failed")
        status, stats, log = "failed", {"error": str(e)}, [f"error: {e}"]
    db = SessionLocal()
    try:
        run = db.query(PhRun).filter(PhRun.id == run_id).first()
        if run:
            run.status, run.stats, run.log, run.finished_at = status, stats, log, datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
    await ws_manager.broadcast(f"hunt-{run_id}", {"type": "hunt_finished", "status": status, "stats": stats})
    return {"status": status, "stats": stats}
