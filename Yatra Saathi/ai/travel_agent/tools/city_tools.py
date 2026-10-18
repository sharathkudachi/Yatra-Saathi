# travel_agent/tools/city_tools.py
"""Resolve city names in free text to cities.city_id (read-only)."""
import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from travel_agent.tools.db import query_db

# Common alternative names → the name used in cities.name. Only real synonyms;
# "Goa" is a state whose capital Panaji is the dataset's city.
ALIASES = {
    "bangalore": "Bengaluru", "bombay": "Mumbai", "delhi": "New Delhi",
    "calcutta": "Kolkata", "madras": "Chennai", "mysore": "Mysuru",
    "trivandrum": "Thiruvananthapuram", "pondy": "Pondicherry",
    "puducherry": "Pondicherry", "goa": "Panaji", "vizag": "Visakhapatnam",
    # Indic transliterations (Hindi & Tamil)
    "जयपुर": "Jaipur", "दिल्ली": "New Delhi", "नई दिल्ली": "New Delhi",
    "मुंबई": "Mumbai", "बम्बई": "Mumbai", "बेंगलुरु": "Bengaluru",
    "बैंगलोर": "Bengaluru", "कोलकाता": "Kolkata", "चेन्नई": "Chennai",
    "मद्रास": "Chennai", "गोवा": "Panaji", "आगरा": "Agra",
    "वाराणसी": "Varanasi", "उदयपुर": "Udaipur", "कोच्चि": "Kochi",
    "केरल": "Kochi",
    "ஜெய்ப்பூர்": "Jaipur", "ஜெய்ப்பூருக்கு": "Jaipur", "தில்லி": "New Delhi",
    "மும்பை": "Mumbai", "பெங்களூரு": "Bengaluru", "கொல்கத்தா": "Kolkata",
    "சென்னை": "Chennai", "கோவா": "Panaji", "ஆக்ரா": "Agra",
    "வாரணாசி": "Varanasi", "உதய்பூர்": "Udaipur", "கொச்சி": "Kochi",
}


@lru_cache(maxsize=1)
def load_cities() -> Dict[str, Dict[str, str]]:
    """Lower-cased name → {city_id, name}."""
    rows = query_db("SELECT city_id, name FROM cities WHERE status = 'active'")
    return {r["name"].lower(): {"city_id": r["city_id"], "name": r["name"]} for r in rows}


def load_cities_via_backend(client, session_id: str) -> Dict[str, Dict[str, str]]:
    """Same shape as `load_cities`, but through the backend's catalog route --
    no SQLite access from the agent process. Not `lru_cache`d: a fresh client
    may be constructed per run."""
    rows = client.catalog_cities(session_id)
    return {r["name"].lower(): {"city_id": r["city_id"], "name": r["name"]} for r in rows}


def resolve_city(name: Optional[str], cities: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[Dict[str, str]]:
    if not name:
        return None
    key = name.strip().lower()
    cities = load_cities() if cities is None else cities
    if key in cities:
        return cities[key]
    alias = ALIASES.get(key)
    return cities.get(alias.lower()) if alias else None


def find_city_mentions(text: str, cities: Optional[Dict[str, Dict[str, str]]] = None) -> List[Tuple[int, str]]:
    """(position, canonical name) for each city or alias mentioned, in text order."""
    cities = load_cities() if cities is None else cities
    names = list(cities) + list(ALIASES)
    names.sort(key=len, reverse=True)
    mentions, taken = [], []
    for name in names:
        city = resolve_city(name, cities)
        if city is None:
            continue
        pattern = re.escape(name) if any(ord(c) > 127 for c in name) else rf"\b{re.escape(name)}\b"
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            span = match.span()
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue
            taken.append(span)
            mentions.append((span[0], city["name"]))
    return sorted(mentions)
