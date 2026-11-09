"""Resolver: many mentions → one project ("same project, different names").

1. Normalise: developer → canonical name (alias table); place → canonical city
   (offline gazetteer); facility codes like "JHB2", "KUL1", "MUM2" are pulled
   out of names — they are the strongest identity signal news gives us.
2. Block by (developer, country) so we only ever compare plausible pairs.
3. Inside a block, two mentions are the same project when:
     • they share a facility code, OR
     • names are similar (token-set ratio ≥ 80) AND cities don't conflict AND
       capacities don't conflict (within ±35%, or one is unknown).
   Greedy single-link clustering over mentions sorted by date.
4. Mentions with no developer and no facility code are not resolved — they're
   too ambiguous to merge safely (kept, but not turned into projects).

Canonical values: capacity = most recent verified value with the most specific
basis (IT > facility > campus > unknown); other values are kept for the
Anomaly Watch, which flags conflicts instead of silently averaging them.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from app.phantom.extract import KNOWN_DEVELOPERS
from app.phantom.geo import resolve_place

_CODE = re.compile(r"\b([A-Z]{2,4}\s?\d{1,2}[A-Z]?)\b")
_BASIS_RANK = {"IT": 0, "facility": 1, "campus": 2, "unknown": 3, None: 3}
_STOP = {"data", "centre", "center", "centres", "centers", "campus", "the", "a", "new", "hyperscale", "facility", "project", "dc", "phase"}


# Utilities / IPPs that sign data-centre power deals. Used to name the power partner from a
# *verified* POWER quote when the LLM left the field empty (common for headline-only evidence).
UTILITIES = {
    "TNB": r"\btnb\b|tenaga nasional", "YTL Power": r"ytl power", "Gentari": r"gentari", "Solarvest": r"solarvest",
    "Sarawak Energy": r"sarawak energy", "Tata Power": r"tata power", "NTPC": r"\bntpc\b", "Adani Green": r"adani green",
    "ReNew": r"\brenew\b(?! data)", "JSW Energy": r"jsw energy", "Torrent Power": r"torrent power", "CleanMax": r"clean ?max",
    "AMPIN": r"\bampin\b", "Sembcorp": r"sembcorp", "Avaada": r"avaada", "Hindustan Power": r"hindustan power",
    "Juniper Green": r"juniper green", "MSEDCL": r"\bmsedcl\b|mahadiscom", "TANGEDCO": r"tangedco|tneb",
    "BESCOM": r"\bbescom\b", "Power Grid": r"power ?grid corporation|\bpgcil\b",
}


def power_partner_from_evidence(power_events) -> Optional[str]:
    for e in power_events:
        q = (e.get("quote") or "").lower()
        for name, pat in UTILITIES.items():
            if re.search(pat, q):
                return name
    return None


def canonical_developer(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    low = name.lower()
    squashed = re.sub(r"[^a-z0-9]", "", low)  # "STTGDC" ↔ "STT GDC", "Adani-ConneX" ↔ "AdaniConneX"
    for canon, aliases in KNOWN_DEVELOPERS.items():
        if any(re.search(rf"\b{re.escape(a)}\b", low) for a in aliases):
            return canon
        if any(len(a) > 4 and re.sub(r"[^a-z0-9]", "", a) in squashed for a in aliases):
            return canon
    return re.sub(r"\s+(sdn bhd|bhd|pvt\.? ltd\.?|ltd\.?|limited|inc\.?|llc)$", "", name.strip(), flags=re.I)


def facility_code(name: Optional[str]) -> Optional[str]:
    m = _CODE.search(name or "")
    return m.group(1).replace(" ", "").upper() if m else None


_GENERIC = _STOP | {"ai", "ready", "mw", "gw", "megawatt", "high", "performance", "computing", "hpc", "cloud", "green", "edge",
                    "tier", "iii", "iv", "first", "second", "third", "largest", "new", "india", "malaysia", "johor",
                    "performance", "computing", "artificial", "intelligence", "hyperscale", "colocation", "sovereign",
                    "national", "integrated", "digital", "infrastructure", "park", "parks", "zone", "city", "tech", "technology",
                    "corp", "corporation", "sustainable", "large", "scale", "biggest", "flagship", "mega", "cluster",
                    "facilities", "dc", "s", "its", "india's", "renewable", "powered", "upcoming", "proposed", "planned"}

# Joint ventures that news names by a parent: (parent, country) → the JV that builds there
JV = {("Digital Realty", "India"): "Digital Connexion"}


def distinctive(name: Optional[str]) -> bool:
    """A brand-like token ("Vyoma.AI", "NxtGen") that can anchor a project without a known developer."""
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9.&-]{3,}", name or ""):
        parts = [p for p in re.split(r"[-.]", tok.lower()) if p]
        if tok[0].isupper() and parts and not all(p in _GENERIC or p.isdigit() for p in parts):
            return True
    return False


def name_core(name: Optional[str], developer: Optional[str]) -> str:
    """Identity words only: no developer, no capacity ("52 MW"), no adjectives ("AI-ready")."""
    if PLACEHOLDER.fullmatch((name or "").strip()):
        return ""
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    dev = set(re.findall(r"[a-z0-9]+", (developer or "").lower()))
    return " ".join(w for w in words if w not in _GENERIC and w not in dev and not w.isdigit()
                    and not re.fullmatch(r"\d+(?:mw|gw|kw|mws|gws)", w) and w not in {"null", "none", "specified", "not", "unknown"})


# The model sometimes writes these instead of a name
PLACEHOLDER = re.compile(r"(?i)(null|none|n/?a|unknown|not specified|unnamed|tbd|-+)")


def _cap_compatible(a: Optional[float], b: Optional[float]) -> bool:
    if not a or not b:
        return True
    lo, hi = sorted((a, b))
    return hi / lo <= 1.35


def _same(m: Dict[str, Any], c: Dict[str, Any]) -> bool:
    if m["code"] and m["code"] in c["codes"]:
        return True
    if m["code"] and c["codes"] and m["code"] not in c["codes"]:
        return False  # two different facility codes are two different buildings
    if m["place"] and c["places"] and m["place"] not in c["places"]:
        return False
    if not any(_cap_compatible(m["cap"], x) for x in c["caps"] or [None]):
        return False
    if not m["core"] or not c["cores"]:
        if m["place"] and m["place"] in c["places"]:
            return True  # e.g. "AirTrunk Johor" twice
        # no name and no conflicting place: same developer + same stated capacity (±10%) is the same campus
        return bool(m["cap"]) and any(x and max(m["cap"], x) / min(m["cap"], x) <= 1.10 for x in c["caps"])
    return max(fuzz.token_set_ratio(m["core"], x) for x in c["cores"]) >= 80


def resolve(mentions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """mentions: [{"id", "data", "published", "article_id", "text_kind"}] → clusters with canonical fields."""
    from app.phantom.extract import NON_FACILITY
    prepared = []
    for row in mentions:
        d = row["data"]
        if NON_FACILITY.search(d.get("project_name") or ""):
            continue  # a deal / supply contract, not a facility
        from app.phantom.geo import _OTHER
        if _OTHER.search(d.get("project_name") or ""):
            continue  # the name itself places it outside India / Malaysia ("DayOne Nurmijärvi")
        dev = canonical_developer(d.get("developer"))
        dev = JV.get((dev, d.get("country")), dev)
        code = facility_code(d.get("project_name"))
        if not dev and not code and not distinctive(d.get("project_name")):
            continue  # "52 MW AI-ready data centre" alone is too ambiguous to merge safely
        prepared.append({
            **row, "dev": dev, "code": code, "country": d.get("country"),
            "place": d["_place"] if "_place" in d else  # precomputed in seed snapshots (no article context there)
                     resolve_place(d.get("city"), d.get("state"), d.get("project_name"), d.get("details_quote"), *(d.get("context") or [])),
            "cap": d.get("capacity_mw"), "core": name_core(d.get("project_name"), dev),
        })
    prepared.sort(key=lambda r: (r["published"] is None, r["published"] or 0))

    # a facility code is unique enough to identify the developer when one mention lacks it
    code_dev = {}
    for m in prepared:
        if m["code"] and m["dev"]:
            code_dev.setdefault(m["code"], m["dev"])
    for m in prepared:
        if not m["dev"] and m["code"] in code_dev:
            m["dev"] = code_dev[m["code"]]
            m["core"] = name_core(m["data"].get("project_name"), m["dev"])

    clusters: List[Dict[str, Any]] = []
    for m in prepared:
        block = [c for c in clusters if c["dev"] == m["dev"] and (c["country"] == m["country"] or not c["country"] or not m["country"])]
        target = next((c for c in block if _same(m, c)), None)
        if target is None:
            target = {"dev": m["dev"], "country": m["country"], "codes": set(), "places": set(), "caps": [], "cores": [], "members": []}
            clusters.append(target)
        target["members"].append(m)
        if m["code"]:
            target["codes"].add(m["code"])
        if m["place"]:
            target["places"].add(m["place"])
        if m["cap"]:
            target["caps"].append(m["cap"])
        if m["core"]:
            target["cores"].append(m["core"])
    return [canonicalise(c) for c in clusters]


def canonicalise(c: Dict[str, Any]) -> Dict[str, Any]:
    ms = c["members"]
    names = Counter(m["data"]["project_name"] for m in ms if not PLACEHOLDER.fullmatch((m["data"]["project_name"] or "").strip()))
    if not names:  # every mention had a placeholder name → describe it instead
        place = next((m["place"] for m in ms if m["place"]), None)
        cap = next((m["cap"] for m in ms if m["cap"]), None)
        names = Counter({" ".join(x for x in (place, f"{cap:g} MW" if cap else None, "campus") if x): 1})
    coded = [n for n in names if facility_code(n)]
    branded = [n for n in names if distinctive(n)]
    # prefer a facility code ("JHB2"), then a brand ("Vyoma.AI"), then the most common wording
    name = (max(coded, key=lambda n: names[n]) if coded else
            max(branded, key=lambda n: (names[n], -len(n))) if branded else names.most_common(1)[0][0])
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    dev_tokens = [squash(t) for t in re.findall(r"[A-Za-z0-9&]+", c["dev"] or "") if len(squash(t)) >= 3]
    if c["dev"] and squash(c["dev"]) not in squash(name) and not any(t in squash(name) for t in dev_tokens):
        name = f"{c['dev']} {name}"
    elif c["dev"] and squash(c["dev"]) in squash(name) and c["dev"].lower() not in name.lower():
        # name spells the developer differently ("STTGDC NOI2") — use the canonical spelling
        name = re.sub(r"^\S+", c["dev"], name) if squash(name.split()[0]) == squash(c["dev"]) else name
    capped = [m for m in ms if m["data"].get("capacity_mw")]
    capped.sort(key=lambda m: (_BASIS_RANK.get(m["data"].get("capacity_basis")), -(m["published"].timestamp() if m["published"] else 0)))
    best_cap = capped[0]["data"] if capped else {}
    years = [(m["published"], m["data"].get("target_year")) for m in ms if m["data"].get("target_year")]
    latest_year = sorted(years, key=lambda x: (x[0] is None, x[0] or 0))[-1][1] if years else None
    pick = lambda f: next((m["data"].get(f) for m in reversed(ms) if m["data"].get(f)), None)  # noqa: E731
    place = Counter(m["place"] for m in ms if m["place"]).most_common(1)
    return {
        "name": name[:300], "developer": c["dev"], "country": c["country"],
        "place": place[0][0] if place else None,
        "capacity_mw": best_cap.get("capacity_mw"), "capacity_basis": best_cap.get("capacity_basis") or ("unknown" if best_cap else None),
        "capacities": [{"mw": m["data"]["capacity_mw"], "basis": m["data"].get("capacity_basis"), "published": m["published"], "article_id": m["article_id"]} for m in capped],
        "target_year": latest_year, "target_years": years,
        "power_partner": pick("power_partner") or power_partner_from_evidence(
            e for m in ms for e in m["data"].get("events") or [] if e.get("layer") == "POWER"), "power_source": pick("power_source"), "cooling": pick("cooling"),
        "ai_density": any(m["data"].get("ai_density") for m in ms),
        "mention_ids": [m["id"] for m in ms], "article_ids": list(dict.fromkeys(m["article_id"] for m in ms)),
        "text_kinds": [m.get("text_kind") for m in ms],
        "events": [{**e, "article_id": m["article_id"], "published": m["published"]} for m in ms for e in m["data"].get("events") or []],
        "first_seen": min((m["published"] for m in ms if m["published"]), default=None),
        "last_seen": max((m["published"] for m in ms if m["published"]), default=None),
    }
