"""Evidence Extractor: article text → verified project mentions.

LLM proposes, verifier disposes:

1. the model reads one article and returns structured mentions (schema.ArticleExtraction);
2. parsing is lenient per project and per event — one malformed event never
   throws away the rest of the article;
3. a deterministic gazetteer fills a missing developer when exactly one known
   developer is named in the article (small models often skip the obvious one);
4. market-level statistics are dropped (a project needs a developer or a named
   facility, and the article must be project news);
5. verify.verify_mention removes every claim the article does not support.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.phantom.llm import structured
from app.phantom.schema import EXTRACTOR_SYSTEM, ArticleExtraction, Event, ProjectMention
from app.phantom.sources import REGIONS
from app.phantom.verify import norm, verify_mention

logger = logging.getLogger(__name__)

MAX_CHARS = 3200      # ~800 tokens of article — news puts the facts up front; prompt reading dominates on a laptop
EXTRACT_CTX = 4096    # small context keeps a 7B model mostly on a 4 GB GPU
MAX_OUT = 1100        # output cap: enough for 4 projects with events, not enough to loop for minutes
TIMEOUT_S = 150       # a single article may not hold the batch hostage

# Known developers / operators (canonical name, aliases). Used only to FILL a
# missing developer when the article names exactly one of them — never to override.
KNOWN_DEVELOPERS: Dict[str, List[str]] = {
    "AirTrunk": ["airtrunk"], "YTL": ["ytl"], "Bridge Data Centres": ["bridge data centres", "bdc"],
    "Princeton Digital Group": ["princeton digital", "pdg"], "STACK Infrastructure": ["stack infrastructure"],
    "Vantage Data Centers": ["vantage"], "Equinix": ["equinix"], "Yondr": ["yondr"], "DayOne": ["dayone", "day one"],
    "K2 Strategic": ["k2 strategic"], "Microsoft": ["microsoft"], "Google": ["google"], "Amazon Web Services": ["aws", "amazon web services"],
    "NTT DATA": ["ntt"], "Digital Realty": ["digital realty"], "Keppel": ["keppel"], "Gamuda": ["gamuda"], "EdgeConneX": ["edgeconnex"],
    "Yotta": ["yotta"], "CtrlS": ["ctrls"], "AdaniConneX": ["adaniconnex", "adani connex"], "Sify": ["sify"], "Nxtra": ["nxtra"],
    "STT GDC": ["stt gdc", "st telemedia"], "Reliance Jio": ["reliance", "jio"], "Colt DCS": ["colt dcs", "colt data centre"],
    "Digital Connexion": ["digital connexion"], "CapitaLand": ["capitaland"], "Lodha": ["lodha"], "Hiranandani": ["hiranandani"],
    "Tata Communications": ["tata communications"], "Iron Mountain": ["iron mountain"], "Oracle": ["oracle"], "Meta": ["meta"],
    "CoreWeave": ["coreweave"], "Anant Raj": ["anant raj"], "RackBank": ["rackbank"], "Web Werks": ["web werks"],
    "ESR": ["esr data centres", "esr"], "Lumina CloudInfra": ["lumina cloudinfra", "lumina"], "Techno Digital": ["techno digital"],
    "Telekom Malaysia": ["telekom malaysia", "tm one", "tm nxera", "nxera"], "Zdata": ["zdata"], "Open DC": ["open dc"], "Basis Bay": ["basis bay"],
    "NeXtDC": ["nextdc"], "Airtel": ["airtel"], "Hiranandani Group": ["hiranandani"], "Blackstone": ["blackstone"],
    "Brookfield": ["brookfield"], "Mapletree": ["mapletree"], "GDS": ["gds holdings", "gds international", "dayone"],
    "Pure Data Centres": ["pure dc", "pure data centres"], "Global Switch": ["global switch"], "Sunway": ["sunway"],
    "L&T Vyoma": ["l&t", "larsen & toubro", "larsen and toubro", "vyoma"], "Hiranandani Yotta": ["yotta infrastructure"],
    "RackBank Datacenters": ["rackbank"], "Blackstone Lumina": ["lumina"], "Tata Power": ["tata power"],
    "TCS HyperVault": ["hypervault", "tata consultancy", "tcs"], "Infosys": ["infosys"], "Ascendas": ["ascendas"], "Bain Capital Bridge": ["bain capital"],
    "Gamuda Land": ["gamuda land"], "Sime Darby Property": ["sime darby"], "Iskandar Investment": ["iskandar investment"],
    "Edgenta": ["edgenta"], "Johor Corporation": ["jcorp", "johor corporation"], "Yondr": ["yondr"],
    "Bitdeer": ["bitdeer"], "Avisirah": ["avisirah"], "Fortune Hospitality": ["fortune hospitality"],
    "NxtGen": ["nxtgen"], "Yotta Data Services": ["yotta data services"], "Adani Group": ["adani group"],
    "Tata Power Renewable": ["tata power renewable"], "BharatNet": ["bharatnet"], "Anant Raj Cloud": ["anant raj cloud"],
}

GENERIC_NAME = re.compile(r"\b(hub|market|industry|sector|state|region|country|capacity|pipeline|corridor|demand)\b", re.I)
# names that describe a deal / supply contract rather than a facility
NON_FACILITY = re.compile(r"\b(agreement|deal|partnership|alliance|contract|fuel[- ]?cells?|ppa|mou|order|tender|investment plan|funding|ipo|stake|acquisition of|solar|wind farm|hydro|power plant|battery storage)\b", re.I)


def gazetteer_developer(text: str, project_name: Optional[str] = None) -> Optional[str]:
    """Known developer for a mention: the only one in the article, else the one named
    closest to (within 300 chars of) the project name. Never overrides the model."""
    t = norm(text)
    hits: Dict[str, List[int]] = {}
    for canon, aliases in KNOWN_DEVELOPERS.items():
        for a in aliases:
            for m in re.finditer(rf"\b{re.escape(a)}\b", t):
                hits.setdefault(canon, []).append(m.start())
    if len(hits) == 1:
        return next(iter(hits))
    if not hits or not project_name:
        return None
    pos = [m.start() for tok in re.findall(r"[a-z0-9]{3,}", norm(project_name))
           if tok not in {"data", "centre", "center", "campus", "hyperscale"}
           for m in re.finditer(rf"\b{re.escape(tok)}\b", t)]
    if not pos:
        return None
    best = min(((abs(p - q), canon) for canon, ps in hits.items() for p in ps for q in pos), default=None)
    return best[1] if best and best[0] <= 300 else None


def _lenient_projects(raw: Dict[str, Any]) -> List[ProjectMention]:
    out = []
    for p in (raw.get("projects") or [])[:5]:
        if not isinstance(p, dict):
            continue
        events = []
        for e in p.get("events") or []:
            try:
                events.append(Event(**e))
            except (ValidationError, TypeError):
                continue  # drop just this event
        try:
            out.append(ProjectMention(**{**p, "events": events}))
        except (ValidationError, TypeError):
            continue
    return out


async def extract_article(title: str, text: str, published: Optional[str], region: Optional[str] = None) -> Dict[str, Any]:
    """Returns {"mentions": [...], "is_project_news": bool, "meta": {...}, "dropped": [...]}."""
    body = text[:MAX_CHARS]
    user = f"ARTICLE (published {published or 'unknown'}):\nTITLE: {title}\n\n{body}"
    async def call(prompt: str):
        return await asyncio.wait_for(
            structured(EXTRACTOR_SYSTEM, prompt, ArticleExtraction, max_tokens=MAX_OUT, tier="fast",
                       agent="Evidence Extractor", num_ctx=EXTRACT_CTX, temperature=0.1),
            timeout=TIMEOUT_S,
        )

    raw, meta = await call(user)
    projects = _lenient_projects(raw)
    # Self-correction: the article clearly names a known developer AND a capacity, yet the
    # model found nothing — retry once, telling it what to look for.
    hint_dev = gazetteer_developer(f"{title}. {body}", title)
    if not projects and hint_dev and re.search(r"\d+(?:\.\d+)?\s?(?:MW|GW|megawatt|gigawatt)", body, re.I):
        raw2, meta2 = await call(user + f"\n\nNOTE: this article appears to describe a specific data-centre project by {hint_dev}. "
                                        "If it does, extract it (with its capacity and location); if it truly only gives market totals, return no projects.")
        projects = _lenient_projects(raw2)
        if projects:
            raw, meta = raw2, {**meta2, "retried": True, "tokens": meta["tokens"] + meta2["tokens"]}
    is_news = bool(raw.get("is_project_news", True)) or bool(projects and any(p.developer for p in projects))
    country = REGIONS.get(region or "", {}).get("country")

    mentions: List[Dict[str, Any]] = []
    dropped: List[str] = []
    for p in projects:
        d = p.model_dump(mode="json")
        gaz = None if d.get("developer") else gazetteer_developer(body, d.get("project_name"))
        if gaz:
            d["developer"], d["_developer_from"] = gaz, "gazetteer"
        if not d.get("country") and country:
            d["country"] = country
        rescue_quotes(d, body)
        clean, verdicts, ratio = verify_mention(d, body)
        if not verdicts["project_name"]["ok"]:
            dropped.append(f"{d['project_name']}: not in article (hallucinated)")
            continue
        if not is_news or (not clean.get("developer") and GENERIC_NAME.search(d["project_name"] or "")):
            dropped.append(f"{d['project_name']}: market statistic, not a project")
            continue
        if NON_FACILITY.search(d["project_name"] or ""):
            dropped.append(f"{d['project_name']}: a deal / supply contract, not a facility")
            continue
        mined = mine_evidence(clean, body)
        clean["events"] = clean["events"] + mined
        clean["context"] = project_sentences(clean, body)[:3]  # for the resolver's place detection
        mentions.append({"data": clean, "verification": {**verdicts, "mined": [m["layer"] for m in mined]},
                         "verified_ratio": ratio, "raw": d})
    return {"mentions": mentions, "is_project_news": is_news, "meta": meta, "dropped": dropped}


# ───────────────────────── Evidence Miner (deterministic) ─────────────────────────
# Precise stage language, applied only to sentences that mention the project.
# Future-tense sentences ("will open", "expected to be commissioned") never prove
# a stage beyond ANNOUNCED.

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])|\n+")  # sentence ends, or line breaks (headlines have no full stop)
_FUTURE = re.compile(r"\b(will|would|plans? to|planning|expected to|aims? to|to be (?:built|commissioned|operational)|proposed|could|by 20\d\d|slated|must|needs? to|requires?|in talks|negotiat\w*|seeks?|seeking|mulls?|eyes|considering|weighs)\b", re.I)
STAGE_PATTERNS = {
    "LIVE": r"\b(opened|opens|inaugurated|inaugurates|commissioned|commissions|commissioning|operationali[sz]ation|is (?:now )?operational|became operational|went live|began operations|started operations|launched (?:its|the)|is live|now live|opening of|completion of (?:its|the)|launch(?:es|ed)? (?:its |a |the )?(?:new |first |purpose-built )?[\w-]*\s?(?:data cent(?:er|re)|campus|ibx|facility))\b",
    "BUILDING": r"\b(broke ground|ground[- ]?breaking ceremony|began construction|started construction|commenced construction|construction (?:has |had )?(?:begun|began|started|commenced|is (?:well )?under ?way)|under construction|laid the foundation|work (?:has )?(?:begun|began|started) on)\b",
    "POWER": r"\b(power purchase agreement|signed (?:an? )?(?:ppa|power)|signs? [^.]{0,30}\b(?:solar|wind|renewable|power|electricity) (?:deal|agreement|ppa) with|electricity supply agreement|power supply agreement|grid connection agreement|secured (?:\d+\s?mw of )?power|dedicated substation)\b",
    "SITE": r"\b(acquired|purchased|bought|leased|secured|allotted|allocated)\b[^.]{0,60}\b(land|acres?|hectares?|site|plot|parcel)\b|\bland acquisition\b",
    "APPROVED": r"\b(received|obtained|granted|got|secured)\b[^.]{0,40}\b(approval|clearance|permit|licen[cs]e|nod)\b|\bapproved\b",
    "FINANCED": r"\b(loan|financing|financed|debt facility|credit facility|green bond|syndicated|bookrunners?|lead arrangers?|raised [^.]{0,40}(?:debt|capital|funding))\b",
    "DELAYED": r"\b(delayed|postponed|pushed back|put on hold|behind schedule|deferred)\b",
    "CANCELLED": r"\b(cancelled|canceled|scrapped|withdrawn|abandoned|shelved|called off|pulled out)\b",
    "OPPOSITION": r"\b(protest(?:s|ed)?|opposition from|objections? (?:from|by)|residents (?:oppose|object)|moratorium)\b",
    "SCALED_DOWN": r"\b(scaled back|downsized|reduced (?:its |the )?capacity|cut (?:its |the )?capacity)\b",
}


def _anchors(m: Dict[str, Any]) -> List[str]:
    from app.phantom.resolve import facility_code
    out = []
    code = facility_code(m.get("project_name"))
    if code:
        out.append(norm(code))
    dev = (m.get("developer") or "").split("(")[0]
    for canon, aliases in KNOWN_DEVELOPERS.items():
        if canon.lower() in dev.lower() or any(a in dev.lower() for a in aliases):
            out += aliases
    if dev and len(dev) > 3:
        out.append(norm(dev).split(" ")[0])
    if m.get("capacity_text"):
        out.append(norm(m["capacity_text"]))
    return [a for a in dict.fromkeys(out) if len(a) >= 3]


def project_sentences(m: Dict[str, Any], text: str, window: int = 2) -> List[str]:
    """Sentences about this project: ones that name it, plus up to `window` following
    sentences ("The company has signed a PPA…") until another developer or facility
    code appears — a cheap, conservative stand-in for coreference resolution."""
    from app.phantom.resolve import facility_code
    anchors = _anchors(m)
    own_code = facility_code(m.get("project_name"))
    own = {a for a in anchors}
    others = [a for canon, aliases in KNOWN_DEVELOPERS.items() for a in aliases if a not in own and len(a) > 3]
    sents = [s.strip() for s in _SENT.split(text) if s and 25 <= len(s.strip()) <= 800]
    keep, carry = [], 0
    for s in sents:
        ns = norm(s)
        named = any(re.search(rf"\b{re.escape(a)}\b", ns) for a in anchors)
        foreign = any(re.search(rf"\b{re.escape(a)}\b", ns) for a in others) or (
            (c := facility_code(s)) is not None and c != own_code)
        if named:
            keep.append(s)
            carry = window
        elif carry and not foreign:
            keep.append(s)
            carry -= 1
        else:
            carry = 0
    return keep


def mine_evidence(m: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
    have = {e["layer"] for e in m.get("events") or []}
    found = []
    for s in project_sentences(m, text):
        for layer, pat in STAGE_PATTERNS.items():
            if layer in have or not re.search(pat, s, re.I):
                continue
            if layer not in ("DELAYED", "CANCELLED", "OPPOSITION", "SCALED_DOWN") and _FUTURE.search(s):
                continue
            found.append({"layer": layer, "detail": f"{layer.title()} (stage language in the article)", "quote": s[:500], "source": "miner"})
            have.add(layer)
    return found


def upgrade_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The LLM under-labels: "announced the completion of its data centre" comes back as ANNOUNCED.
    If an event's own (verified) quote contains precise, non-future language for another stage,
    add that stage too. Audit finding: 7 of 40 sampled items were under-labelled this way."""
    from app.phantom.verify import event_fits
    have = {e.get("layer") for e in events}
    out = []
    for e in events:
        q = e.get("quote") or ""
        for layer, pat in STAGE_PATTERNS.items():
            if layer in have or layer in ("DELAYED", "CANCELLED", "OPPOSITION", "SCALED_DOWN"):
                continue
            if re.search(pat, q, re.I) and not _FUTURE.search(q) and (layer == "FINANCED" or event_fits(layer, q)):
                out.append({"layer": layer, "detail": f"{layer.title()} (stage language in the article)", "quote": q, "source": "upgrade"})
                have.add(layer)
    return out


def rescue_quotes(m: Dict[str, Any], text: str) -> None:
    """The LLM picked a layer but left the quote empty/garbled: take the article's own
    sentence that mentions the project and fits that layer. Still verified afterwards."""
    from app.phantom.verify import LAYER_WORDS, quote_found
    t = norm(text)
    sents = None
    for e in m.get("events") or []:
        words = LAYER_WORDS.get(e.get("layer") if isinstance(e.get("layer"), str) else "", "")
        if quote_found(e.get("quote"), t)[0] and words and re.search(words, norm(e.get("quote", ""))):
            continue  # already a good, matching quote
        sents = sents if sents is not None else project_sentences(m, text)
        match = next((s for s in sents if words and re.search(words, norm(s))), None)
        if match:
            e["quote"], e["source"] = match[:500], "rescued"
