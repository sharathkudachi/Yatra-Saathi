"""Read-only catalog queries over existing tables. Plain reads, no ranking (section 12)."""
from __future__ import annotations

import sqlite3
from typing import Any, Optional


def _rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


# The agent loads the whole city list once to resolve names, so the cap must cover the
# full reference table (60 cities today); a 50 cap silently hid every international city.
def list_cities(conn: sqlite3.Connection, *, name_like: Optional[str] = None, limit: int = 1000) -> list[dict]:
    if name_like:
        cur = conn.execute("SELECT * FROM cities WHERE name LIKE ? LIMIT ?", (f"%{name_like}%", limit))
    else:
        cur = conn.execute("SELECT * FROM cities LIMIT ?", (limit,))
    return _rows(cur)


def list_airports(conn: sqlite3.Connection, *, city_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    if city_id:
        cur = conn.execute("SELECT * FROM airports WHERE city_id = ? LIMIT ?", (city_id, limit))
    else:
        cur = conn.execute("SELECT * FROM airports LIMIT ?", (limit,))
    return _rows(cur)


def search_flights(conn: sqlite3.Connection, *, origin_airport_id: Optional[str] = None,
                    dest_airport_id: Optional[str] = None, depart_date: Optional[str] = None,
                    limit: int = 50) -> list[dict]:
    clauses, params = [], []
    if origin_airport_id:
        clauses.append("f.origin_airport_id = ?")
        params.append(origin_airport_id)
    if dest_airport_id:
        clauses.append("f.dest_airport_id = ?")
        params.append(dest_airport_id)
    if depart_date:
        # departs_at carries a local offset (+05:30); SQLite's date() would convert it to UTC and
        # file early-morning departures under the previous day. Compare the local date instead.
        clauses.append("substr(f.departs_at, 1, 10) = ?")
        params.append(depart_date)
    clauses.append("f.status = 'active'")
    where = " AND ".join(clauses) if clauses else "1=1"
    params.append(limit)
    # Display names/codes ride along (additive columns) so the agent can describe flights.
    cur = conn.execute(
        f"""SELECT f.*, a.name AS airline_name, a.iata AS airline_iata,
                   ao.iata AS origin_iata_code, ad.iata AS dest_iata_code
            FROM flights f LEFT JOIN airlines a ON a.airline_id = f.airline_id
            LEFT JOIN airports ao ON ao.airport_id = f.origin_airport_id
            LEFT JOIN airports ad ON ad.airport_id = f.dest_airport_id
            WHERE {where} ORDER BY f.departs_at LIMIT ?""", params)
    return _rows(cur)


def get_flight(conn: sqlite3.Connection, flight_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM flights WHERE flight_id = ?", (flight_id,)).fetchone()
    return dict(row) if row else None


def list_fares_for_flight(conn: sqlite3.Connection, flight_id: str, *, limit: int = 50) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM flight_fares WHERE flight_id = ? AND status = 'active' LIMIT ?",
        (flight_id, limit),
    )
    return _rows(cur)


def get_fare(conn: sqlite3.Connection, fare_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM flight_fares WHERE fare_id = ?", (fare_id,)).fetchone()
    return dict(row) if row else None


def search_hotels(conn: sqlite3.Connection, *, city_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    if city_id:
        cur = conn.execute(
            "SELECT * FROM hotels WHERE city_id = ? AND status = 'active' LIMIT ?", (city_id, limit)
        )
    else:
        cur = conn.execute("SELECT * FROM hotels WHERE status = 'active' LIMIT ?", (limit,))
    return _rows(cur)


def get_hotel(conn: sqlite3.Connection, hotel_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM hotels WHERE hotel_id = ?", (hotel_id,)).fetchone()
    return dict(row) if row else None


def list_room_types_for_hotel(conn: sqlite3.Connection, hotel_id: str, *, limit: int = 50) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM hotel_room_types WHERE hotel_id = ? AND status = 'active' LIMIT ?",
        (hotel_id, limit),
    )
    return _rows(cur)


def get_room_type(conn: sqlite3.Connection, room_type_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM hotel_room_types WHERE room_type_id = ?", (room_type_id,)).fetchone()
    return dict(row) if row else None


def flight_for_fare(conn: sqlite3.Connection, fare_id: str) -> Optional[dict]:
    row = conn.execute(
        """SELECT f.flight_id, f.flight_number, f.departs_at, f.arrives_at FROM flight_fares ff
           JOIN flights f ON f.flight_id = ff.flight_id WHERE ff.fare_id = ?""", (fare_id,)).fetchone()
    return dict(row) if row else None


def get_inventory_row(conn: sqlite3.Connection, inventory_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM inventory_calendar WHERE inventory_id = ?", (inventory_id,)).fetchone()
    return dict(row) if row else None


def get_inventory_for_entity_date(conn: sqlite3.Connection, entity_type: str, entity_id: str,
                                   for_date: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM inventory_calendar WHERE entity_type = ? AND entity_id = ? AND for_date = ?",
        (entity_type, entity_id, for_date),
    ).fetchone()
    return dict(row) if row else None


def list_inventory_for_entity(conn: sqlite3.Connection, entity_type: str, entity_id: str,
                               *, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list[dict]:
    clauses = ["entity_type = ?", "entity_id = ?"]
    params: list[Any] = [entity_type, entity_id]
    if start_date:
        clauses.append("for_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("for_date <= ?")
        params.append(end_date)
    cur = conn.execute(
        f"SELECT * FROM inventory_calendar WHERE {' AND '.join(clauses)} ORDER BY for_date", params
    )
    return _rows(cur)


def get_currency(conn: sqlite3.Connection, iso4217: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM currencies WHERE iso4217 = ?", (iso4217,)).fetchone()
    return dict(row) if row else None


def find_city_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM cities WHERE lower(name) = lower(?) LIMIT 1", (name.strip(),)).fetchone()
    return dict(row) if row else None


def flight_fare_offers(conn: sqlite3.Connection, *, origin_city_id: str, dest_city_id: str,
                       depart_date: str, cabin_class: str) -> list[dict]:
    """Every active fare in `cabin_class` on a flight between the two cities on the local
    `depart_date`, joined with its inventory row and display names (human flight search)."""
    cur = conn.execute(
        """SELECT f.flight_id, f.flight_number, f.departs_at, f.arrives_at, f.duration_minutes,
                  f.stops, f.carbon_kg, a.name AS airline_name, a.iata AS airline_code,
                  ao.name AS origin_airport, ao.iata AS origin_code, co.name AS origin_city,
                  ao.timezone AS origin_tz, ao.lat AS origin_lat, ao.lng AS origin_lng,
                  ad.name AS dest_airport, ad.iata AS dest_code, cd.name AS dest_city,
                  ad.timezone AS dest_tz, ad.lat AS dest_lat, ad.lng AS dest_lng,
                  ff.fare_id, ff.cabin_class, ff.fare_class, ff.baggage_kg, ff.refundable, ff.changeable,
                  ic.inventory_id, ic.price, ic.currency,
                  (ic.total_units - ic.booked_units - ic.held_units) AS available
           FROM flights f
           JOIN airlines a ON a.airline_id = f.airline_id
           JOIN airports ao ON ao.airport_id = f.origin_airport_id
           JOIN cities co ON co.city_id = ao.city_id
           JOIN airports ad ON ad.airport_id = f.dest_airport_id
           JOIN cities cd ON cd.city_id = ad.city_id
           JOIN flight_fares ff ON ff.flight_id = f.flight_id AND ff.status = 'active'
           JOIN inventory_calendar ic ON ic.entity_type = 'flight_fare' AND ic.entity_id = ff.fare_id
                                     AND ic.for_date = substr(f.departs_at, 1, 10)
           WHERE f.status = 'active' AND ao.city_id = ? AND ad.city_id = ?
             AND substr(f.departs_at, 1, 10) = ? AND ff.cabin_class = ?
           ORDER BY f.departs_at""",
        (origin_city_id, dest_city_id, depart_date, cabin_class),
    )
    return _rows(cur)


def flight_dates_between(conn: sqlite3.Connection, *, origin_city_id: str, dest_city_id: str,
                         cabin_class: str, min_seats: int, near_date: str, from_date: str,
                         limit: int = 5) -> list[str]:
    """Local departure dates (on or after `from_date`) with a bookable fare between two
    cities, nearest to `near_date`."""
    cur = conn.execute(
        """SELECT DISTINCT substr(f.departs_at, 1, 10) AS d
           FROM flights f
           JOIN airports ao ON ao.airport_id = f.origin_airport_id
           JOIN airports ad ON ad.airport_id = f.dest_airport_id
           JOIN flight_fares ff ON ff.flight_id = f.flight_id AND ff.status = 'active'
           JOIN inventory_calendar ic ON ic.entity_type = 'flight_fare' AND ic.entity_id = ff.fare_id
           WHERE f.status = 'active' AND ao.city_id = ? AND ad.city_id = ? AND ff.cabin_class = ?
             AND (ic.total_units - ic.booked_units - ic.held_units) >= ?
             AND substr(f.departs_at, 1, 10) >= ?
           ORDER BY abs(julianday(d) - julianday(?)), d LIMIT ?""",
        (origin_city_id, dest_city_id, cabin_class, min_seats, from_date, near_date, limit),
    )
    return sorted(r["d"] for r in cur.fetchall())


def room_night_offers(conn: sqlite3.Connection, *, city_id: str, start_date: str, end_date: str,
                      min_occupancy: int) -> list[dict]:
    """Inventory rows for every active room type in the city that sleeps `min_occupancy`, for
    nights start_date..end_date inclusive, joined with hotel details (human hotel search)."""
    cur = conn.execute(
        """SELECT h.hotel_id, h.name AS hotel_name, h.description, h.property_type, h.star_rating,
                  h.lat, h.lng, h.address_line,
                  r.room_type_id, r.name AS room_name, r.max_occupancy,
                  ic.inventory_id, ic.for_date, ic.price, ic.currency, ic.min_stay_nights,
                  ic.closed_to_arrival, (ic.total_units - ic.booked_units - ic.held_units) AS available
           FROM hotels h
           JOIN hotel_room_types r ON r.hotel_id = h.hotel_id AND r.status = 'active'
           JOIN inventory_calendar ic ON ic.entity_type = 'room_type' AND ic.entity_id = r.room_type_id
           WHERE h.status = 'active' AND h.city_id = ? AND r.max_occupancy >= ?
             AND ic.for_date >= ? AND ic.for_date <= ?
           ORDER BY r.room_type_id, ic.for_date""",
        (city_id, min_occupancy, start_date, end_date),
    )
    return _rows(cur)


def item_details(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> Optional[dict]:
    """Read-only schedule/stay facts for a cart entity, for the human itinerary view."""
    if entity_type == "flight_fare":
        row = conn.execute(
            """SELECT a.name AS airline, f.flight_number, ff.cabin_class, f.departs_at, f.arrives_at,
                      f.duration_minutes, f.stops, ao.iata AS origin_code, co.name AS origin_city,
                      ao.lat AS origin_lat, ao.lng AS origin_lng,
                      ad.iata AS destination_code, cd.name AS destination_city,
                      ad.lat AS dest_lat, ad.lng AS dest_lng
               FROM flight_fares ff JOIN flights f ON f.flight_id = ff.flight_id
               JOIN airlines a ON a.airline_id = f.airline_id
               JOIN airports ao ON ao.airport_id = f.origin_airport_id JOIN cities co ON co.city_id = ao.city_id
               JOIN airports ad ON ad.airport_id = f.dest_airport_id JOIN cities cd ON cd.city_id = ad.city_id
               WHERE ff.fare_id = ?""", (entity_id,)).fetchone()
        return {"type": "flight", **dict(row)} if row else None
    if entity_type == "room_type":
        row = conn.execute(
            """SELECT h.name AS hotel, r.name AS room, c.name AS city, h.address_line AS address,
                      h.lat AS latitude, h.lng AS longitude,
                      h.checkin_time, h.checkout_time
               FROM hotel_room_types r JOIN hotels h ON h.hotel_id = r.hotel_id
               JOIN cities c ON c.city_id = h.city_id WHERE r.room_type_id = ?""", (entity_id,)).fetchone()
        return {"type": "stay", **dict(row)} if row else None
    return None


def display_title(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> Optional[str]:
    """Human-readable label for a cart entity (read-only; for the human cart view)."""
    if entity_type == "room_type":
        row = conn.execute(
            """SELECT h.name AS hotel, r.name AS room FROM hotel_room_types r
               JOIN hotels h ON h.hotel_id = r.hotel_id WHERE r.room_type_id = ?""", (entity_id,),
        ).fetchone()
        return f"{row['hotel']} · {row['room']}" if row else None
    if entity_type == "flight_fare":
        row = conn.execute(
            """SELECT a.name AS airline, a.iata AS iata, f.flight_number AS number, ff.cabin_class AS cabin
               FROM flight_fares ff JOIN flights f ON f.flight_id = ff.flight_id
               JOIN airlines a ON a.airline_id = f.airline_id WHERE ff.fare_id = ?""", (entity_id,),
        ).fetchone()
        return f"{row['airline']} {row['number']} · {row['cabin']}" if row else None
    return None


def list_activities(
    conn: sqlite3.Connection,
    *,
    city_id: Optional[str] = None,
    city_name: Optional[str] = None,
    currency: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Authoritative POIs from historical reference itineraries in the working database."""
    clauses = ["it.entity_type = 'poi'", "it.status <> 'removed'"]
    params: list[Any] = []

    if city_id:
        clauses.append("t.destination_city_id = ?")
        params.append(city_id)
    elif city_name:
        clauses.append("lower(c.name) = lower(?)")
        params.append(city_name.strip())

    if currency:
        clauses.append("it.currency = ?")
        params.append(currency)

    where = " AND ".join(clauses)
    params.append(limit)

    cur = conn.execute(
        f"""SELECT it.entity_id AS poi_id, it.title, it.cost, it.currency,
                   MAX(it.duration_minutes) AS duration_minutes,
                   c.city_id, c.name AS city_name,
                   c.lat AS city_lat, c.lng AS city_lng,
                   COUNT(*) AS times_planned
            FROM itinerary_items it
            JOIN itineraries iti ON iti.itinerary_id = it.itinerary_id
            JOIN trips t ON t.trip_id = iti.trip_id
            JOIN cities c ON c.city_id = t.destination_city_id
            WHERE {where}
            GROUP BY it.entity_id, it.title, it.cost, it.currency, c.city_id, c.name
            ORDER BY times_planned DESC, it.title
            LIMIT ?""",
        params,
    )
    return _rows(cur)


def get_activity(conn: sqlite3.Connection, poi_id: str) -> Optional[dict]:
    """Retrieve an authoritative POI by its stable ID."""
    row = conn.execute(
        """SELECT it.entity_id AS poi_id, it.title, it.cost, it.currency,
                  MAX(it.duration_minutes) AS duration_minutes,
                  c.city_id, c.name AS city_name,
                  c.lat AS city_lat, c.lng AS city_lng
           FROM itinerary_items it
           JOIN itineraries iti ON iti.itinerary_id = it.itinerary_id
           JOIN trips t ON t.trip_id = iti.trip_id
           JOIN cities c ON c.city_id = t.destination_city_id
           WHERE it.entity_type = 'poi' AND it.entity_id = ?
           GROUP BY it.entity_id, it.title, it.cost, it.currency, c.city_id, c.name
           LIMIT 1""",
        (poi_id,),
    ).fetchone()
    return dict(row) if row else None

