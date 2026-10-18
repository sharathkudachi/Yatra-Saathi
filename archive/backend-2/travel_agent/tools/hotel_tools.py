# travel_agent/tools/hotel_tools.py
"""Hotel search over hotels → hotel_room_types → inventory_calendar (read-only).

A room type is offered only if every night of the stay has an inventory row with
enough free units, the check-in night is not closed to arrival, the stay meets
min_stay_nights, and every night is priced in the trip currency.
"""
import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from travel_agent.tools.budget_tools import to_money
from travel_agent.tools.db import query_db

_HOTEL_SQL = """
SELECT r.room_type_id, r.name AS room_name, r.max_adults,
       h.hotel_id, h.name AS hotel_name, h.star_rating, h.guest_score,
       h.distance_to_centre_km,
       i.inventory_id, i.for_date, i.price, i.currency, i.min_stay_nights,
       i.closed_to_arrival,
       (i.total_units - i.booked_units - i.held_units) AS units_available
FROM hotel_room_types r
JOIN hotels h ON h.hotel_id = r.hotel_id
JOIN inventory_calendar i ON i.entity_type = 'room_type' AND i.entity_id = r.room_type_id
WHERE h.city_id = ? AND i.for_date >= ? AND i.for_date < ?
  AND r.status = 'active' AND h.status = 'active'
ORDER BY r.room_type_id, i.for_date
"""


def _stay_dates(check_in: str, check_out: str) -> List[str]:
    start, end = date.fromisoformat(check_in), date.fromisoformat(check_out)
    return [(start + timedelta(days=n)).isoformat() for n in range((end - start).days)]


def search_hotels(city_id: str, check_in: str, check_out: str, travellers: int,
                  currency: str) -> Dict[str, Any]:
    """Return room types bookable for the whole stay, cheapest first."""
    nights = _stay_dates(check_in, check_out)
    if not nights:
        raise ValueError("check_out must be after check_in")
    rows = query_db(_HOTEL_SQL, (city_id, check_in, check_out))

    by_room: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_room.setdefault(row["room_type_id"], []).append(row)

    options: List[Dict[str, Any]] = []
    excluded = {"missing_nights": 0, "sold_out": 0, "closed_to_arrival": 0,
                "min_stay": 0, "currency_mismatch": 0}
    for room_type_id, night_rows in by_room.items():
        first = night_rows[0]
        rooms = math.ceil(travellers / max(first["max_adults"], 1))
        if [r["for_date"] for r in night_rows] != nights:
            excluded["missing_nights"] += 1
        elif any(r["currency"] != currency for r in night_rows):
            excluded["currency_mismatch"] += 1
        elif any(r["units_available"] < rooms for r in night_rows):
            excluded["sold_out"] += 1
        elif first["closed_to_arrival"]:
            excluded["closed_to_arrival"] += 1
        elif first["min_stay_nights"] > len(nights):
            excluded["min_stay"] += 1
        else:
            nightly = [{"inventory_id": r["inventory_id"], "for_date": r["for_date"],
                        "price": to_money(r["price"])} for r in night_rows]
            total = sum((n["price"] for n in nightly), Decimal("0.00")) * rooms
            options.append({
                "room_type_id": room_type_id,
                "room_name": first["room_name"],
                "hotel_id": first["hotel_id"],
                "hotel_name": first["hotel_name"].strip(),
                "star_rating": first["star_rating"],
                "guest_score": first["guest_score"],
                "distance_to_centre_km": first["distance_to_centre_km"],
                "rooms": rooms,
                "nights": len(nights),
                "nightly": nightly,
                "total_price": total,
                "currency": currency,
            })
    options.sort(key=lambda o: (o["total_price"], o["room_type_id"]))
    return {"options": options, "found": len(by_room), "excluded": excluded}


def select_hotel(options: List[Dict[str, Any]], strategy_level: int) -> Optional[Dict[str, Any]]:
    """Best guest score first; from replan level 1 onward, the cheapest stay."""
    if not options:
        return None
    if strategy_level >= 1:
        return min(options, key=lambda o: (o["total_price"], -(o["guest_score"] or 0)))
    return max(options, key=lambda o: (o["guest_score"] or 0, o["star_rating"], -o["total_price"]))
