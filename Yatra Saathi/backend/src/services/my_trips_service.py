"""The signed-in user's trips for the "My trips" page (read-only).

Two sources, both scoped to the user:
  * trips on their account in the dataset (`trips`, with budget, itinerary and bookings);
  * trips planned with Yatra (`agent_sessions`): destination and dates come from the cart
    (flights + hotel nights) once there is one, else from what the agent has understood so far
    (its saved requirements), else from the trip brief. Repeated attempts at the same trip
    collapse into the most recent one; sessions that never got a destination are left out.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from src.core import money
from src.db.repositories import bookings as bookings_repo
from src.db.repositories import carts as carts_repo
from src.db.repositories import catalog as catalog_repo

_RANK = {"confirmed": 3, "planning": 2, "draft": 1, "cancelled": 0}

# agent session status -> My-trips status
_SESSION_STATUS = {"completed": "confirmed", "awaiting_confirmation": "planning", "awaiting_input": "draft",
                   "executing": "planning", "planning": "draft", "paused": "draft"}


def _title(destination: str, start: str) -> str:
    try:
        return f"{destination} — {date.fromisoformat(start).strftime('%b %Y')}"
    except ValueError:
        return destination


def account_trips(conn, user_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT t.trip_id, t.title, t.start_date, t.end_date, t.party_size, t.adults, t.children, t.status,
                  t.home_currency, co.name AS origin, cd.name AS destination,
                  b.total_amount AS budget, b.currency AS budget_currency,
                  (SELECT i.total_cost FROM itineraries i WHERE i.trip_id = t.trip_id AND i.is_active = 1 LIMIT 1) AS itin_cost,
                  (SELECT i.currency FROM itineraries i WHERE i.trip_id = t.trip_id AND i.is_active = 1 LIMIT 1) AS itin_currency,
                  (SELECT COUNT(*) FROM itinerary_items ii JOIN itineraries i ON i.itinerary_id = ii.itinerary_id
                    WHERE i.trip_id = t.trip_id AND i.is_active = 1) AS itin_items,
                  (SELECT COUNT(*) FROM bookings bk WHERE bk.trip_id = t.trip_id) AS booking_count
           FROM trips t
           LEFT JOIN cities co ON co.city_id = t.origin_city_id
           LEFT JOIN cities cd ON cd.city_id = t.destination_city_id
           LEFT JOIN budgets b ON b.trip_id = t.trip_id
           WHERE t.owner_user_id = ?""", (user_id,)).fetchall()
    return [{
        "id": r["trip_id"], "source": "account", "sessionId": None, "bookingReference": None,
        "title": r["title"] or _title(r["destination"] or "", r["start_date"]),
        "origin": r["origin"] or "", "destination": r["destination"] or "",
        "startDate": r["start_date"], "endDate": r["end_date"], "partySize": r["party_size"],
        "adults": r["adults"], "children": r["children"], "status": r["status"],
        "currency": r["budget_currency"] or r["home_currency"], "budget": r["budget"] or "0.00",
        "itineraryCost": r["itin_cost"], "itineraryCurrency": r["itin_currency"],
        "itineraryItemCount": r["itin_items"], "bookingCount": r["booking_count"],
    } for r in rows]


def _cart_summary(conn, session_id: str) -> Optional[dict]:
    cart = carts_repo.get_active_cart(conn, session_id) or carts_repo.get_booked_cart(conn, session_id)
    if cart is None:
        return None
    items = carts_repo.list_active_items(conn, cart.cart_id)
    if not items:
        return None
    start, end, origin, destination = None, None, None, None
    for it in items:
        d = catalog_repo.item_details(conn, it.entity_type, it.entity_id) or {}
        last_day = it.for_date
        if d.get("type") == "stay":
            destination = d["city"]
            last_day = (date.fromisoformat(it.for_date) + timedelta(days=1)).isoformat()  # check-out
        elif d.get("type") == "flight" and origin is None:
            origin, destination = d["origin_city"], destination or d["destination_city"]
        start = min(start or it.for_date, it.for_date)
        end = max(end or last_day, last_day)
    return {"cart": cart, "items": len(items), "start": start, "end": end, "origin": origin, "destination": destination}


