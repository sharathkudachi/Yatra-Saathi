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
}


@lru_cache(maxsize=1)
def load_cities() -> Dict[str, Dict[str, str]]:
    """Lower-cased name → {city_id, name}."""
    rows = query_db("SELECT city_id, name FROM cities WHERE status = 'active'")
    return {r["name"].lower(): {"city_id": r["city_id"], "name": r["name"]} for r in rows}


def resolve_city(name: Optional[str]) -> Optional[Dict[str, str]]:
    if not name:
        return None
    key = name.strip().lower()
    cities = load_cities()
    if key in cities:
        return cities[key]
    alias = ALIASES.get(key)
    return cities.get(alias.lower()) if alias else None


def find_city_mentions(text: str) -> List[Tuple[int, str]]:
    """(position, canonical name) for each city or alias mentioned, in text order."""
    names = list(load_cities()) + list(ALIASES)
    names.sort(key=len, reverse=True)
    mentions, taken = [], []
    for name in names:
        city = resolve_city(name)
        if city is None:
            continue
        for match in re.finditer(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
            span = match.span()
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue
            taken.append(span)
            mentions.append((span[0], city["name"]))
    return sorted(mentions)
