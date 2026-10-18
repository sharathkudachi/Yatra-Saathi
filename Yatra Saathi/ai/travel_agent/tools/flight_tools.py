# travel_agent/tools/flight_tools.py
"""Flight search over flights → flight_fares → inventory_calendar (read-only).

A fare is offered only when it has an inventory_calendar row on the travel date,
enough free seats (total - booked - held) and the trip's currency. The dated
inventory price is the per-seat price. Flights are compared as instants (their
timestamps carry an offset): one that has already left, or whose arrival is not
after its departure, is excluded -- one that lands after local midnight is not.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from travel_agent.tools.budget_tools import to_money
from travel_agent.tools.db import query_db
from travel_agent.tools.fx_tools import Rates, can_convert, convert

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


def time_problem(departs_at: str, arrives_at: str, now: Optional[str]) -> Optional[str]:
    """Why a flight can't be offered on timing grounds ("departed" / "bad_times"), or None."""
    try:
        departs, arrives = datetime.fromisoformat(str(departs_at)), datetime.fromisoformat(str(arrives_at))
        if arrives <= departs:
            return "bad_times"
        if now and departs <= datetime.fromisoformat(now):
            return "departed"
    except (TypeError, ValueError):
        return "bad_times"
    return None


def search_flights(origin_city_id: str, destination_city_id: str, travel_date: str,
                   seats: int, currency: str, now: Optional[str] = None) -> Dict[str, Any]:
    """Return bookable fares for one leg, cheapest first, plus counts of what was excluded."""
    rows = query_db(_FLIGHT_SQL, (origin_city_id, destination_city_id, travel_date))
    options: List[Dict[str, Any]] = []
    excluded = {"currency_mismatch": 0, "insufficient_seats": 0, "departed": 0, "bad_times": 0}
    for row in rows:
        problem = time_problem(row["departs_at"], row["arrives_at"], now)
        if problem:
            excluded[problem] += 1
            continue
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


def search_flights_via_backend(client, session_id: str, origin_city_id: str, destination_city_id: str,
                               travel_date: str, seats: int, currency: str, rates: Rates = None,
                               now: Optional[str] = None) -> Dict[str, Any]:
    """Same shape as `search_flights`, but through the backend's catalog routes
    instead of a local database -- no SQLite access from the agent process. Fares in
    another currency are converted into the trip currency when `rates` are known."""
    origin_airports = client.catalog_airports(session_id, city_id=origin_city_id)
    dest_airports = client.catalog_airports(session_id, city_id=destination_city_id)
    options: List[Dict[str, Any]] = []
    excluded = {"currency_mismatch": 0, "insufficient_seats": 0, "departed": 0, "bad_times": 0}
    found = 0
    for oa in origin_airports:
        for da in dest_airports:
            flights = client.catalog_flights(session_id, origin_airport_id=oa["airport_id"],
                                             dest_airport_id=da["airport_id"], depart_date=travel_date)
            for flight in flights:
                problem = time_problem(flight["departs_at"], flight["arrives_at"], now)
                if problem:
                    excluded[problem] += 1
                    continue
                for fare in client.catalog_fares(session_id, flight["flight_id"]):
                    inventory = client.catalog_inventory(session_id, "flight_fare", fare["fare_id"],
                                                         start_date=travel_date, end_date=travel_date)
                    if not inventory:
                        continue
                    row = inventory[0]
                    found += 1
                    seats_available = row["total_units"] - row["booked_units"] - row["held_units"]
                    if not can_convert(rates, row["currency"], currency):
                        excluded["currency_mismatch"] += 1
                        continue
                    if seats_available < seats:
                        excluded["insufficient_seats"] += 1
                        continue
                    options.append({
                        "fare_id": fare["fare_id"], "inventory_id": row["inventory_id"],
                        "flight_id": flight["flight_id"], "flight_number": flight["flight_number"],
                        "airline": flight.get("airline_name") or flight["airline_id"],
                        "origin_iata": flight.get("origin_iata_code") or flight["origin_airport_id"],
                        "destination_iata": flight.get("dest_iata_code") or flight["dest_airport_id"],
                        "departs_at": flight["departs_at"],
                        "arrives_at": flight["arrives_at"], "duration_minutes": flight["duration_minutes"],
                        "stops": flight["stops"], "cabin_class": fare["cabin_class"],
                        "fare_class": fare["fare_class"], "refundable": bool(fare["refundable"]),
                        "for_date": row["for_date"],
                        "unit_price": convert(to_money(row["price"]), row["currency"], currency, rates),
                        "currency": currency, "seats_available": seats_available,
                    })
    options.sort(key=lambda o: (o["unit_price"], o["departs_at"]))
    return {"options": options, "found": found, "excluded": excluded}