def yatra_trips(conn, user_id: str) -> list[dict]:
    sessions = conn.execute(
        """SELECT s.session_id, s.status, s.last_error_code, s.spend_cap, s.currency, s.constraints_json,
                  s.updated_at, st.state_json
           FROM agent_sessions s LEFT JOIN agent_session_state st ON st.session_id = s.session_id
           WHERE s.user_id = ? ORDER BY s.updated_at DESC""", (user_id,)).fetchall()
    candidates = []
    for s in sessions:
        constraints = json.loads(s["constraints_json"] or "{}")
        remembered = (json.loads(s["state_json"]).get("requirements") or {}) if s["state_json"] else {}
        known = {**{k: v for k, v in constraints.items() if v}, **{k: v for k, v in remembered.items() if v}}
        cart = _cart_summary(conn, s["session_id"])
        destination = (cart or {}).get("destination") or known.get("destination_name")
        start = (cart or {}).get("start") or known.get("start_date")
        end = (cart or {}).get("end") or known.get("end_date")
        if not destination or not start or not end:
            continue  # the conversation never got as far as a trip
        if s["status"] == "failed":
            if s["last_error_code"] != "confirmation_declined":
                continue
            status = "cancelled"
        else:
            status = _SESSION_STATUS.get(s["status"], "draft")
        booking = bookings_repo.get_by_session_confirmed(conn, s["session_id"]) if status == "confirmed" else None
        travellers = known.get("travellers") or 1
        candidates.append({
            "id": s["session_id"], "source": "yatra", "sessionId": s["session_id"],
            "bookingReference": booking["booking_reference"] if booking else None,
            "title": _title(destination, start),
            "origin": (cart or {}).get("origin") or known.get("origin_name") or "",
            "destination": destination, "startDate": start, "endDate": end,
            "partySize": travellers, "adults": travellers, "children": 0, "status": status,
            "currency": s["currency"], "budget": money.format_amount(s["spend_cap"]),
            "itineraryCost": money.format_minor(cart["cart"].total_minor) if cart else None,
            "itineraryCurrency": s["currency"] if cart else None,
            "itineraryItemCount": cart["items"] if cart else 0,
            "bookingCount": 1 if status == "confirmed" else 0,
        })
    # One entry per trip: repeated or refined attempts (same destination, overlapping dates)
    # collapse into the most advanced one -- booked, then awaiting approval, then draft --
    # and, among equals, the most recent (sessions are already newest first).
    trips: list[dict] = []
    for trip in sorted(candidates, key=lambda t: -_RANK[t["status"]]):
        if not any(t["destination"] == trip["destination"] and t["startDate"] <= trip["endDate"]
                   and trip["startDate"] <= t["endDate"] for t in trips):
            trips.append(trip)
    return trips


def phase5_trips(conn, user_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT b.booking_id, b.booking_reference, b.status, b.lifecycle_status, b.total_amount, b.currency,
                  b.created_at, b.itinerary_id, b.itinerary_version,
                  t.trip_id, t.title, t.start_date, t.end_date, t.party_size, t.adults, t.children,
                  co.name AS origin, cd.name AS destination
           FROM bookings b
           LEFT JOIN trips t ON t.trip_id = b.trip_id
           LEFT JOIN cities co ON co.city_id = t.origin_city_id
           LEFT JOIN cities cd ON cd.city_id = t.destination_city_id
           WHERE b.user_id = ?
           ORDER BY b.created_at DESC""",
        (user_id,),
    ).fetchall()
    res = []
    for r in rows:
        dest = r["destination"] or "Destination"
        start_d = r["start_date"] or r["created_at"][:10]
        end_d = r["end_date"] or r["created_at"][:10]
        res.append({
            "id": r["booking_id"],
            "source": "yatra",
            "sessionId": None,
            "bookingId": r["booking_id"],
            "bookingReference": r["booking_reference"],
            "title": r["title"] or f"{dest} — Demo Reservation",
            "origin": r["origin"] or "",
            "destination": dest,
            "startDate": start_d,
            "endDate": end_d,
            "partySize": r["party_size"] or 1,
            "adults": r["adults"] or 1,
            "children": r["children"] or 0,
            "status": r["status"],
            "currency": r["currency"],
            "budget": r["total_amount"],
            "itineraryCost": r["total_amount"],
            "itineraryCurrency": r["currency"],
            "itineraryItemCount": 1,
            "bookingCount": 1,
        })
    return res


def my_trips(conn, user_id: str) -> list[dict]:
    existing = yatra_trips(conn, user_id) + account_trips(conn, user_id)
    p5 = phase5_trips(conn, user_id)
    known_booking_refs = {t["bookingReference"] for t in existing if t.get("bookingReference")}
    all_trips = existing + [p for p in p5 if p["bookingReference"] not in known_booking_refs]
    return sorted(all_trips, key=lambda t: t["startDate"])

