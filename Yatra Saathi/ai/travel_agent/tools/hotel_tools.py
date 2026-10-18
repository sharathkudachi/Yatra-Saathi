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
from travel_agent.tools.fx_tools import Rates, can_convert, convert

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


def search_hotels_via_backend(client, session_id: str, city_id: str, check_in: str, check_out: str,
                              travellers: int, currency: str, rates: Rates = None) -> Dict[str, Any]:
    """Same shape as `search_hotels`, but through the backend's catalog routes
    instead of a local database -- no SQLite access from the agent process. Nightly
    prices in another currency are converted into the trip currency when `rates` are known."""
    nights = _stay_dates(check_in, check_out)
    if not nights:
        raise ValueError("check_out must be after check_in")

    hotels = client.catalog_hotels(session_id, city_id=city_id)
    options: List[Dict[str, Any]] = []
    excluded = {"missing_nights": 0, "sold_out": 0, "closed_to_arrival": 0,
                "min_stay": 0, "currency_mismatch": 0}
    found = 0
    for hotel in hotels:
        for room in client.catalog_room_types(session_id, hotel["hotel_id"]):
            # `catalog_inventory`'s end_date is inclusive; the stay's last night is
            # check_out minus one day (the check-out date itself is not a night).
            night_rows = client.catalog_inventory(session_id, "room_type", room["room_type_id"],
                                                  start_date=check_in, end_date=nights[-1])
            if not night_rows:
                continue
            found += 1
            rooms = math.ceil(travellers / max(room["max_adults"], 1))
            night_rows = sorted(night_rows, key=lambda r: r["for_date"])
            if [r["for_date"] for r in night_rows] != nights:
                excluded["missing_nights"] += 1
                continue
            if not all(can_convert(rates, r["currency"], currency) for r in night_rows):
                excluded["currency_mismatch"] += 1
                continue
            if any((r["total_units"] - r["booked_units"] - r["held_units"]) < rooms for r in night_rows):
                excluded["sold_out"] += 1
                continue
            first = night_rows[0]
            if first["closed_to_arrival"]:
                excluded["closed_to_arrival"] += 1
                continue
            if first["min_stay_nights"] > len(nights):
                excluded["min_stay"] += 1
                continue
            nightly = [{"inventory_id": r["inventory_id"], "for_date": r["for_date"],
                        "price": convert(to_money(r["price"]), r["currency"], currency, rates)}
                       for r in night_rows]
            total = sum((n["price"] for n in nightly), Decimal("0.00")) * rooms
            options.append({
                "room_type_id": room["room_type_id"], "room_name": room["name"],
                "hotel_id": hotel["hotel_id"], "hotel_name": hotel["name"].strip(),
                "star_rating": hotel["star_rating"], "guest_score": hotel["guest_score"],
                "distance_to_centre_km": hotel["distance_to_centre_km"], "rooms": rooms,
                "nights": len(nights), "nightly": nightly, "total_price": total, "currency": currency,
            })
    options.sort(key=lambda o: (o["total_price"], o["room_type_id"]))
    return {"options": options, "found": found, "excluded": excluded}


def hotel_offer(hotel: Dict[str, Any]) -> Dict[str, Any]:
    """Shapes a selected room stay as an offer for `POST /tool-calls/{id}/results`."""
    return {"kind": "hotel_stay", "entity_type": "room_type", "entity_id": hotel["room_type_id"],
            "items": [{"inventory_id": n["inventory_id"], "units": hotel["rooms"]}
                     for n in hotel["nightly"]]}


def select_hotel(options: List[Dict[str, Any]], strategy_level: int) -> Optional[Dict[str, Any]]:
    """Best guest score first; from replan level 1 onward, the cheapest stay."""
    if not options:
        return None
    if strategy_level >= 1:
        return min(options, key=lambda o: (o["total_price"], -(o["guest_score"] or 0)))
    return max(options, key=lambda o: (o["guest_score"] or 0, o["star_rating"], -o["total_price"]))
