"""Validates agent-proposed offers against inventory before they can enter a
cart (section 8 "Quantity and offer validation", section 12 `/tool-calls/{id}/results`).

An offer looks like:
    {
      "kind": "flight" | "hotel_stay",
      "entity_type": "flight_fare" | "room_type",
      "entity_id": "...",
      "items": [{"inventory_id": "...", "units": <int>}, ...],
      "display": {...},          # opaque, passed straight into the audit event
      "claimed_total": "123.45", # optional; only ever compared, never trusted
    }
For `hotel_stay`, `items` has one entry per night, in check-in..check-out-1 order.
Activities are display-only and are never validated as bookable offers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from src.core import dates, fx, money
from src.core.clock import Clock
from src.db.repositories import catalog as catalog_repo
from src.db.repositories.trips import Trip
from src.services import audit_service

VALID_KINDS = {"flight": "flight_fare", "hotel_stay": "room_type"}


@dataclass(frozen=True)
class ValidatedOffer:
    accepted: bool
    code: Optional[str]
    message: Optional[str]
    kind: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    currency: Optional[str] = None
    lines: Optional[list[dict]] = None  # [{inventory_id, for_date, units, unit_price_minor}]
    price_mismatch: bool = False


def _is_clean_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _reject(code: str, message: str) -> ValidatedOffer:
    return ValidatedOffer(accepted=False, code=code, message=message)


def validate_offer(conn, offer: dict, *, trip: Optional[Trip], session_currency: str,
                    today: date, now: Optional[datetime] = None) -> ValidatedOffer:
    if not isinstance(offer, dict):
        return _reject("MALFORMED_ITEM", "offer must be an object")

    kind = offer.get("kind")
    if kind == "activity":
        return _reject("NOT_BOOKABLE", "activities are informational only and cannot be booked")
    if kind not in VALID_KINDS:
        return _reject("MALFORMED_ITEM", f"unknown offer kind: {kind!r}")

    entity_type = offer.get("entity_type")
    entity_id = offer.get("entity_id")
    if entity_type != VALID_KINDS[kind] or not entity_id:
        return _reject("ENTITY_MISMATCH", "entity_type/entity_id do not match the offer kind")

    items = offer.get("items")
    if not isinstance(items, list) or not items:
        return _reject("MALFORMED_ITEM", "offer must include a non-empty items list")

    seen_inventory_ids: set[str] = set()
    resolved_rows: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            return _reject("MALFORMED_ITEM", "each item must be an object")
        inventory_id = raw.get("inventory_id")
        units = raw.get("units")
        if not isinstance(inventory_id, str) or not inventory_id:
            return _reject("MALFORMED_ITEM", "item is missing inventory_id")
        if not _is_clean_int(units) or units < 1:
            return _reject("INVALID_QUANTITY", f"units must be an integer >= 1, got {units!r}")
        if inventory_id in seen_inventory_ids:
            return _reject("DUPLICATE_ITEM", f"duplicate inventory row in one offer: {inventory_id}")
        seen_inventory_ids.add(inventory_id)

        row = catalog_repo.get_inventory_row(conn, inventory_id)
        if row is None:
            return _reject("UNKNOWN_INVENTORY", f"unknown inventory row: {inventory_id}")
        if row["entity_type"] != entity_type or row["entity_id"] != entity_id:
            return _reject("ENTITY_MISMATCH", "inventory row does not match the offer's entity")
        # Local prices are converted into the session currency at the demo rates (src/core/fx.py);
        # only a currency with no rate is refused.
        if not (fx.supported(row["currency"]) and fx.supported(session_currency)):
            return _reject("CURRENCY_MISMATCH",
                            f"no exchange rate for {row['currency']} -> {session_currency}")
        try:
            for_date = date.fromisoformat(row["for_date"])
        except ValueError:
            return _reject("MALFORMED_ITEM", f"inventory row has an invalid date: {row['for_date']}")
        if for_date < today:
            return _reject("DATE_IN_PAST", f"inventory date {row['for_date']} is in the past")
        if trip is not None and not (trip.start_date <= row["for_date"] <= trip.end_date):
            return _reject("DATE_OUTSIDE_TRIP", f"inventory date {row['for_date']} is outside the trip dates")

        available = row["total_units"] - row["booked_units"] - row["held_units"]
        if available < units:
            return _reject("INSUFFICIENT_AVAILABILITY",
                            f"only {available} units available for {inventory_id}, requested {units}")
        resolved_rows.append({"row": row, "units": units,
                              "unit_price_minor": fx.convert_to_minor(row["price"], row["currency"], session_currency)})

    if kind == "flight":
        result = _validate_flight(conn, resolved_rows, trip, now)
    else:
        result = _validate_hotel(conn, resolved_rows, trip)
    if not result.accepted:
        return result

    claimed_total = offer.get("claimed_total")
    price_mismatch = False
    if claimed_total is not None:
        try:
            claimed_minor = money.to_minor(claimed_total)
            backend_minor = sum(money.line_total_minor(l["units"], l["unit_price_minor"]) for l in resolved_rows)
            price_mismatch = claimed_minor != backend_minor
        except money.MoneyError:
            price_mismatch = True

    lines = [
        {
            "inventory_id": l["row"]["inventory_id"],
            "for_date": l["row"]["for_date"],
            "units": l["units"],
            "unit_price_minor": l["unit_price_minor"],
        }
        for l in resolved_rows
    ]
    return ValidatedOffer(accepted=True, code=None, message=None, kind=kind, entity_type=entity_type,
                          entity_id=entity_id, currency=session_currency, lines=lines,
                          price_mismatch=price_mismatch)


def _validate_flight(conn, resolved_rows: list[dict], trip: Optional[Trip],
                     now: Optional[datetime]) -> ValidatedOffer:
    if len(resolved_rows) != 1:
        return _reject("MALFORMED_ITEM", "a flight offer must have exactly one inventory row")
    # Compare instants, not calendar dates: landing after local midnight is fine; landing at or
    # before take-off, or a flight that has already left, is not.
    flight = catalog_repo.flight_for_fare(conn, resolved_rows[0]["row"]["entity_id"])
    if flight is not None:
        try:
            times = dates.flight_times(flight["departs_at"], flight["arrives_at"], None, None)
        except ValueError:
            return _reject("MALFORMED_ITEM", "flight has an invalid departure or arrival time")
        if not times["arrivesAfterDeparture"]:
            return _reject("NOT_BOOKABLE", "flight arrival is not after its departure")
        if now is not None and dates.has_departed(flight["departs_at"], now):
            return _reject("DATE_IN_PAST", f"flight {flight['flight_number']} has already departed")
    units = resolved_rows[0]["units"]
    if trip is not None and units != trip.party_size:
        return _reject("INVALID_QUANTITY",
                        f"flight units {units} must equal the trip's party size {trip.party_size}")
    return ValidatedOffer(accepted=True, code=None, message=None)


def _validate_hotel(conn, resolved_rows: list[dict], trip: Optional[Trip]) -> ValidatedOffer:
    dates = sorted(date.fromisoformat(l["row"]["for_date"]) for l in resolved_rows)
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days != 1:
            return _reject("MISSING_NIGHTS", "hotel nights must be consecutive with no gaps")

    units_set = {l["units"] for l in resolved_rows}
    if len(units_set) != 1:
        return _reject("INVALID_QUANTITY", "the same number of rooms must be booked every night")
    rooms = next(iter(units_set))

    entity_id = resolved_rows[0]["row"]["entity_id"]
    room_type = catalog_repo.get_room_type(conn, entity_id)
    if room_type is None:
        return _reject("UNKNOWN_INVENTORY", f"unknown room type: {entity_id}")

    if trip is not None:
        if rooms > trip.party_size:
            return _reject("OCCUPANCY_EXCEEDED", "rooms booked cannot exceed the number of travellers")
        if rooms * room_type["max_adults"] < trip.adults:
            return _reject("OCCUPANCY_EXCEEDED", "rooms cannot fit the trip's adults")
        if rooms * room_type["max_children"] < trip.children:
            return _reject("OCCUPANCY_EXCEEDED", "rooms cannot fit the trip's children")
        if rooms * room_type["max_occupancy"] < trip.party_size:
            return _reject("OCCUPANCY_EXCEEDED", "rooms cannot fit the trip's party size")

    check_in_row = sorted(resolved_rows, key=lambda l: l["row"]["for_date"])[0]["row"]
    if check_in_row["closed_to_arrival"]:
        return _reject("CLOSED_TO_ARRIVAL", "the room type is closed to arrival on the check-in date")

    nights = len(resolved_rows)
    min_stay = max(l["row"]["min_stay_nights"] for l in resolved_rows)
    if nights < min_stay:
        return _reject("MIN_STAY_NOT_MET", f"stay of {nights} nights is below the minimum of {min_stay}")

    return ValidatedOffer(accepted=True, code=None, message=None)


def process_tool_result(
    conn, clock: Clock, session_id: str, *, tool_call_id: str, agent_run_id: str,
    offers: list[dict], activities: Optional[list[dict]] = None,
    trip: Optional[Trip], session_currency: str, error: Optional[str] = None,
) -> dict:
    """Validates every offer, writes exactly one TOOL_RESULT audit event covering
    accepted offers (with backend prices and an `offer_ref`), rejected offers
    (with their codes), and informational activities. Returns the same summary
    that goes into the event's result_json, for the HTTP layer to relay."""
    today, now = dates.local_today(clock), clock.now()
    accepted: list[dict] = []
    rejected: list[dict] = []

    for index, offer in enumerate(offers or []):
        result = validate_offer(conn, offer, trip=trip, session_currency=session_currency, today=today, now=now)
        if result.accepted:
            accepted.append({
                "index": index, "kind": result.kind, "entity_type": result.entity_type,
                "entity_id": result.entity_id, "currency": result.currency, "lines": result.lines,
                "price_mismatch": result.price_mismatch,
            })
        else:
            rejected.append({"index": index, "code": result.code, "message": result.message})

    outcome = "success" if (accepted or not offers) and error is None else (
        "refused" if rejected and not accepted else "info"
    )
    event = audit_service.append(
        conn, session_id=session_id, event_type="TOOL_RESULT", actor="agent",
        agent_run_id=agent_run_id, occurred_at=clock.utc(), outcome=outcome,
        input_data={"tool_call_id": tool_call_id},
        result_data={
            "accepted": accepted, "rejected": rejected,
            "activities": activities or [], "error": error,
        },
        caused_by_event_id=tool_call_id,
        reason_code=rejected[0]["code"] if outcome == "refused" else None,
        reason=rejected[0]["message"] if outcome == "refused" else None,
    )

    accepted_with_refs = [
        {**a, "offer_ref": f"{event.event_id}#{a['index']}"} for a in accepted
    ]
    return {
        "event_id": event.event_id, "accepted": accepted_with_refs, "rejected": rejected,
        "activities": activities or [], "error": error,
    }


def parse_offer_ref(offer_ref: str) -> tuple[str, int]:
    if "#" not in offer_ref:
        raise ValueError(f"malformed offer_ref: {offer_ref!r}")
    event_id, _, index_text = offer_ref.partition("#")
    if not index_text.isdigit():
        raise ValueError(f"malformed offer_ref: {offer_ref!r}")
    return event_id, int(index_text)
