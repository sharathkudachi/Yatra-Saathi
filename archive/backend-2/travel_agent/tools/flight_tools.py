# travel_agent/tools/flight_tools.py
"""Flight search over flights → flight_fares → inventory_calendar (read-only).

A fare is offered only when it has an inventory_calendar row on the travel date,
enough free seats (total - booked - held) and the trip's currency. The dated
inventory price is the per-seat price.
"""
from typing import Any, Dict, List, Optional

from travel_agent.tools.budget_tools import to_money
from travel_agent.tools.db import query_db

_FLIGHT_SQL = """
SELECT f.fare_id, f.cabin_class, f.fare_class, f.refundable, f.baggage_kg,
       fl.flight_id, fl.flight_number, fl.departs_at, fl.arrives_at,
       fl.duration_minutes, fl.stops,
       al.name AS airline, oa.iata AS origin_iata, da.iata AS destination_iata,
       i.inventory_id, i.for_date, i.price, i.currency,
       (i.total_units - i.booked_units - i.held_units) AS seats_available
FROM inventory_calendar i
JOIN flight_fares f ON i.entity_type = 'flight_fare' AND f.fare_id = i.entity_id
JOIN flights fl     ON fl.flight_id = f.flight_id
JOIN airlines al    ON al.airline_id = fl.airline_id
JOIN airports oa    ON oa.airport_id = fl.origin_airport_id
JOIN airports da    ON da.airport_id = fl.dest_airport_id
WHERE oa.city_id = ? AND da.city_id = ? AND i.for_date = ?
  AND f.status = 'active' AND fl.status = 'active'
"""


def search_flights(origin_city_id: str, destination_city_id: str, travel_date: str,
                   seats: int, currency: str) -> Dict[str, Any]:
    """Return bookable fares for one leg, cheapest first, plus counts of what was excluded."""
    rows = query_db(_FLIGHT_SQL, (origin_city_id, destination_city_id, travel_date))
    options: List[Dict[str, Any]] = []
    excluded = {"currency_mismatch": 0, "insufficient_seats": 0}
    for row in rows:
        if row["currency"] != currency:
            excluded["currency_mismatch"] += 1
            continue
        if row["seats_available"] < seats:
            excluded["insufficient_seats"] += 1
            continue
        options.append({
            "fare_id": row["fare_id"],
            "inventory_id": row["inventory_id"],
            "flight_id": row["flight_id"],
            "flight_number": row["flight_number"],
            "airline": row["airline"],
            "origin_iata": row["origin_iata"],
            "destination_iata": row["destination_iata"],
            "departs_at": row["departs_at"],
            "arrives_at": row["arrives_at"],
            "duration_minutes": row["duration_minutes"],
            "stops": row["stops"],
            "cabin_class": row["cabin_class"],
            "fare_class": row["fare_class"],
            "refundable": bool(row["refundable"]),
            "for_date": row["for_date"],
            "unit_price": to_money(row["price"]),
            "currency": row["currency"],
            "seats_available": row["seats_available"],
        })
    options.sort(key=lambda o: (o["unit_price"], o["departs_at"]))
    return {"options": options, "found": len(rows), "excluded": excluded}


def select_flight(options: List[Dict[str, Any]], strategy_level: int) -> Optional[Dict[str, Any]]:
    """Cheapest economy fare; from the most aggressive replan level, cheapest in any cabin."""
    if not options:
        return None
    if strategy_level < 3:
        economy = [o for o in options if o["cabin_class"] == "economy"]
        if economy:
            return min(economy, key=lambda o: o["unit_price"])
    return min(options, key=lambda o: o["unit_price"])
