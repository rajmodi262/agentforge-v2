"""The Verifier — deterministic checks of every extracted claim against its source.

No LLM is involved here, on purpose: a model cannot be trusted to grade itself.
A claim survives only if the article text actually supports it:

* quote       → appears in the article (exact after normalisation, else ≥90 fuzzy)
* capacity    → capacity_text appears in the article AND parses to capacity_mw (±2%)
* developer / city / power partner → the name appears in the article
* target_year → the year appears in the article
* event layer → its quote exists AND contains words that fit that layer
                 (a "POWER" event whose quote never mentions power is rejected)

Rejected claims are removed before anything is scored, and every verdict is
stored, so the UI can show exactly why a fact was dropped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

_WS = re.compile(r"\s+")
_TRANS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})

LAYER_WORDS = {
    "ANNOUNCED": r"announc|plan|invest|propos|unveil|mou|memorandum|intend|will|to build|to develop|set up|commit|deal|agreement|partner|expan|launch|tenant|lease",
    "SITE": r"\bland\b|acre|hectare|site|plot|parcel|lease|acquir|purchas|bought",
    "APPROVED": r"approv|clearance|permit|licen[cs]|sanction|consent|nod|green light|authori[sz]",
    # POWER means power is SECURED — not merely mentioned ("AI computing power" is not evidence)
    "POWER": r"\bppa\b|power purchase|power supply (?:agreement|deal|contract)|electricity supply (?:agreement|deal)|"
             r"grid (?:connection|access|capacity (?:was |has been )?(?:allocated|approved|secured))|substation|"
             r"grid interconnection|interconnection agreement|"  # bare "interconnected" is usually networking, not power
             r"\b\d+\s?kv\b|\btnb\b|tenaga nasional|\bdiscom\b|transmission line|secured (?:\d+\s?mw of )?power|"
             r"power (?:allocation|connection) (?:approved|granted|secured)|signed [^.]{0,40}\b(?:power|electricity|energy)\b[^.]{0,40}\b(?:agreement|deal)",
    "BUILDING": r"construct|ground[- ]?break|broke ground|groundwork|\bbuild|\bepc\b|contractor|foundation stone|bhoomi|under way|underway|piling",
    "LIVE": r"operational|commission|launch|inaugurat|\blive\b|energi[sz]|went online|opened|opens|began operations|start(?:ed)? operations|ready for service|completion of|completed",
    "DELAYED": r"delay|postpon|pushed back|on hold|slip|behind schedule|deferr|paus",
    "CANCELLED": r"cancel|scrap|withdr|terminat|abandon|shelv|pull(?:ed)? out|called off",
    "OPPOSITION": r"protest|oppos|object|resident|complain|petition|backlash|concern|moratorium|freeze",
    "SCALED_DOWN": r"reduc|scale(?:d)? back|downsiz|cut|lower(?:ed)? .*capacity|trim",
}


# Words too common to prove a company / place is the one named ("Hiranandani Group" ↔ "group")
_GENERIC_NAME_TOKENS = {
    "data", "centre", "center", "centres", "centers", "the", "ltd", "sdn", "bhd", "pvt", "limited", "campus", "group",
    "holdings", "infrastructure", "capital", "digital", "cloud", "power", "energy", "technologies", "technology", "services",
    "india", "malaysia", "global", "international", "partners", "networks", "systems", "solutions", "corporation", "corp",
    "company", "inc", "llc", "park", "city", "new", "and", "ventures", "properties", "realty", "land",
}


# A positive stage needs a fact, not an intention: "must build substations" / "plans to sign a PPA"
_HEDGE = re.compile(r"\b(must|needs? to|would need|will need|requires?|required|seeking|seeks|plans? to|planning to|proposed|intends? to|aims? to|in talks|negotiat"
                    r"|expected to|is set to|slated to|scheduled to|will (?:be|go|start|begin|open|commence|acquire|buy|sign)|to be (?:commissioned|operational|completed|built)"
                    r"|seeks?|seeking|mulls?|eyes|considering|weighs)\b", re.I)


def event_fits(layer: Optional[str], quote: str) -> bool:
    """Does this quote actually prove `layer`? Layer words must appear; for the positive stages
    beyond ANNOUNCED, hedged / intended language does not count."""
    words = LAYER_WORDS.get(layer or "", "")
    q = norm(quote or "")
    if not words or not re.search(words, q):
        return False
    if layer in ("SITE", "APPROVED", "POWER", "BUILDING", "LIVE") and _HEDGE.search(q):
        return False
    return True


def norm(s: str) -> str:
    return _WS.sub(" ", (s or "").translate(_TRANS)).strip().lower()


def quote_found(quote: Optional[str], text_norm: str) -> Tuple[bool, str]:
    q = norm(quote or "")
    if len(q) < 12:
        return False, "quote missing or too short"
    if q in text_norm:
        return True, "exact"
    score = fuzz.partial_ratio(q, text_norm)
    return (score >= 90, f"fuzzy {score:.0f}")


def name_found(name: Optional[str], text_norm: str) -> Tuple[bool, str]:
    n = norm(name or "")
    if not n:
        return False, "empty"
    if n in text_norm:
        return True, "exact"
    # allow "AirTrunk JHB1" ↔ "AirTrunk" style partial matches on the distinctive token(s)
    tokens = [t for t in re.findall(r"[a-z0-9]+", n) if len(t) > 2 and t not in _GENERIC_NAME_TOKENS]
    hits = [t for t in tokens if re.search(rf"\b{re.escape(t)}\b", text_norm)]
    if tokens and len(hits) >= max(1, len(tokens) // 2):
        return True, f"tokens {hits}"
    return False, "not in article"


_CAP = re.compile(r"(\d+(?:[.,]\d+)?)\s*(gw|gigawatts?|mw|megawatts?)", re.I)


def parse_capacity(text: Optional[str]) -> Optional[float]:
    m = _CAP.search(text or "")
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    return val * 1000 if m.group(2).lower().startswith("g") else val


def verify_mention(mention: Dict[str, Any], article_text: str) -> Tuple[Dict[str, Any], Dict[str, Any], float]:
    """Return (clean_mention, verdicts, verified_ratio). Unsupported fields are nulled / dropped."""
    t = norm(article_text)
    v: Dict[str, Any] = {}
    clean = dict(mention)

    def check(field: str, ok: bool, why: str):
        v[field] = {"ok": ok, "why": why}
        if not ok:
            clean[field] = None

    ok, why = name_found(mention.get("project_name"), t)
    if not ok and mention.get("developer"):
        ok, why = name_found(mention.get("developer"), t)
    v["project_name"] = {"ok": ok, "why": why}

    for f in ("developer", "city", "state", "power_partner"):
        if mention.get(f):
            check(f, *name_found(mention[f], t))
    if mention.get("country"):
        v["country"] = {"ok": True, "why": "context"}  # country is region context, not a claim we score

    if mention.get("capacity_mw") is not None:
        cap_text = mention.get("capacity_text")
        parsed = parse_capacity(cap_text)
        in_text = bool(cap_text) and norm(cap_text) in t
        if not in_text and cap_text:
            # tolerate "300 MW" vs "300MW" spacing differences
            in_text = norm(cap_text).replace(" ", "") in t.replace(" ", "")
        matches = parsed is not None and abs(parsed - float(mention["capacity_mw"])) <= max(1.0, 0.02 * parsed)
        check("capacity_mw", in_text and matches,
              "ok" if in_text and matches else ("capacity_text not in article" if not in_text else f"text says {parsed} MW, field says {mention['capacity_mw']}"))
        if not v["capacity_mw"]["ok"]:
            clean["capacity_text"] = None

    if mention.get("target_year"):
        y = str(mention["target_year"])
        check("target_year", y in t, "ok" if y in t else "year not in article")

    for f in ("power_source", "cooling"):
        if mention.get(f):
            check(f, *name_found(mention[f], t))

    if mention.get("ai_density"):
        dens = bool(re.search(r"\bai\b|artificial intelligence|gpu|high[- ]density|hpc|nvidia|liquid cool", t))
        check("ai_density", dens, "ok" if dens else "no AI / high-density wording")
        if not dens:
            clean["ai_density"] = False

    events: List[Dict[str, Any]] = []
    ev_verdicts = []
    for e in mention.get("events") or []:
        layer = e.get("layer") if isinstance(e.get("layer"), str) else getattr(e.get("layer"), "value", None)
        q_ok, q_why = quote_found(e.get("quote"), t)
        words = LAYER_WORDS.get(layer or "", "")
        fits = event_fits(layer, e.get("quote", ""))
        ok = q_ok and fits
        ev_verdicts.append({"layer": layer, "ok": ok, "why": q_why if not q_ok else ("ok" if fits else f"quote doesn't describe {layer}")})
        if ok:
            events.append({**e, "layer": layer})
    clean["events"] = events
    v["events"] = ev_verdicts

    claims = [x["ok"] for k, x in v.items() if k != "events" and k != "country"] + [x["ok"] for x in ev_verdicts]
    ratio = sum(claims) / len(claims) if claims else 0.0
    return clean, v, round(ratio, 3)
