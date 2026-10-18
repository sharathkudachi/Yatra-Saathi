"""Read-only flight and hotel search for the human UI (the Flights and stays panels).

Shapes match the frontend's `FlightOption` / `HotelOption` types (camelCase). Search never
holds, prices a cart or books anything: the agent + confirmation gate remain the only way to
book. Prices use the same rules as the cart (flight = seat fare x passengers; stay = sum of
nightly rates for one room), before tax, converted per unit into the requested currency at the
demo rates (src/core/fx.py) exactly as the cart would; `localPrice`/`localCurrency` keep the
catalog's own figure.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import groupby
from typing import Optional

from src.core import dates, fx, money
from src.db.repositories import catalog as catalog_repo

MAX_NIGHTS = 30
MAX_RESULTS = 20
# Everyday names that differ from the dataset's city names (same aliases the frontend uses).
CITY_ALIASES = {"goa": "Panaji", "delhi": "New Delhi"}


def _unit_minor(price: str, src: str, dst: Optional[str]) -> int:
    """One night / one seat in the display currency (the catalog's own when none is asked)."""
    if not dst or not fx.supported(dst) or not fx.supported(src):
        return money.to_minor(price)
    return fx.convert_to_minor(price, src, dst)


def _shown(src: str, dst: Optional[str]) -> str:
    return dst if dst and fx.supported(dst) and fx.supported(src) else src


def _resolve_city(conn, name: str) -> Optional[dict]:
    key = name.strip()
    return catalog_repo.find_city_by_name(conn, CITY_ALIASES.get(key.lower(), key))


def search_flights(conn, *, origin_city: str, destination_city: str, departure_date: date,
                   passengers: int, cabin_class: str, currency: Optional[str],
                   now: Optional[datetime] = None) -> list[dict]:
    """Bookable fares on the local departure date. A flight that has already left (`now`) or
    whose arrival is not after its departure is skipped; one landing after local midnight is not."""
    origin, dest = _resolve_city(conn, origin_city), _resolve_city(conn, destination_city)
    if origin is None or dest is None or origin["city_id"] == dest["city_id"]:
        return []
    rows = catalog_repo.flight_fare_offers(
        conn, origin_city_id=origin["city_id"], dest_city_id=dest["city_id"],
        depart_date=departure_date.isoformat(), cabin_class=cabin_class)
    options = []
    for r in rows:
        if r["available"] < passengers:
            continue
        times = dates.flight_times(r["departs_at"], r["arrives_at"], r["origin_tz"], r["dest_tz"])
        if not times["arrivesAfterDeparture"] or (now is not None and dates.has_departed(r["departs_at"], now)):
            continue
        total_minor = money.line_total_minor(passengers, _unit_minor(r["price"], r["currency"], currency))
        local_minor = money.line_total_minor(passengers, money.to_minor(r["price"]))
        options.append({
            "flightId": r["flight_id"], "fareId": r["fare_id"], "inventoryId": r["inventory_id"],
            "airlineName": r["airline_name"], "airlineCode": r["airline_code"],
            "flightNumber": r["flight_number"],
            "originCity": r["origin_city"], "originAirport": r["origin_airport"], "originCode": r["origin_code"],
            "originLatitude": float(r["origin_lat"]) if r.get("origin_lat") is not None else None,
            "originLongitude": float(r["origin_lng"]) if r.get("origin_lng") is not None else None,
            "destinationCity": r["dest_city"], "destinationAirport": r["dest_airport"],
            "destinationCode": r["dest_code"],
            "destLatitude": float(r["dest_lat"]) if r.get("dest_lat") is not None else None,
            "destLongitude": float(r["dest_lng"]) if r.get("dest_lng") is not None else None,
            "departsAt": r["departs_at"], "arrivesAt": r["arrives_at"],
            "departsAtLocal": times["departsAtLocal"], "arrivesAtLocal": times["arrivesAtLocal"],
            "arrivalDayOffset": times["arrivalDayOffset"],
            "originTimezone": r["origin_tz"], "destinationTimezone": r["dest_tz"],
            "durationMinutes": r["duration_minutes"], "stops": r["stops"],
            "cabinClass": r["cabin_class"], "fareClass": r["fare_class"],
            "price": money.format_minor(total_minor), "currency": _shown(r["currency"], currency),
            "localPrice": money.format_minor(local_minor), "localCurrency": r["currency"],
            "baggageKg": r["baggage_kg"], "seatsAvailable": r["available"],
            "refundable": bool(r["refundable"]), "changeable": bool(r["changeable"]),
            "carbonKg": f"{r['carbon_kg']:.1f}" if r["carbon_kg"] is not None else "",
            "_sort": (_shown(r["currency"], currency) != currency, total_minor),
        })
    options.sort(key=lambda o: o["_sort"])
    for o in options:
        del o["_sort"]
    return options[:MAX_RESULTS]


def other_flight_dates(conn, *, origin_city: str, destination_city: str, departure_date: date,
                       passengers: int, cabin_class: str, today: str) -> list[str]:
    """Nearest dates that do have a bookable flight on the route (the dataset is sparse)."""
    origin, dest = _resolve_city(conn, origin_city), _resolve_city(conn, destination_city)
    if origin is None or dest is None or origin["city_id"] == dest["city_id"]:
        return []
    dates = catalog_repo.flight_dates_between(
        conn, origin_city_id=origin["city_id"], dest_city_id=dest["city_id"], cabin_class=cabin_class,
        min_seats=passengers, near_date=departure_date.isoformat(), from_date=today)
    return [d for d in dates if d != departure_date.isoformat()]


def search_hotels(conn, *, destination: str, start_date: date, end_date: date, travellers: int,
                  currency: Optional[str], budget_minor: Optional[int]) -> list[dict]:
    city = _resolve_city(conn, destination)
    nights = (end_date - start_date).days
    if city is None or not 1 <= nights <= MAX_NIGHTS:
        return []
    wanted = [(start_date + timedelta(days=i)).isoformat() for i in range(nights)]
    rows = catalog_repo.room_night_offers(
        conn, city_id=city["city_id"], start_date=wanted[0], end_date=wanted[-1],
        min_occupancy=travellers)
    options = []
    for _, group in groupby(rows, key=lambda r: r["room_type_id"]):
        by_date = {r["for_date"]: r for r in group}
        stay = [by_date.get(d) for d in wanted]
        # Bookable only if every night has a room, one currency, arrival allowed, min stay met.
        if any(r is None or r["available"] < 1 for r in stay):
            continue
        if len({r["currency"] for r in stay}) != 1 or stay[0]["closed_to_arrival"]:
            continue
        if any(r["min_stay_nights"] > nights for r in stay):
            continue
        first = stay[0]
        total_minor = sum(_unit_minor(r["price"], r["currency"], currency) for r in stay)
        local_minor = sum(money.to_minor(r["price"]) for r in stay)
        if budget_minor is not None and total_minor > budget_minor:
            continue
        options.append({
            "hotelId": first["hotel_id"], "roomTypeId": first["room_type_id"],
            "inventoryIds": [r["inventory_id"] for r in stay], "maxOccupancy": first["max_occupancy"],
            "name": first["hotel_name"], "city": city["name"], "country": city["country_code"],
            "description": first["description"] or "", "imageUrl": "",
            "roomName": first["room_name"],
            "price": money.format_minor(total_minor), "currency": _shown(first["currency"], currency),
            "localPrice": money.format_minor(local_minor), "localCurrency": first["currency"],
            "nights": nights, "availableUnits": min(r["available"] for r in stay),
            "latitude": float(first["lat"]) if first.get("lat") is not None else None,
            "longitude": float(first["lng"]) if first.get("lng") is not None else None,
            "address": first.get("address_line") or "",
            "tags": [t for t in ((first["property_type"] or "").replace("_", " "),
                                 f"{first['star_rating']} star" if first["star_rating"] else "") if t],
            "_sort": total_minor,
        })
    options.sort(key=lambda o: o["_sort"])
    for o in options:
        del o["_sort"]
    return options[:MAX_RESULTS]


def hotel_rooms(conn, *, hotel_id: str, start_date: date, end_date: date, travellers: int,
                currency: Optional[str] = None) -> Optional[dict]:
    """One hotel's details and *every* active room type for the stay, each priced per night and
    marked bookable or not (with the reason), so the stay page can show all rooms honestly."""
    hotel = catalog_repo.get_hotel(conn, hotel_id)
    if hotel is None or hotel["status"] != "active":
        return None
    city = conn.execute("SELECT name, country_code FROM cities WHERE city_id = ?", (hotel["city_id"],)).fetchone()
    nights = (end_date - start_date).days
    wanted = [(start_date + timedelta(days=i)).isoformat() for i in range(max(nights, 0))]
    rooms = []
    for room in catalog_repo.list_room_types_for_hotel(conn, hotel_id):
        rows = {r["for_date"]: {**r, "available": r["total_units"] - r["booked_units"] - r["held_units"]}
                for r in catalog_repo.list_inventory_for_entity(
            conn, "room_type", room["room_type_id"], start_date=wanted[0], end_date=wanted[-1])} if wanted else {}
        stay = [rows.get(d) for d in wanted]
        reason, code, detail = _unbookable_reason(stay, wanted, nights)
        priced = all(r is not None for r in stay) and len({r["currency"] for r in stay}) == 1 and stay
        rooms.append({
            "roomTypeId": room["room_type_id"], "name": room["name"],
            "bedConfig": (room["bed_config"] or "").replace("_", " "), "sizeSqm": room["size_sqm"],
            "maxOccupancy": room["max_occupancy"], "maxAdults": room["max_adults"],
            "maxChildren": room["max_children"], "smokingAllowed": bool(room["smoking_allowed"]),
            "fitsParty": room["max_occupancy"] >= travellers,
            "bookable": reason is None, "unavailableReason": reason,
            # Machine-readable form of the reason, so the UI can phrase it in any language.
            "unavailableCode": code, "unavailableDetail": detail,
            "availableUnits": min(r["available"] for r in stay) if priced else 0,
            "nightly": [{"date": d, "price": money.format_minor(_unit_minor(r["price"], r["currency"], currency))}
                        for d, r in zip(wanted, stay) if r],
            "price": money.format_minor(sum(_unit_minor(r["price"], r["currency"], currency) for r in stay))
            if priced else None,
            "currency": _shown(stay[0]["currency"] if priced else room["currency"], currency),
            "localPrice": money.format_minor(sum(money.to_minor(r["price"]) for r in stay)) if priced else None,
            "localCurrency": stay[0]["currency"] if priced else room["currency"],
            "inventoryIds": [r["inventory_id"] for r in stay] if priced else [],
            "_sort": (reason is not None, room["max_occupancy"] < travellers,
                      sum(_unit_minor(r["price"], r["currency"], currency) for r in stay) if priced else 0),
        })
    rooms.sort(key=lambda r: r["_sort"])
    for r in rooms:
        del r["_sort"]
    return {
        "hotel": {
            "hotelId": hotel["hotel_id"], "name": hotel["name"], "description": hotel["description"] or "",
            "city": city["name"] if city else "", "country": city["country_code"] if city else "",
            "propertyType": (hotel["property_type"] or "").replace("_", " "), "starRating": hotel["star_rating"],
            "guestScore": hotel["guest_score"], "reviewCount": hotel["review_count"],
            "address": hotel["address_line"] or "", "distanceToCentreKm": hotel["distance_to_centre_km"],
            "latitude": float(hotel["lat"]) if hotel.get("lat") is not None else None,
            "longitude": float(hotel["lng"]) if hotel.get("lng") is not None else None,
            "checkinTime": hotel["checkin_time"], "checkoutTime": hotel["checkout_time"],
            "hasXrScene": bool(hotel["has_xr_scene"]),
        },
        "startDate": start_date.isoformat(), "endDate": end_date.isoformat(), "nights": nights,
        "travellers": travellers, "rooms": rooms,
    }


def _unbookable_reason(stay: list, wanted: list[str], nights: int) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(English reason, code, detail) for a room that can't be booked, or (None, None, None)."""
    if not 1 <= nights <= MAX_NIGHTS:
        return f"Stays must be 1 to {MAX_NIGHTS} nights", "stay_length", str(MAX_NIGHTS)
    for day, row in zip(wanted, stay):
        if row is None:
            return f"Not offered on {day}", "not_offered", day
        if row["total_units"] - row["booked_units"] - row["held_units"] < 1:
            return f"Sold out on {day}", "sold_out", day
    if stay[0]["closed_to_arrival"]:
        return f"No check-in on {wanted[0]}", "no_checkin", wanted[0]
    min_stay = max(r["min_stay_nights"] for r in stay)
    if min_stay > nights:
        return f"Minimum stay is {min_stay} nights", "min_stay", str(min_stay)
    if len({r["currency"] for r in stay}) != 1:
        return "Priced in more than one currency", "mixed_currency", None
    return None, None, None
