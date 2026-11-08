"""Offline gazetteer of data-centre locations (city → state, country, lat, lon).

Kept offline on purpose: no geocoding API calls, no rate limits, deterministic
results. Aliases map the spellings news articles use to one canonical place.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# canonical: (state, country, lat, lon, [aliases])
PLACES = {
    # Malaysia
    "Johor Bahru": ("Johor", "Malaysia", 1.4927, 103.7414, ["johor bahru", "jb", "johor baru"]),
    "Kulai": ("Johor", "Malaysia", 1.6561, 103.6032, ["kulai", "kulaijaya"]),
    "Sedenak": ("Johor", "Malaysia", 1.6870, 103.5460, ["sedenak", "sedenak tech park", "stp"]),
    "Iskandar Puteri": ("Johor", "Malaysia", 1.4250, 103.6420, ["iskandar puteri", "nusajaya", "iskandar"]),
    "Pasir Gudang": ("Johor", "Malaysia", 1.4700, 103.9030, ["pasir gudang"]),
    "Kluang": ("Johor", "Malaysia", 2.0251, 103.3328, ["kluang"]),
    "Johor": ("Johor", "Malaysia", 1.8550, 103.5000, ["johor"]),
    "Cyberjaya": ("Selangor", "Malaysia", 2.9213, 101.6559, ["cyberjaya"]),
    "Kuala Lumpur": ("Kuala Lumpur", "Malaysia", 3.1390, 101.6869, ["kuala lumpur", "kl"]),
    "Selangor": ("Selangor", "Malaysia", 3.0738, 101.5183, ["selangor", "shah alam", "petaling jaya", "puchong", "rawang", "bukit jalil", "klang"]),
    "Negeri Sembilan": ("Negeri Sembilan", "Malaysia", 2.7258, 101.9424, ["negeri sembilan", "nilai", "seremban", "port dickson"]),
    "Kulim": ("Kedah", "Malaysia", 5.3650, 100.5617, ["kulim"]),
    "Penang": ("Penang", "Malaysia", 5.4141, 100.3288, ["penang", "batu kawan"]),
    # India
    "Navi Mumbai": ("Maharashtra", "India", 19.0330, 73.0297, ["navi mumbai", "panvel", "airoli", "mahape", "rabale", "ghansoli"]),
    "Mumbai": ("Maharashtra", "India", 19.0760, 72.8777, ["mumbai", "bombay", "chandivali", "powai", "bkc", "thane", "bhiwandi"]),
    "Pune": ("Maharashtra", "India", 18.5204, 73.8567, ["pune", "chakan", "talegaon", "hinjewadi"]),
    "Chennai": ("Tamil Nadu", "India", 13.0827, 80.2707, ["chennai", "ambattur", "siruseri", "sriperumbudur", "oragadam", "kanchipuram"]),
    "Hyderabad": ("Telangana", "India", 17.3850, 78.4867, ["hyderabad", "shamshabad", "medchal", "gachibowli"]),
    "Noida": ("Uttar Pradesh", "India", 28.5355, 77.3910, ["noida", "greater noida", "yamuna expressway"]),
    "Delhi NCR": ("Delhi", "India", 28.6139, 77.2090, ["delhi", "new delhi", "gurugram", "gurgaon", "ncr", "faridabad"]),
    "Bengaluru": ("Karnataka", "India", 12.9716, 77.5946, ["bengaluru", "bangalore", "whitefield"]),
    "Kolkata": ("West Bengal", "India", 22.5726, 88.3639, ["kolkata", "calcutta", "new town", "rajarhat"]),
    "Visakhapatnam": ("Andhra Pradesh", "India", 17.6868, 83.2185, ["visakhapatnam", "vizag"]),
    "Ahmedabad": ("Gujarat", "India", 23.0225, 72.5714, ["ahmedabad", "gift city", "gandhinagar", "dholera"]),
    "Jamnagar": ("Gujarat", "India", 22.4707, 70.0577, ["jamnagar"]),
    "Lucknow": ("Uttar Pradesh", "India", 26.8467, 80.9462, ["lucknow"]),
    "Kochi": ("Kerala", "India", 9.9312, 76.2673, ["kochi", "cochin"]),
}

COUNTRY_CENTRE = {"Malaysia": (3.9, 102.0), "India": (21.0, 78.0)}

_ALIAS = sorted(((a, canon) for canon, v in PLACES.items() for a in v[4]), key=lambda x: -len(x[0]))


def resolve_place(*texts: Optional[str]) -> Optional[str]:
    """First canonical place whose alias appears in any of the given strings (longest alias wins)."""
    for t in texts:
        low = (t or "").lower()
        if not low:
            continue
        for alias, canon in _ALIAS:
            if re.search(rf"\b{re.escape(alias)}\b", low):
                return canon
    return None


_IN = re.compile(r"\bindia\b|\bindian\b|₹|\brs\.?\s?\d|\bcrore\b|\blakh\b|maharashtra|tamil nadu|telangana|uttar pradesh|karnataka", re.I)
_MY = re.compile(r"\bmalaysia\b|\bmalaysian\b|\bringgit\b|\brm\s?\d|\bjohor\b|selangor|\btnb\b|tenaga nasional|bursa", re.I)
_OTHER = re.compile(r"\b(indonesia|jakarta|batam|singapore|thailand|bangkok|vietnam|philippines|japan|australia|united states|u\.s\.|europe|finland|nurmij\w*|sweden|norway|denmark|ireland|germany|netherlands|spain|united kingdom|hong kong|china|taiwan|korea)\b", re.I)


def infer_country(*texts: Optional[str]) -> Optional[str]:
    """Country of a mention: a gazetteer place wins; else whichever country's signals dominate the text."""
    place = resolve_place(*texts)
    if place:
        return PLACES[place][1]
    blob = " ".join(t or "" for t in texts)
    i, m, o = len(_IN.findall(blob)), len(_MY.findall(blob)), len(_OTHER.findall(blob))
    if max(i, m) == 0 or o > max(i, m):
        return None
    return "India" if i > m else "Malaysia" if m > i else None


def coords(place: Optional[str], country: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[float]]:
    if place and place in PLACES:
        st, c, lat, lon, _ = PLACES[place]
        return place, st, lat, lon
    if country in COUNTRY_CENTRE:
        lat, lon = COUNTRY_CENTRE[country]
        return None, None, lat, lon
    return None, None, None, None
