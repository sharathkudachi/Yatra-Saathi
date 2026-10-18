"""POST /api/v1/search/flights, /search/hotels and /search/hotels/{hotel_id}/rooms.

Read-only catalog search for the human UI's Flights and stays panels. Public (no login),
like browsing a travel site; it never holds or books. Booking still only happens through an
agent session and the human confirmation gate.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import get_clock, get_conn
from src.contracts.envelope import ok
from src.core import fx, money
from src.core.clock import Clock
from src.core.dates import local_today, past_date_error
from src.contracts.codes import RefusalError
from src.schemas.human import FlightSearchRequest, HotelRoomsRequest, HotelSearchRequest
from src.services import search_service

router = APIRouter()


def _refuse_past(day, clock: Clock, label: str) -> None:
    error = past_date_error(day, local_today(clock), label=label)
    if error:
        raise RefusalError("DATE_IN_PAST", error, http_status=422)


@router.post("/search/flights")
def search_flights(body: FlightSearchRequest, conn: sqlite3.Connection = Depends(get_conn),
                   clock: Clock = Depends(get_clock)):
    _refuse_past(body.departureDate, clock, "departure date")
    flights = search_service.search_flights(
        conn, origin_city=body.originCity, destination_city=body.destinationCity,
        departure_date=body.departureDate, passengers=body.passengers,
        cabin_class=body.cabinClass, currency=body.currency, now=clock.now())
    other_dates = [] if flights else search_service.other_flight_dates(
        conn, origin_city=body.originCity, destination_city=body.destinationCity,
        departure_date=body.departureDate, passengers=body.passengers, cabin_class=body.cabinClass,
        today=local_today(clock).isoformat())
    return ok({"flights": flights, "otherDates": other_dates})


@router.post("/search/hotels")
def search_hotels(body: HotelSearchRequest, conn: sqlite3.Connection = Depends(get_conn),
                  clock: Clock = Depends(get_clock)):
    _refuse_past(body.startDate, clock, "check-in date")
    if not body.destination.strip() or body.startDate is None or body.endDate is None:
        return ok({"hotels": []})
    hotels = search_service.search_hotels(
        conn, destination=body.destination, start_date=body.startDate, end_date=body.endDate,
        travellers=body.travellers, currency=body.currency,
        budget_minor=money.to_minor(body.budget) if body.budget is not None else None)
    return ok({"hotels": hotels})


@router.post("/search/hotels/{hotel_id}/rooms")
def hotel_rooms(hotel_id: str, body: HotelRoomsRequest, conn: sqlite3.Connection = Depends(get_conn),
                clock: Clock = Depends(get_clock)):
    _refuse_past(body.startDate, clock, "check-in date")
    stay = search_service.hotel_rooms(conn, hotel_id=hotel_id, start_date=body.startDate,
                                      end_date=body.endDate, travellers=body.travellers, currency=body.currency)
    if stay is None:
        raise RefusalError("NOT_BOOKABLE", "hotel not found", http_status=404)
    return ok(stay)


@router.get("/currencies")
def currencies(conn: sqlite3.Connection = Depends(get_conn)):
    """Currencies a trip can be planned in, with the indicative demo rates used for conversion."""
    names = {r["iso4217"]: dict(r) for r in conn.execute("SELECT iso4217, name, symbol FROM currencies")}
    rows = [{"code": r["iso4217"], "name": names.get(r["iso4217"], {}).get("name", r["iso4217"]),
             "symbol": names.get(r["iso4217"], {}).get("symbol", ""), "inrPerUnit": r["inr_per_unit"]}
            for r in fx.rate_rows()]
    return ok({"currencies": rows, "ratesAsOf": fx.RATES_AS_OF, "ratesNote": "Indicative demo rates, not live"})


@router.get("/search/cities")
def search_cities(conn: sqlite3.Connection = Depends(get_conn)):
    """Reference cities with authoritative coordinates and metadata (read-only)."""
    rows = conn.execute(
        "SELECT city_id, name, state, country_code, lat, lng, timezone, region FROM cities WHERE status = 'active' ORDER BY name"
    ).fetchall()
    cities = [
        {
            "cityId": r["city_id"],
            "name": r["name"],
            "state": r["state"],
            "countryCode": r["country_code"],
            "latitude": float(r["lat"]) if r["lat"] is not None else None,
            "longitude": float(r["lng"]) if r["lng"] is not None else None,
            "timezone": r["timezone"],
            "region": r["region"],
        }
        for r in rows
    ]
    return ok({"cities": cities})