def flight_offer(fare: Dict[str, Any], seats: int) -> Dict[str, Any]:
    """Shapes a selected fare as an offer for `POST /tool-calls/{id}/results`."""
    return {"kind": "flight", "entity_type": "flight_fare", "entity_id": fare["fare_id"],
            "items": [{"inventory_id": fare["inventory_id"], "units": seats}]}


def select_flight(options: List[Dict[str, Any]], strategy_level: int) -> Optional[Dict[str, Any]]:
    """Cheapest economy fare; from the most aggressive replan level, cheapest in any cabin."""
    if not options:
        return None
    if strategy_level < 3:
        economy = [o for o in options if o["cabin_class"] == "economy"]
        if economy:
            return min(economy, key=lambda o: o["unit_price"])
    return min(options, key=lambda o: o["unit_price"])



_ROUTE_DATES_SQL = """
SELECT DISTINCT substr(fl.departs_at, 1, 10) AS day
FROM flights fl
JOIN airports oa ON oa.airport_id = fl.origin_airport_id
JOIN airports da ON da.airport_id = fl.dest_airport_id
JOIN flight_fares f ON f.flight_id = fl.flight_id AND f.status = 'active'
JOIN inventory_calendar i ON i.entity_type = 'flight_fare' AND i.entity_id = f.fare_id
                         AND i.for_date = substr(fl.departs_at, 1, 10)
WHERE fl.status = 'active' AND oa.city_id = ? AND da.city_id = ?
  AND i.currency = ? AND (i.total_units - i.booked_units - i.held_units) >= ?
"""


def nearby_flight_dates(client, session_id: Optional[str], origin_city_id: str, destination_city_id: str,
                        around: str, today: str, seats: int, currency: str, limit: int = 3,
                        rates: Rates = None, not_before: Optional[str] = None) -> List[str]:
    """Find bookable route dates, prioritizing the next scheduled dates.

    not_before constrains suggestions to dates on or after a required lower
    bound; for a return leg this keeps every suggestion after the outbound date.
    """
    from datetime import date as _date
    target = _date.fromisoformat(around)
    earliest = _date.fromisoformat(not_before) if not_before else None

    def suggestion_order(day: str):
        parsed = _date.fromisoformat(day)
        return (parsed < target, abs((parsed - target).days), parsed)

    def eligible(day: str) -> bool:
        parsed = _date.fromisoformat(day)
        return parsed.isoformat() >= today and parsed != target and (earliest is None or parsed >= earliest)

    if client is None:
        days = {r["day"] for r in query_db(_ROUTE_DATES_SQL, (origin_city_id, destination_city_id,
                                                               currency, seats))}
        candidates = [d for d in days if eligible(d)]
        return sorted(candidates, key=suggestion_order)[:limit]

    flights = [f for oa in client.catalog_airports(session_id, city_id=origin_city_id)
               for da in client.catalog_airports(session_id, city_id=destination_city_id)
               for f in client.catalog_flights(session_id, origin_airport_id=oa["airport_id"],
                                               dest_airport_id=da["airport_id"])]
    found: List[str] = []
    for flight in sorted(flights, key=lambda f: suggestion_order(f["departs_at"][:10])):
        day = flight["departs_at"][:10]
        if not eligible(day) or day in found:
            continue
        for fare in client.catalog_fares(session_id, flight["flight_id"]):
            rows = client.catalog_inventory(session_id, "flight_fare", fare["fare_id"], start_date=day, end_date=day)
            if any(can_convert(rates, r["currency"], currency)
                   and r["total_units"] - r["booked_units"] - r["held_units"] >= seats
                   for r in rows):
                found.append(day)
                break
        if len(found) == limit:
            break
    return found
