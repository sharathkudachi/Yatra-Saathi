# travel_agent/tools/activity_tools.py
"""Activity (POI) search.

The dataset ships no activities table; POIs exist only as itinerary_items with
entity_type = 'poi'. Each POI belongs to one city via itineraries → trips
.destination_city_id, and every row for a POI carries the same title and cost.
Popularity = how many non-removed itinerary items reference the POI.
The recorded cost is charged per traveller (conservative for the spend cap).
"""
from typing import Any, Dict, List

from travel_agent.tools.budget_tools import to_money
from travel_agent.tools.db import query_db

_ACTIVITY_SQL = """
SELECT it.entity_id AS poi_id, it.title, it.cost, it.currency,
       MAX(it.duration_minutes) AS duration_minutes, COUNT(*) AS times_planned
FROM itinerary_items it
JOIN itineraries iti ON iti.itinerary_id = it.itinerary_id
JOIN trips t        ON t.trip_id = iti.trip_id
WHERE it.entity_type = 'poi' AND it.status <> 'removed' AND t.destination_city_id = ?
GROUP BY it.entity_id, it.title, it.cost, it.currency
"""


def search_activities(city_id: str, currency: str) -> Dict[str, Any]:
    """Return distinct activities in the city, most planned first (duplicate titles merged)."""
    rows = query_db(_ACTIVITY_SQL, (city_id,))
    rows.sort(key=lambda r: (-r["times_planned"], r["title"].strip(), r["poi_id"]))
    options: List[Dict[str, Any]] = []
    seen_titles = set()
    excluded = {"currency_mismatch": 0, "duplicate_title": 0}
    for row in rows:
        title = row["title"].strip()
        if row["currency"] != currency:
            excluded["currency_mismatch"] += 1
            continue
        if title.lower() in seen_titles:
            excluded["duplicate_title"] += 1
            continue
        seen_titles.add(title.lower())
        options.append({
            "poi_id": row["poi_id"],
            "title": title,
            "unit_price": to_money(row["cost"]),
            "currency": row["currency"],
            "duration_minutes": row["duration_minutes"],
            "times_planned": row["times_planned"],
        })
    return {"options": options, "found": len(rows), "excluded": excluded}


def search_activities_via_backend(client, session_id: str, city_id: str, currency: str) -> Dict[str, Any]:
    """Retrieve authoritative POIs for the city via the backend's HTTP catalog endpoint."""
    try:
        rows = client.catalog_activities(session_id, city_id=city_id, currency=currency)
    except Exception:
        return {"options": [], "found": 0, "excluded": {}}

    options: List[Dict[str, Any]] = []
    seen_titles = set()
    excluded = {"currency_mismatch": 0, "duplicate_title": 0}
    for row in rows:
        title = row["title"].strip()
        if row.get("currency") and row["currency"] != currency:
            excluded["currency_mismatch"] += 1
            continue
        if title.lower() in seen_titles:
            excluded["duplicate_title"] += 1
            continue
        seen_titles.add(title.lower())
        options.append({
            "poi_id": row["poi_id"],
            "title": title,
            "unit_price": to_money(row["cost"]),
            "currency": row["currency"],
            "duration_minutes": row.get("duration_minutes"),
            "times_planned": row.get("times_planned", 0),
            "latitude": row.get("city_lat"),
            "longitude": row.get("city_lng"),
        })
    return {"options": options, "found": len(rows), "excluded": excluded}



def select_activities(options: List[Dict[str, Any]], strategy_level: int, max_count: int) -> List[Dict[str, Any]]:
    """Most popular activities; replan level 2 keeps free ones only; level 3 drops them."""
    if strategy_level >= 3 or max_count < 1:
        return []
    if strategy_level >= 2:
        options = [o for o in options if o["unit_price"] == 0]
    return options[:max_count]
