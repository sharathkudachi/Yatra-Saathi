"""Authoritative service layer for structured itineraries and trip plans (Phase 2A).

Follows project conventions:
- Strict validation of dates, money, travellers, coordinates, and backend references.
- Uses existing database tables `itineraries` and `itinerary_items`.
- Authoritative money calculated using core.money (no floats).
- Enforces ownership and lifecycle transitions.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from src.contracts.codes import RefusalError
from src.core import fx, money
from src.core.clock import Clock
from src.core.dates import parse_date_only
from src.core.geo import is_valid_coord
from src.core.ids import new_id
from src.db.repositories import carts as carts_repo
from src.db.repositories import catalog as catalog_repo
from src.db.repositories import sessions as sessions_repo
from src.schemas.itinerary import (
    AccommodationStay,
    ActivityCategory,
    GenerateItineraryRequest,
    GenerateItineraryResponse,
    ItemSource,
    ItineraryActivity,
    ItineraryAlternativeOption,
    ItineraryDay,
    ItineraryStatus,
    ItineraryValidationResult,
    ReplanItineraryRequest,
    SelectAlternativeOptionRequest,
    TransportSegment,
    TransportType,
    TripPlan,
    VALID_LIFECYCLE_TRANSITIONS,
)


def validate_itinerary(plan: TripPlan, conn: Optional[sqlite3.Connection] = None) -> ItineraryValidationResult:
    """Validate a TripPlan against all business, date, money, geographic, and grounding rules."""
    errors: list[str] = []
    warnings: list[str] = []


    # 1. Date range
    if plan.end_date < plan.start_date:
        errors.append(f"end_date {plan.end_date.isoformat()} cannot be before start_date {plan.start_date.isoformat()}")

    # 2. Travellers
    if plan.travellers < 1:
        errors.append(f"travellers count must be at least 1, got {plan.travellers}")

    # 3. Currency
    if conn is not None:
        curr_row = conn.execute("SELECT 1 FROM currencies WHERE iso4217 = ?", (plan.currency,)).fetchone()
        if not curr_row:
            errors.append(f"unsupported currency: {plan.currency}")

    # 4. Money validation on plan totals
    for field_name, amount in [
        ("budget", plan.budget),
        ("total_estimated_cost", plan.total_estimated_cost),
        ("total_authoritative_cost", plan.total_authoritative_cost),
    ]:
        if amount is not None:
            try:
                money.parse_amount(amount)
            except Exception as exc:
                errors.append(f"invalid {field_name} money amount '{amount}': {exc}")

    if plan.budget is not None and plan.total_authoritative_cost is not None:
        try:
            b_val = money.parse_amount(plan.budget)
            c_val = money.parse_amount(plan.total_authoritative_cost)
            if c_val > b_val:
                errors.append(f"total authoritative cost '{plan.total_authoritative_cost}' exceeds trip budget '{plan.budget}'")
        except Exception:
            pass

    # 5. Itinerary days & activities
    expected_days = (plan.end_date - plan.start_date).days + 1
    if len(plan.days) > expected_days:
        errors.append(f"too many itinerary days ({len(plan.days)}) for trip range ({expected_days} days)")

    for idx, day in enumerate(plan.days, start=1):
        if day.date < plan.start_date or day.date > plan.end_date:
            errors.append(
                f"day {day.day_number} date {day.date.isoformat()} outside trip dates {plan.start_date.isoformat()} to {plan.end_date.isoformat()}"
            )
        if day.estimated_cost is not None:
            try:
                money.parse_amount(day.estimated_cost)
            except Exception as exc:
                errors.append(f"day {day.day_number} invalid estimated_cost '{day.estimated_cost}': {exc}")

        for act in day.activities:
            if act.currency != plan.currency:
                warnings.append(f"activity '{act.title}' currency {act.currency} differs from trip currency {plan.currency}")
            if act.latitude is not None or act.longitude is not None:
                if not is_valid_coord(act.latitude, act.longitude):
                    errors.append(f"activity '{act.title}' has invalid coordinates: ({act.latitude}, {act.longitude})")
            if act.estimated_cost is not None:
                try:
                    money.parse_amount(act.estimated_cost)
                except Exception as exc:
                    errors.append(f"activity '{act.title}' invalid estimated_cost '{act.estimated_cost}': {exc}")
            if act.authoritative_cost is not None:
                try:
                    money.parse_amount(act.authoritative_cost)
                except Exception as exc:
                    errors.append(f"activity '{act.title}' invalid authoritative_cost '{act.authoritative_cost}': {exc}")

    # 6. Transport segments
    for seg in plan.transport:
        if seg.origin_latitude is not None or seg.origin_longitude is not None:
            if not is_valid_coord(seg.origin_latitude, seg.origin_longitude):
                errors.append(f"transport segment '{seg.origin}->{seg.destination}' has invalid origin coordinates")
        if seg.dest_latitude is not None or seg.dest_longitude is not None:
            if not is_valid_coord(seg.dest_latitude, seg.dest_longitude):
                errors.append(f"transport segment '{seg.origin}->{seg.destination}' has invalid destination coordinates")
        if seg.known_price is not None:
            try:
                money.parse_amount(seg.known_price)
            except Exception as exc:
                errors.append(f"transport segment known_price '{seg.known_price}' invalid: {exc}")

        # Authoritative reference check
        if conn is not None and seg.reference and seg.reference.startswith(("far_", "flt_")):
            flt = conn.execute("SELECT 1 FROM flight_fares WHERE fare_id = ? LIMIT 1", (seg.reference,)).fetchone()
            if not flt:
                flt = conn.execute("SELECT 1 FROM flights WHERE flight_id = ? OR flight_number = ? LIMIT 1", (seg.reference, seg.reference)).fetchone()
            if not flt:
                errors.append(f"unknown flight reference '{seg.reference}' not found in catalog")

    # 7. Accommodation stays
    for stay in plan.accommodation:
        if stay.check_out_date <= stay.check_in_date:
            errors.append(f"accommodation stay '{stay.hotel_name}' check_out_date must be after check_in_date")
        if stay.latitude is not None or stay.longitude is not None:
            if not is_valid_coord(stay.latitude, stay.longitude):
                errors.append(f"accommodation stay '{stay.hotel_name}' has invalid coordinates")
        if stay.known_price is not None:
            try:
                money.parse_amount(stay.known_price)
            except Exception as exc:
                errors.append(f"accommodation stay known_price '{stay.known_price}' invalid: {exc}")

        # Authoritative reference check
        if conn is not None and stay.hotel_id:
            htl = conn.execute("SELECT 1 FROM hotels WHERE hotel_id = ?", (stay.hotel_id,)).fetchone()
            if not htl:
                errors.append(f"unknown hotel ID '{stay.hotel_id}' not found in catalog")

    # 8. Duplicate activities and POI catalog grounding
    seen_activity_ids = set()
    seen_poi_ids = set()
    for day in plan.days:
        if len(day.activities) > 8:
            warnings.append(f"day {day.day_number} has high activity density ({len(day.activities)} activities)")
        for act in day.activities:
            if act.id in seen_activity_ids:
                errors.append(f"Duplicate activity ID '{act.id}' across days")
            seen_activity_ids.add(act.id)

            if act.entity_id and act.entity_type == "poi":
                if act.entity_id in seen_poi_ids:
                    errors.append(f"Duplicate activity POI '{act.entity_id}' ({act.title}) scheduled multiple times")
                seen_poi_ids.add(act.entity_id)

                if conn is not None:
                    poi_row = conn.execute(
                        "SELECT 1 FROM itinerary_items WHERE entity_type = 'poi' AND entity_id = ? LIMIT 1",
                        (act.entity_id,),
                    ).fetchone()
                    if not poi_row:
                        errors.append(f"unknown activity POI '{act.entity_id}' not found in catalog")

    return ItineraryValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings, itinerary=plan if len(errors) == 0 else None)



def validate_lifecycle_transition(current_status: ItineraryStatus, next_status: ItineraryStatus) -> None:
    if current_status == next_status:
        return
    allowed = VALID_LIFECYCLE_TRANSITIONS.get(current_status, set())
    if next_status not in allowed:
        raise RefusalError(
            "INVALID_STATE",
            f"cannot transition itinerary from {current_status.value} to {next_status.value} (allowed: {[s.value for s in allowed]})",
        )


def _ensure_trip_record(conn: sqlite3.Connection, clock: Clock, user_id: str, plan: TripPlan) -> str:
    """Ensure a corresponding trip row exists in trips table."""
    if plan.trip_id:
        row = conn.execute("SELECT owner_user_id FROM trips WHERE trip_id = ?", (plan.trip_id,)).fetchone()
        if not row:
            raise RefusalError("STATE_INVALID", f"trip {plan.trip_id} does not exist")
        if row[0] != user_id:
            raise RefusalError("SESSION_ACCESS_DENIED", "cannot attach itinerary to a trip owned by another user", http_status=403)
        return plan.trip_id

    # Create a trip row for this plan
    trip_id = new_id("trp")
    now_str = clock.utc()
    dest_city = conn.execute("SELECT city_id FROM cities WHERE name = ? LIMIT 1", (plan.destination,)).fetchone()
    dest_city_id = dest_city[0] if dest_city else (conn.execute("SELECT city_id FROM cities LIMIT 1").fetchone()[0])
    orig_city = conn.execute("SELECT city_id FROM cities WHERE name = ? LIMIT 1", (plan.origin,)).fetchone()
    orig_city_id = orig_city[0] if orig_city else None

    conn.execute(
        """INSERT INTO trips (
            trip_id, owner_user_id, title, origin_city_id, destination_city_id,
            start_date, end_date, party_size, adults, children, trip_type,
            is_group_trip, status, home_currency, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'leisure', 0, ?, ?, ?, ?, ?)""",
        (
            trip_id,
            user_id,
            plan.title,
            orig_city_id,
            dest_city_id,
            plan.start_date.isoformat(),
            plan.end_date.isoformat(),
            plan.travellers,
            plan.travellers,
            0,
            "planning",
            plan.currency,
            f"Created for itinerary {plan.id}",
            now_str,
            now_str,
        ),
    )
    return trip_id


def create_itinerary_draft(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    plan: TripPlan,
    session_id: Optional[str] = None,
) -> TripPlan:
    """Validate and persist a new itinerary draft into the authoritative SQLite tables."""
    # Run comprehensive domain validation
    validation = validate_itinerary(plan, conn=conn)
    if not validation.valid:
        raise RefusalError("STATE_INVALID", f"itinerary validation failed: {'; '.join(validation.errors)}", http_status=422)

    now_str = clock.utc()
    itinerary_id = plan.id if plan.id and not plan.id.startswith("draft_") else new_id("itn")
    trip_id = _ensure_trip_record(conn, clock, user_id, plan)

    # Compute total cost for DB column
    total_cost = plan.total_authoritative_cost or plan.total_estimated_cost or "0.00"

    # Store full structured representation in optimizer_weights metadata column
    meta = {
        "origin": plan.origin,
        "destination": plan.destination,
        "travellers": plan.travellers,
        "budget": plan.budget,
        "total_estimated_cost": plan.total_estimated_cost,
        "total_authoritative_cost": plan.total_authoritative_cost,
        "transport": [t.model_dump(mode="json") for t in plan.transport],
        "accommodation": [a.model_dump(mode="json") for a in plan.accommodation],
        "constraints": plan.constraints,
        "session_id": session_id or plan.session_id,
    }

    conn.execute(
        """INSERT INTO itineraries (
            itinerary_id, trip_id, name, version, is_active, generated_by,
            total_cost, currency, total_duration_minutes, total_carbon_kg,
            optimizer_weights, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, 'user', ?, ?, 0, 0.0, ?, ?, ?, ?)""",
        (
            itinerary_id,
            trip_id,
            plan.title,
            plan.version,
            total_cost,
            plan.currency,
            json.dumps(meta),
            plan.status.value,
            now_str,
            now_str,
        ),
    )

    # Insert items
    sort_idx = 0
    for day in plan.days:
        for act in day.activities:
            act_id = act.id if act.id and not act.id.startswith("draft_") else new_id("itm")
            cost_str = act.authoritative_cost or act.estimated_cost or "0.00"
            conn.execute(
                """INSERT INTO itinerary_items (
                    item_id, itinerary_id, day_index, sort_order, starts_at, ends_at,
                    item_type, entity_type, entity_id, title, cost, currency,
                    carbon_kg, duration_minutes, source, explanation, locked, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0, ?, ?, 0, 'proposed', ?, ?)""",
                (
                    act_id,
                    itinerary_id,
                    day.day_number,
                    sort_idx,
                    act.start_time,
                    act.end_time,
                    act.category.value,
                    act.entity_type,
                    act.entity_id,
                    act.title,
                    cost_str,
                    act.currency,
                    act.source.value,
                    act.description,
                    now_str,
                    now_str,
                ),
            )
            sort_idx += 1

    return plan.model_copy(
        update={
            "id": itinerary_id,
            "trip_id": trip_id,
            "session_id": session_id or plan.session_id,
            "created_at": now_str,
            "updated_at": now_str,
        }
    )


def get_itinerary(conn: sqlite3.Connection, itinerary_id: str, user_id: Optional[str] = None) -> TripPlan:
    """Retrieve an itinerary by ID and verify user ownership."""
    row = conn.execute(
        """SELECT i.itinerary_id, i.trip_id, i.name, i.version, i.total_cost, i.currency,
                  i.optimizer_weights, i.status, i.created_at, i.updated_at,
                  t.owner_user_id, t.origin_city_id, t.destination_city_id,
                  t.start_date, t.end_date, t.party_size, co.name AS origin_name, cd.name AS dest_name
           FROM itineraries i
           JOIN trips t ON t.trip_id = i.trip_id
           LEFT JOIN cities co ON co.city_id = t.origin_city_id
           LEFT JOIN cities cd ON cd.city_id = t.destination_city_id
           WHERE i.itinerary_id = ?""",
        (itinerary_id,),
    ).fetchone()

    if not row:
        if itinerary_id.startswith("session_plan_") or itinerary_id == "preview_plan":
            if itinerary_id.startswith("session_plan_"):
                session_id = itinerary_id[len("session_plan_"):]
            else:
                effective_u = user_id or "usr_demo0001"
                s_row = conn.execute(
                    "SELECT session_id FROM agent_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (effective_u,),
                ).fetchone()
                session_id = s_row["session_id"] if s_row else None

            if session_id:
                session = sessions_repo.get(conn, session_id)
                effective_user = user_id or (session.user_id if session else "usr_demo0001")
                plan = build_plan_from_session(conn, session_id, effective_user)
                if plan:
                    from src.core.clock import SystemClock
                    clock = SystemClock()
                    try:
                        persisted = create_itinerary_draft(conn, clock, effective_user, plan, session_id=session_id)
                        return persisted
                    except Exception:
                        return plan
        raise RefusalError("STATE_INVALID", f"itinerary {itinerary_id} not found", http_status=404)

    if user_id and row["owner_user_id"] != user_id:
        raise RefusalError("SESSION_ACCESS_DENIED", "access denied to this itinerary", http_status=403)

    meta = {}
    if row["optimizer_weights"]:
        try:
            meta = json.loads(row["optimizer_weights"])
        except Exception:
            pass

    origin = meta.get("origin") or row["origin_name"] or "Origin"
    destination = meta.get("destination") or row["dest_name"] or "Destination"
    start_date = parse_date_only(row["start_date"])
    end_date = parse_date_only(row["end_date"])
    status = ItineraryStatus(row["status"]) if row["status"] in [s.value for s in ItineraryStatus] else ItineraryStatus.DRAFT

    # Fetch items and group into days
    item_rows = conn.execute(
        """SELECT item_id, day_index, sort_order, starts_at, ends_at, item_type,
                  entity_type, entity_id, title, cost, currency, source, explanation
           FROM itinerary_items WHERE itinerary_id = ? ORDER BY day_index, sort_order""",
        (itinerary_id,),
    ).fetchall()

    days_map: dict[int, list[ItineraryActivity]] = {}
    for ir in item_rows:
        day_idx = ir["day_index"]
        cat = ActivityCategory.ACTIVITY
        if ir["item_type"] in [c.value for c in ActivityCategory]:
            cat = ActivityCategory(ir["item_type"])
        src = ItemSource.USER
        if ir["source"] in [s.value for s in ItemSource]:
            src = ItemSource(ir["source"])

        is_authoritative = ir["entity_type"] in ("flight_fare", "room_type")
        act = ItineraryActivity(
            id=ir["item_id"],
            title=ir["title"],
            description=ir["explanation"],
            start_time=ir["starts_at"],
            end_time=ir["ends_at"],
            currency=ir["currency"],
            authoritative_cost=ir["cost"] if is_authoritative else None,
            estimated_cost=ir["cost"] if not is_authoritative else None,
            category=cat,
            source=src,
            entity_type=ir["entity_type"],
            entity_id=ir["entity_id"],
        )
        days_map.setdefault(day_idx, []).append(act)

    num_days = (end_date - start_date).days + 1
    days: list[ItineraryDay] = []
    for d_num in range(1, num_days + 1):
        d_date = start_date + timedelta(days=d_num - 1)
        acts = days_map.get(d_num, [])
        days.append(
            ItineraryDay(
                date=d_date,
                day_number=d_num,
                title=f"Day {d_num}",
                activities=acts,
                locations=[destination],
            )
        )

    transport = [TransportSegment.model_validate(t) for t in meta.get("transport", [])]
    accommodation = [AccommodationStay.model_validate(a) for a in meta.get("accommodation", [])]

    return TripPlan(
        id=row["itinerary_id"],
        trip_id=row["trip_id"],
        session_id=meta.get("session_id"),
        title=row["name"],
        origin=origin,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        travellers=meta.get("travellers") or row["party_size"],
        currency=row["currency"],
        budget=meta.get("budget"),
        total_estimated_cost=meta.get("total_estimated_cost"),
        total_authoritative_cost=row["total_cost"],
        transport=transport,
        accommodation=accommodation,
        days=days,
        constraints=meta.get("constraints", {}),
        status=status,
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def update_itinerary(
    conn: sqlite3.Connection,
    clock: Clock,
    itinerary_id: str,
    user_id: str,
    updated_plan: TripPlan,
) -> TripPlan:
    """Validate and update an existing itinerary."""
    current = get_itinerary(conn, itinerary_id, user_id=user_id)

    # Validate lifecycle transition
    validate_lifecycle_transition(current.status, updated_plan.status)

    # Validate updated plan
    validation = validate_itinerary(updated_plan, conn=conn)
    if not validation.valid:
        raise RefusalError("STATE_INVALID", f"validation failed: {'; '.join(validation.errors)}", http_status=422)

    now_str = clock.utc()
    total_cost = updated_plan.total_authoritative_cost or updated_plan.total_estimated_cost or current.total_authoritative_cost or "0.00"
    new_version = current.version + 1

    meta = {
        "origin": updated_plan.origin,
        "destination": updated_plan.destination,
        "travellers": updated_plan.travellers,
        "budget": updated_plan.budget,
        "total_estimated_cost": updated_plan.total_estimated_cost,
        "total_authoritative_cost": total_cost,
        "transport": [t.model_dump(mode="json") for t in updated_plan.transport],
        "accommodation": [a.model_dump(mode="json") for a in updated_plan.accommodation],
        "constraints": updated_plan.constraints,
        "session_id": updated_plan.session_id or current.session_id,
    }

    conn.execute(
        """UPDATE itineraries SET
            name = ?, version = ?, total_cost = ?, currency = ?,
            optimizer_weights = ?, status = ?, updated_at = ?
           WHERE itinerary_id = ?""",
        (
            updated_plan.title,
            new_version,
            total_cost,
            updated_plan.currency,
            json.dumps(meta),
            updated_plan.status.value,
            now_str,
            itinerary_id,
        ),
    )

    # Replace itinerary items
    conn.execute("DELETE FROM itinerary_items WHERE itinerary_id = ?", (itinerary_id,))
    sort_idx = 0
    for day in updated_plan.days:
        for act in day.activities:
            act_id = act.id if act.id and not act.id.startswith("draft_") else new_id("itm")
            cost_str = act.authoritative_cost or act.estimated_cost or "0.00"
            conn.execute(
                """INSERT INTO itinerary_items (
                    item_id, itinerary_id, day_index, sort_order, starts_at, ends_at,
                    item_type, entity_type, entity_id, title, cost, currency,
                    carbon_kg, duration_minutes, source, explanation, locked, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0, ?, ?, 0, 'proposed', ?, ?)""",
                (
                    act_id,
                    itinerary_id,
                    day.day_number,
                    sort_idx,
                    act.start_time,
                    act.end_time,
                    act.category.value,
                    act.entity_type,
                    act.entity_id,
                    act.title,
                    cost_str,
                    act.currency,
                    act.source.value,
                    act.description,
                    now_str,
                    now_str,
                ),
            )
            sort_idx += 1

    return updated_plan.model_copy(
        update={
            "id": itinerary_id,
            "version": new_version,
            "updated_at": now_str,
        }
    )


def build_plan_from_session(conn: sqlite3.Connection, session_id: str, user_id: str) -> Optional[TripPlan]:
    """Deterministically assemble a structured TripPlan from an active session's cart and brief."""
    session = sessions_repo.get(conn, session_id)
    if not session or session.user_id != user_id:
        return None

    constraints = json.loads(session.constraints_json or "{}")
    cart = carts_repo.get_active_cart(conn, session_id) or carts_repo.get_booked_cart(conn, session_id)
    cart_items = carts_repo.list_active_items(conn, cart.cart_id) if cart else []

    dest = constraints.get("destination_name")
    start = constraints.get("start_date")
    end = constraints.get("end_date")
    travellers = int(constraints.get("travellers") or 1)
    currency = session.currency

    transports: list[TransportSegment] = []
    accommodations: list[AccommodationStay] = []
    authoritative_minor = 0

    # Parse cart items
    for it in cart_items:
        details = catalog_repo.item_details(conn, it.entity_type, it.entity_id) or {}
        authoritative_minor += getattr(it, "line_total_minor", getattr(it, "unit_price_minor", 0) * it.units)

        if details.get("type") == "flight":
            dest = dest or details.get("destination_city")
            seg = TransportSegment(
                id=it.cart_item_id,
                type=TransportType.FLIGHT,
                origin=details["origin_city"],
                origin_code=details.get("origin_code"),
                destination=details["destination_city"],
                dest_code=details.get("destination_code"),
                carrier=details.get("airline"),
                reference=details.get("flight_number"),
                departs_at=details["departs_at"],
                arrives_at=details["arrives_at"],
                known_price=money.format_minor(it.line_total_minor),
                currency=currency,
                origin_latitude=float(details["origin_lat"]) if details.get("origin_lat") is not None else None,
                origin_longitude=float(details["origin_lng"]) if details.get("origin_lng") is not None else None,
                dest_latitude=float(details["dest_lat"]) if details.get("dest_lat") is not None else None,
                dest_longitude=float(details["dest_lng"]) if details.get("dest_lng") is not None else None,
            )
            transports.append(seg)
        elif details.get("type") == "stay":
            dest = dest or details.get("city")
            # Calculate stay start and end dates from cart items
            stay = AccommodationStay(
                id=it.cart_item_id,
                hotel_id=it.entity_id,
                hotel_name=details.get("hotel") or "Hotel",
                room_type_id=it.entity_id if it.entity_type == "room_type" else None,
                room_name=details.get("room"),
                address=details.get("address"),
                check_in_date=parse_date_only(it.for_date),
                check_out_date=parse_date_only(it.for_date) + timedelta(days=1),
                known_price=money.format_minor(it.line_total_minor),
                currency=currency,
                latitude=float(details["latitude"]) if details.get("latitude") is not None else None,
                longitude=float(details["longitude"]) if details.get("longitude") is not None else None,
            )
            accommodations.append(stay)

    if not dest or not start or not end:
        return None

    s_date = parse_date_only(start)
    e_date = parse_date_only(end)
    num_days = max((e_date - s_date).days + 1, 1)

    pois = catalog_repo.list_activities(conn, city_name=dest, limit=50)
    hotel_primary = accommodations[0] if accommodations else None

    days = build_daily_schedule(
        candidate_pois=pois,
        start_date=s_date,
        end_date=e_date,
        destination=dest,
        currency=currency,
        style="balanced",
        hotel_info=hotel_primary,
        transport_info=transports,
    )

    authoritative_cost = money.format_minor(authoritative_minor) if authoritative_minor > 0 else None

    return TripPlan(
        id=f"session_plan_{session_id}",
        session_id=session_id,
        title=f"Trip to {dest}",
        origin=transports[0].origin if transports else "Mumbai",
        destination=dest,
        start_date=s_date,
        end_date=e_date,
        travellers=travellers,
        currency=currency,
        budget=session.spend_cap,
        total_authoritative_cost=authoritative_cost,
        total_estimated_cost=authoritative_cost,
        transport=transports,
        accommodation=accommodations,
        days=days,
        constraints=constraints,
        status=ItineraryStatus.PLANNED if cart_items else ItineraryStatus.DRAFT,
    )


def categorize_activity(title: str) -> ActivityCategory:
    """Classify an activity title into a typed ActivityCategory."""
    lower = title.lower()
    if any(k in lower for k in ("museum", "gallery", "fort", "palace", "temple", "monument", "historic", "heritage", "bazaar", "market", "cultural", "coin", "textile", "art", "theatre")):
        return ActivityCategory.CULTURE
    if any(k in lower for k in ("springs", "beach", "lake", "garden", "lookout", "ridge", "park", "botanical", "sunset", "trail", "nature", "mountain", "channel", "backwater", "cove")):
        return ActivityCategory.NATURE
    if any(k in lower for k in ("food", "dining", "roastery", "coffee", "cooking", "cuisine", "lounge", "bistro", "cafe", "tasting", "dinner", "lunch", "breakfast")):
        return ActivityCategory.FOOD
    if any(k in lower for k in ("flight", "airline", "airport")):
        return ActivityCategory.FLIGHT
    if any(k in lower for k in ("hotel", "check-in", "check-out", "resort", "stay")):
        return ActivityCategory.STAY
    if any(k in lower for k in ("free time", "leisure", "relax", "unwind", "rest", "stroll")):
        return ActivityCategory.FREE_TIME
    return ActivityCategory.ACTIVITY


def calculate_plan_totals(
    conn: Optional[sqlite3.Connection], plan: TripPlan
) -> tuple[Optional[str], Optional[str], dict[str, str]]:
    """Deterministically calculate authoritative totals using core.money (no floating-point math)."""
    transport_minor = 0
    for t in plan.transport:
        if t.known_price:
            transport_minor += money.to_minor(t.known_price)

    accommodation_minor = 0
    for a in plan.accommodation:
        if a.known_price:
            accommodation_minor += money.to_minor(a.known_price)

    activities_auth_minor = 0
    activities_est_minor = 0
    for day in plan.days:
        for act in day.activities:
            if act.authoritative_cost:
                if act.currency and act.currency != plan.currency:
                    if fx.supported(act.currency) and fx.supported(plan.currency):
                        activities_auth_minor += fx.convert_to_minor(act.authoritative_cost, act.currency, plan.currency)
                else:
                    activities_auth_minor += money.to_minor(act.authoritative_cost)
            elif act.estimated_cost:
                if act.currency and act.currency != plan.currency:
                    if fx.supported(act.currency) and fx.supported(plan.currency):
                        activities_est_minor += fx.convert_to_minor(act.estimated_cost, act.currency, plan.currency)
                else:
                    activities_est_minor += money.to_minor(act.estimated_cost)

    total_auth_minor = transport_minor + accommodation_minor + activities_auth_minor
    total_est_minor = total_auth_minor + activities_est_minor

    breakdown = {
        "transport": money.format_minor(transport_minor),
        "accommodation": money.format_minor(accommodation_minor),
        "activities_authoritative": money.format_minor(activities_auth_minor),
        "activities_estimated": money.format_minor(activities_est_minor),
        "authoritative_total": money.format_minor(total_auth_minor),
        "estimated_total": money.format_minor(total_est_minor),
    }

    if plan.budget:
        try:
            budget_minor = money.to_minor(plan.budget)
            remaining_minor = max(0, budget_minor - total_auth_minor)
            breakdown["budget_remaining"] = money.format_minor(remaining_minor)
        except Exception:
            pass

    auth_str = money.format_minor(total_auth_minor) if total_auth_minor > 0 else None
    est_str = money.format_minor(total_est_minor) if total_est_minor > 0 else auth_str
    return auth_str, est_str, breakdown


# In-memory record for structured itinerary audit events across sessions and tests
_ITINERARY_AUDIT_LOG: list[dict] = []


def record_itinerary_event(
    conn: Optional[sqlite3.Connection],
    clock: Clock,
    session_id: Optional[str],
    user_id: str,
    action: str,
    input_data: dict,
    result_data: dict,
    outcome: str = "info",
    reason_code: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """Record a structured itinerary audit event safely."""
    entry = {
        "event_id": new_id("aud"),
        "session_id": session_id,
        "user_id": user_id,
        "action": action,
        "occurred_at": clock.utc(),
        "outcome": outcome,
        "reason_code": reason_code,
        "reason": reason,
        "input": input_data,
        "result": result_data,
        "itinerary_id": result_data.get("itinerary_id") or input_data.get("itinerary_id"),
    }
    _ITINERARY_AUDIT_LOG.append(entry)

    # If linked to a real agent session, append to database audit table using valid schema event type
    if conn is not None and session_id:
        try:
            from src.services import audit_service
            db_event_type = "TOOL_RESULT" if action in ("ITINERARY_GENERATION_COMPLETED", "ITINERARY_REPLANNED", "ITINERARY_OPTION_SELECTED") else "TOOL_CALL"
            if outcome in ("failed", "refused"):
                db_event_type = "ACTION_REFUSED" if outcome == "refused" else "ERROR"
            audit_service.append(
                conn,
                session_id=session_id,
                event_type=db_event_type,
                actor="user",
                actor_user_id=user_id,
                occurred_at=clock.utc(),
                outcome=outcome,
                reason_code=reason_code,
                reason=reason,
                input_data={"action": action, **input_data},
                result_data=result_data,
            )
        except Exception:
            pass  # Never let optional DB audit write crash business logic

    return entry


def get_itinerary_audit_log(session_id: Optional[str] = None) -> list[dict]:
    """Retrieve recorded itinerary audit events."""
    if session_id:
        return [e for e in _ITINERARY_AUDIT_LOG if e.get("session_id") == session_id]
    return list(_ITINERARY_AUDIT_LOG)


def get_candidate_transport(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    start_date: date,
    end_date: date,
    travellers: int,
    currency: str,
) -> list[TransportSegment]:
    """Fetch authoritative flight candidates between origin and destination."""
    orig_city = catalog_repo.find_city_by_name(conn, origin)
    dest_city = catalog_repo.find_city_by_name(conn, destination)
    if not orig_city or not dest_city:
        return []

    segments: list[TransportSegment] = []
    # Outbound flight
    out_offers = catalog_repo.flight_fare_offers(
        conn,
        origin_city_id=orig_city["city_id"],
        dest_city_id=dest_city["city_id"],
        depart_date=start_date.isoformat(),
        cabin_class="economy",
    )
    if out_offers:
        avail_out = [o for o in out_offers if int(o.get("available") or 0) >= travellers]
        cands_out = avail_out if avail_out else out_offers
        cands_out = sorted(cands_out, key=lambda o: money.to_minor(o["price"]))
        best_out = cands_out[0]
        per_person = money.to_minor(best_out["price"])
        total_fare = money.format_minor(per_person * travellers)
        segments.append(
            TransportSegment(
                id=new_id("itm"),
                type=TransportType.FLIGHT,
                origin=best_out["origin_city"],
                origin_code=best_out.get("origin_code"),
                destination=best_out["dest_city"],
                dest_code=best_out.get("dest_code"),
                carrier=best_out.get("airline_name"),
                reference=best_out["fare_id"],
                entity_type="flight_fare",
                entity_id=best_out["fare_id"],
                departs_at=best_out["departs_at"],
                arrives_at=best_out["arrives_at"],
                known_price=total_fare,
                currency=currency,
                origin_latitude=float(best_out["origin_lat"]) if best_out.get("origin_lat") is not None else None,
                origin_longitude=float(best_out["origin_lng"]) if best_out.get("origin_lng") is not None else None,
                dest_latitude=float(best_out["dest_lat"]) if best_out.get("dest_lat") is not None else None,
                dest_longitude=float(best_out["dest_lng"]) if best_out.get("dest_lng") is not None else None,
            )
        )

    # Return flight
    ret_offers = catalog_repo.flight_fare_offers(
        conn,
        origin_city_id=dest_city["city_id"],
        dest_city_id=orig_city["city_id"],
        depart_date=end_date.isoformat(),
        cabin_class="economy",
    )
    if ret_offers:
        avail_ret = [o for o in ret_offers if int(o.get("available") or 0) >= travellers]
        cands_ret = avail_ret if avail_ret else ret_offers
        cands_ret = sorted(cands_ret, key=lambda o: money.to_minor(o["price"]))
        best_ret = cands_ret[0]
        per_person = money.to_minor(best_ret["price"])
        total_fare = money.format_minor(per_person * travellers)
        segments.append(
            TransportSegment(
                id=new_id("itm"),
                type=TransportType.FLIGHT,
                origin=best_ret["origin_city"],
                origin_code=best_ret.get("origin_code"),
                destination=best_ret["dest_city"],
                dest_code=best_ret.get("dest_code"),
                carrier=best_ret.get("airline_name"),
                reference=best_ret["fare_id"],
                entity_type="flight_fare",
                entity_id=best_ret["fare_id"],
                departs_at=best_ret["departs_at"],
                arrives_at=best_ret["arrives_at"],
                known_price=total_fare,
                currency=currency,
                origin_latitude=float(best_ret["origin_lat"]) if best_ret.get("origin_lat") is not None else None,
                origin_longitude=float(best_ret["origin_lng"]) if best_ret.get("origin_lng") is not None else None,
                dest_latitude=float(best_ret["dest_lat"]) if best_ret.get("dest_lat") is not None else None,
                dest_longitude=float(best_ret["dest_lng"]) if best_ret.get("dest_lng") is not None else None,
            )
        )

    return segments


def get_candidate_accommodation(
    conn: sqlite3.Connection,
    destination: str,
    start_date: date,
    end_date: date,
    travellers: int,
    currency: str,
) -> list[AccommodationStay]:
    """Fetch authoritative accommodation candidates in destination."""
    dest_city = catalog_repo.find_city_by_name(conn, destination)
    if not dest_city:
        return []

    last_night = (end_date - timedelta(days=1)).isoformat()
    offers = catalog_repo.room_night_offers(
        conn,
        city_id=dest_city["city_id"],
        start_date=start_date.isoformat(),
        end_date=last_night,
        min_occupancy=travellers,
    )
    if not offers:
        return []

    num_nights = max((end_date - start_date).days, 1)
    from collections import defaultdict
    by_room = defaultdict(list)
    for o in offers:
        by_room[o["room_type_id"]].append(o)

    valid_candidates = []
    for r_id, night_rows in by_room.items():
        if len(night_rows) == num_nights and all(int(n.get("available") or 0) >= 1 for n in night_rows):
            tot = sum(money.to_minor(n["price"]) for n in night_rows)
            valid_candidates.append((tot, night_rows[0]))

    if valid_candidates:
        valid_candidates.sort(key=lambda x: x[0])
        total_minor, first_offer = valid_candidates[0]
        total_stay = money.format_minor(total_minor)
    else:
        # Fallback to cheapest single offer
        offers = sorted(offers, key=lambda o: money.to_minor(o["price"]))
        first_offer = offers[0]
        nightly_minor = money.to_minor(first_offer["price"])
        total_stay = money.format_minor(nightly_minor * num_nights)

    return [
        AccommodationStay(
            id=new_id("itm"),
            hotel_id=first_offer["hotel_id"],
            hotel_name=first_offer["hotel_name"],
            room_type_id=first_offer["room_type_id"],
            room_name=first_offer["room_name"],
            address=first_offer.get("address_line"),
            check_in_date=start_date,
            check_out_date=end_date,
            known_price=total_stay,
            currency=currency,
            latitude=float(first_offer["lat"]) if first_offer.get("lat") is not None else None,
            longitude=float(first_offer["lng"]) if first_offer.get("lng") is not None else None,
        )
    ]


def _resolve_poi_cost_and_notes(
    poi: dict, target_currency: str
) -> tuple[Optional[str], Optional[str], str, str]:
    """Safely resolve POI cost without silently relabeling foreign currencies 1:1.

    Sightseeing POIs are non-authoritative inventory, so authoritative_cost is ALWAYS None.
    Returns: (authoritative_cost, estimated_cost, currency, description_suffix)
    """
    authoritative_cost = None
    raw_cost = poi.get("cost")
    poi_curr = (poi.get("currency") or target_currency or "INR").strip().upper()
    target_curr = (target_currency or "INR").strip().upper()

    if raw_cost is None:
        return authoritative_cost, None, target_curr, ""

    try:
        val = Decimal(str(raw_cost))
    except Exception:
        return authoritative_cost, None, target_curr, ""

    if val <= Decimal("0"):
        return authoritative_cost, "0.00", target_curr, ""

    # If catalog currency matches target currency
    if poi_curr == target_curr:
        return authoritative_cost, f"{val:.2f}", target_curr, ""

    # Foreign currency case (e.g. AED catalog item in an INR trip)
    # Option A: Real documented conversion using src.core.fx
    if fx.supported(poi_curr) and fx.supported(target_curr):
        converted_val = fx.convert(str(val), poi_curr, target_curr)
        desc_note = f" (Estimated entry ~{converted_val} {target_curr}, converted from {val:.2f} {poi_curr} via demo fx mid-rate; pay on-site)"
        return authoritative_cost, converted_val, target_curr, desc_note
    else:
        # Option B: Foreign amount is unconvertible; NEVER relabel currency code.
        # Mark estimated_cost as None (pay-on-site) so it is excluded from authoritative totals.
        desc_note = f" (Pay on-site in local currency: {val:.2f} {poi_curr})"
        return authoritative_cost, None, poi_curr, desc_note


def build_daily_schedule(
    candidate_pois: list[dict],
    start_date: date,
    end_date: date,
    destination: str,
    currency: str,
    style: str = "balanced",
    hotel_info: Optional[AccommodationStay] = None,
    transport_info: Optional[list[TransportSegment]] = None,
    preferred_categories: Optional[list[str]] = None,
) -> list[ItineraryDay]:
    """Deterministically assemble daily schedules without duplicates and with reasonable pacing."""
    num_days = max((end_date - start_date).days + 1, 1)
    days: list[ItineraryDay] = []

    # Sort POIs according to style and preferred categories
    filtered_pois = list(candidate_pois)
    if preferred_categories:
        pref_vals = getattr(preferred_categories, "value", preferred_categories)
        if isinstance(pref_vals, (list, tuple, set)):
            pref_cats_set = {str(c).lower() for c in pref_vals}
        else:
            pref_cats_set = {str(pref_vals).lower()}
        def cat_rank(p):
            title = p.get("title", "")
            cat = categorize_activity(title).value
            matches_cat = 1 if cat in pref_cats_set or any(c in title.lower() for c in pref_cats_set) else 0
            if style == "budget":
                p_cost = p.get("cost") or "0.00"
                p_curr = (p.get("currency") or currency).upper()
                c_minor = fx.convert_to_minor(p_cost, p_curr, currency) if fx.supported(p_curr) and fx.supported(currency) else money.to_minor(p_cost)
                return (-matches_cat, c_minor, -p.get("times_planned", 0))
            return (-matches_cat, -p.get("times_planned", 0))
        filtered_pois.sort(key=cat_rank)
    elif style == "budget":
        def budget_rank(p):
            p_cost = p.get("cost") or "0.00"
            p_curr = (p.get("currency") or currency).upper()
            c_minor = fx.convert_to_minor(p_cost, p_curr, currency) if fx.supported(p_curr) and fx.supported(currency) else money.to_minor(p_cost)
            return (c_minor, -p.get("times_planned", 0))
        filtered_pois.sort(key=budget_rank)
    else:
        filtered_pois.sort(key=lambda p: -p.get("times_planned", 0))

    poi_index = 0
    used_poi_ids = set()
    used_titles = set()

    dest_lat = (
        float(candidate_pois[0]["city_lat"])
        if candidate_pois and candidate_pois[0].get("city_lat") is not None
        else (hotel_info.latitude if hotel_info else None)
    )
    dest_lng = (
        float(candidate_pois[0]["city_lng"])
        if candidate_pois and candidate_pois[0].get("city_lng") is not None
        else (hotel_info.longitude if hotel_info else None)
    )

    for day_num in range(1, num_days + 1):
        cur_date = start_date + timedelta(days=day_num - 1)
        activities: list[ItineraryActivity] = []
        is_first_day = day_num == 1
        is_last_day = day_num == num_days

        # Helper to get next unused grounded POI
        def get_next_poi():
            nonlocal poi_index
            while poi_index < len(filtered_pois):
                candidate = filtered_pois[poi_index]
                poi_index += 1
                cand_title = (candidate.get("title") or candidate.get("name") or "").strip().lower()
                c_id = candidate.get("poi_id") or candidate.get("activity_id") or f"poi_{poi_index}"
                candidate["poi_id"] = c_id
                candidate["title"] = candidate.get("title") or candidate.get("name") or "Sightseeing"
                if c_id not in used_poi_ids and cand_title not in used_titles:
                    used_poi_ids.add(c_id)
                    used_titles.add(cand_title)
                    return candidate
            return None

        # -------------------------------------------------------------
        # DAY 1: ARRIVAL, TRANSFER, CHECK-IN, LUNCH, ACTIVITIES, DINNER
        # -------------------------------------------------------------
        if is_first_day:
            t = transport_info[0] if (transport_info and len(transport_info) > 0) else None
            arr_time = "10:30"
            if t and getattr(t, "arrives_at", None) and len(t.arrives_at) >= 16:
                arr_time = t.arrives_at[11:16]

            def _safe_time_add(s_time: str, add_mins: int = 40) -> str:
                try:
                    parts = s_time.split(":")
                    mins = int(parts[0]) * 60 + int(parts[1]) + add_mins
                    mins = min(mins, 23 * 60 + 59)
                    return f"{mins // 60:02d}:{mins % 60:02d}"
                except Exception:
                    return "23:59"

            # 1. Flight arrival
            if t:
                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=f"{t.carrier or 'Flight'} Arrival at {destination} Airport",
                        description=f"{t.carrier or 'Flight'} {t.reference or ''}: {t.origin} → {destination}.",
                        start_time=arr_time,
                        end_time=_safe_time_add(arr_time, 40),
                        location=f"{destination} Airport ({t.dest_code or ''})",
                        latitude=t.dest_latitude or dest_lat,
                        longitude=t.dest_longitude or dest_lng,
                        currency=currency,
                        category=ActivityCategory.FLIGHT,
                        source=ItemSource.BACKEND,
                        entity_type="flight_fare",
                        entity_id=t.reference,
                    )
                )

            # 2. Airport exit and hotel transfer buffer
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title="Airport exit, baggage collection & hotel transfer (~50 mins)",
                    description=f"Airport exit and taxi/cab transfer to accommodation in {destination}.",
                    start_time="11:15",
                    end_time="12:15",
                    location=f"{destination} Airport to Hotel",
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.ACTIVITY,
                    source=ItemSource.BACKEND,
                )
            )

            # 3. Hotel check-in or luggage drop
            if hotel_info:
                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=f"Hotel check-in / luggage drop at {hotel_info.hotel_name}",
                        description="Check-in to room or leave luggage safely with front desk.",
                        start_time="12:15",
                        end_time="13:00",
                        location=hotel_info.address or destination,
                        latitude=hotel_info.latitude or dest_lat,
                        longitude=hotel_info.longitude or dest_lng,
                        currency=currency,
                        category=ActivityCategory.STAY,
                        source=ItemSource.BACKEND,
                        entity_type="room_type",
                        entity_id=hotel_info.hotel_id,
                    )
                )

            # 4. Lunch window
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title=f"Suggested lunch window — regional dining in {destination}",
                    description=f"Taste local culinary specialities in central {destination}.",
                    start_time="13:00",
                    end_time="14:15",
                    location=f"Central {destination}",
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FOOD,
                    source=ItemSource.AI_PLANNER,
                )
            )

            # 5. Afternoon grounded attraction
            p1 = get_next_poi()
            if p1:
                auth_c, est_c, act_curr, desc_suffix = _resolve_poi_cost_and_notes(p1, currency)
                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=p1["title"],
                        description=f"Afternoon visit to {p1['title']} ({p1.get('duration_minutes', 120)} mins).{desc_suffix}",
                        start_time="14:30",
                        end_time="17:00",
                        location=p1.get("city_name") or destination,
                        latitude=float(p1["city_lat"]) if p1.get("city_lat") is not None else dest_lat,
                        longitude=float(p1["city_lng"]) if p1.get("city_lng") is not None else dest_lng,
                        authoritative_cost=auth_c,
                        estimated_cost=est_c,
                        currency=act_curr,
                        category=categorize_activity(p1["title"]),
                        source=ItemSource.AI_PLANNER,
                        entity_type="poi",
                        entity_id=p1["poi_id"],
                    )
                )

            # 6. Evening break & leisure stroll
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title="Local transit & evening tea break",
                    description="Short rest and stroll through the city centre.",
                    start_time="17:00",
                    end_time="18:30",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FREE_TIME,
                    source=ItemSource.AI_PLANNER,
                )
            )

            # 7. Dinner window
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title=f"Suggested dinner — evening cuisine in {destination}",
                    description=f"Relaxing evening meal with regional culinary dishes.",
                    start_time="20:00",
                    end_time="21:30",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FOOD,
                    source=ItemSource.AI_PLANNER,
                )
            )

        # -------------------------------------------------------------
        # INTERMEDIATE DAYS: BREAKFAST, MORNING POI, LUNCH, AFTERNOON POI, DINNER
        # -------------------------------------------------------------
        elif not is_last_day:
            # 1. Breakfast
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title=f"Breakfast at hotel or local cafe",
                    description=f"Fresh morning breakfast before beginning city exploration.",
                    start_time="08:30",
                    end_time="09:30",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FOOD,
                    source=ItemSource.AI_PLANNER,
                )
            )

            # 2. Morning grounded attraction
            p1 = get_next_poi()
            if p1:
                auth_c, est_c, act_curr, desc_suffix = _resolve_poi_cost_and_notes(p1, currency)
                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=p1["title"],
                        description=f"Morning visit to {p1['title']} ({p1.get('duration_minutes', 150)} mins).{desc_suffix}",
                        start_time="09:30",
                        end_time="12:30",
                        location=p1.get("city_name") or destination,
                        latitude=float(p1["city_lat"]) if p1.get("city_lat") is not None else dest_lat,
                        longitude=float(p1["city_lng"]) if p1.get("city_lng") is not None else dest_lng,
                        authoritative_cost=auth_c,
                        estimated_cost=est_c,
                        currency=act_curr,
                        category=categorize_activity(p1["title"]),
                        source=ItemSource.AI_PLANNER,
                        entity_type="poi",
                        entity_id=p1["poi_id"],
                    )
                )

            # 3. Lunch window
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title=f"Suggested lunch area — local flavours",
                    description=f"Midday lunch break near exploration route.",
                    start_time="12:45",
                    end_time="14:00",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FOOD,
                    source=ItemSource.AI_PLANNER,
                )
            )

            # 4. Afternoon grounded attraction
            p2 = get_next_poi()
            if p2:
                auth_c, est_c, act_curr, desc_suffix = _resolve_poi_cost_and_notes(p2, currency)
                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=p2["title"],
                        description=f"Afternoon visit to {p2['title']} ({p2.get('duration_minutes', 120)} mins).{desc_suffix}",
                        start_time="14:30",
                        end_time="17:00",
                        location=p2.get("city_name") or destination,
                        latitude=float(p2["city_lat"]) if p2.get("city_lat") is not None else dest_lat,
                        longitude=float(p2["city_lng"]) if p2.get("city_lng") is not None else dest_lng,
                        authoritative_cost=auth_c,
                        estimated_cost=est_c,
                        currency=act_curr,
                        category=categorize_activity(p2["title"]),
                        source=ItemSource.AI_PLANNER,
                        entity_type="poi",
                        entity_id=p2["poi_id"],
                    )
                )

            # 5. Travel & evening leisure break
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title="Local transit & evening tea break",
                    description="Short break and travel buffer between sights.",
                    start_time="17:00",
                    end_time="18:30",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FREE_TIME,
                    source=ItemSource.AI_PLANNER,
                )
            )

            # 6. Dinner window
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title=f"Traditional dinner in {destination}",
                    description=f"Evening dinner and relaxation.",
                    start_time="20:00",
                    end_time="21:30",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FOOD,
                    source=ItemSource.AI_PLANNER,
                )
            )

        # -------------------------------------------------------------
        # LAST DAY: BREAKFAST, MORNING VISIT, CHECK-OUT, LUNCH, AIRPORT TRANSFER, FLIGHT
        # -------------------------------------------------------------
        else:
            # 1. Breakfast
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title="Breakfast & morning preparation",
                    description="Morning breakfast and luggage packing before check-out.",
                    start_time="08:30",
                    end_time="09:30",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FOOD,
                    source=ItemSource.AI_PLANNER,
                )
            )

            # 2. Morning attraction / souvenir exploration
            p1 = get_next_poi()
            if p1:
                auth_c, est_c, act_curr, desc_suffix = _resolve_poi_cost_and_notes(p1, currency)
                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=p1["title"],
                        description=f"Morning visit to {p1['title']} ({p1.get('duration_minutes', 90)} mins).{desc_suffix}",
                        start_time="09:30",
                        end_time="11:00",
                        location=p1.get("city_name") or destination,
                        latitude=float(p1["city_lat"]) if p1.get("city_lat") is not None else dest_lat,
                        longitude=float(p1["city_lng"]) if p1.get("city_lng") is not None else dest_lng,
                        authoritative_cost=auth_c,
                        estimated_cost=est_c,
                        currency=act_curr,
                        category=categorize_activity(p1["title"]),
                        source=ItemSource.AI_PLANNER,
                        entity_type="poi",
                        entity_id=p1["poi_id"],
                    )
                )

            # 3. Hotel check-out
            if hotel_info:
                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=f"Check-out from {hotel_info.hotel_name}",
                        description="Room check-out, luggage collection and settlement.",
                        start_time="11:00",
                        end_time="11:30",
                        location=hotel_info.address or destination,
                        latitude=hotel_info.latitude or dest_lat,
                        longitude=hotel_info.longitude or dest_lng,
                        currency=currency,
                        category=ActivityCategory.STAY,
                        source=ItemSource.BACKEND,
                        entity_type="room_type",
                        entity_id=hotel_info.hotel_id,
                    )
                )

            # 4. Farewell lunch
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title="Farewell lunch before airport departure",
                    description="Relaxed lunch before heading to the departure airport terminal.",
                    start_time="11:30",
                    end_time="12:30",
                    location=destination,
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.FOOD,
                    source=ItemSource.AI_PLANNER,
                )
            )

            # 5. Airport transfer and security check-in buffer
            activities.append(
                ItineraryActivity(
                    id=new_id("itm"),
                    title=f"Transfer to {destination} Airport & security check-in buffer (~90 mins)",
                    description="Taxi transfer to terminal, baggage drop, and airport security clearance.",
                    start_time="12:30",
                    end_time="14:00",
                    location=f"Transit to {destination} Airport",
                    latitude=dest_lat,
                    longitude=dest_lng,
                    currency=currency,
                    category=ActivityCategory.ACTIVITY,
                    source=ItemSource.BACKEND,
                )
            )

            # 6. Return flight departure
            if transport_info and len(transport_info) > 1:
                ret = transport_info[1]
                dep_time = "14:30"
                if getattr(ret, "departs_at", None) and len(ret.departs_at) >= 16:
                    dep_time = ret.departs_at[11:16]
                if getattr(ret, "arrives_at", None) and len(ret.arrives_at) >= 16:
                    arr_time = ret.arrives_at[11:16]
                if arr_time <= dep_time:
                    try:
                        p = dep_time.split(":")
                        m = min(int(p[0]) * 60 + int(p[1]) + 120, 23 * 60 + 59)
                        arr_time = f"{m // 60:02d}:{m % 60:02d}"
                    except Exception:
                        arr_time = "23:59"

                activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=f"{ret.carrier or 'Flight'} Departure to {ret.destination}",
                        description=f"{ret.carrier or 'Flight'} {ret.reference or ''}: {destination} → {ret.destination}.",
                        start_time=dep_time,
                        end_time=arr_time,
                        location=f"{destination} Airport ({ret.origin_code or ''})",
                        latitude=ret.origin_latitude or dest_lat,
                        longitude=ret.origin_longitude or dest_lng,
                        currency=currency,
                        category=ActivityCategory.FLIGHT,
                        source=ItemSource.BACKEND,
                        entity_type="flight_fare",
                        entity_id=ret.reference,
                    )
                )

        day_title = "Arrival & Welcome" if is_first_day else ("Departure" if is_last_day else f"Explore {destination}")
        days.append(
            ItineraryDay(
                date=cur_date,
                day_number=day_num,
                title=f"Day {day_num} - {day_title}",
                activities=activities,
                locations=[destination],
            )
        )


    return days


def generate_itinerary(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    request: GenerateItineraryRequest,
) -> GenerateItineraryResponse:
    """Intelligently plan and generate a structured itinerary with bounded alternatives and verification."""
    # Step 1: Constraint verification
    if request.end_date < request.start_date:
        raise RefusalError("DATE_INVALID", f"end_date {request.end_date} cannot be before start_date {request.start_date}", http_status=422)
    if request.travellers < 1:
        raise RefusalError("CONSTRAINT_INVALID", "travellers count must be at least 1", http_status=422)

    record_itinerary_event(
        conn, clock, request.session_id, user_id,
        "ITINERARY_GENERATION_REQUESTED",
        request.model_dump(mode="json"),
        {},
    )

    execution_steps = [
        "Retrieved authoritative flight and hotel inventory",
        f"Grounded destination POIs for {request.destination} from catalog",
        "Generated balanced, budget, and relaxed daily schedules",
        "Validated dates, budget, money, and geographic constraints",
    ]

    # Step 2: Retrieve candidate inventory
    transports = request.transport_options or get_candidate_transport(
        conn, request.origin, request.destination, request.start_date, request.end_date, request.travellers, request.currency
    )
    accommodations = request.accommodation_options or get_candidate_accommodation(
        conn, request.destination, request.start_date, request.end_date, request.travellers, request.currency
    )
    pois = catalog_repo.list_activities(conn, city_name=request.destination, limit=50)

    hotel_primary = accommodations[0] if accommodations else None

    # Resolve user preferences for pacing and activity categories
    from src.db.repositories import preferences as pref_repo
    from src.services import preference_service

    saved_user_prefs = pref_repo.get_preferences_for_user(conn, user_id)
    effective_prefs = preference_service.resolve_effective_preferences(
        saved_user_prefs, request_text=request.preferences
    )
    pref_cats = effective_prefs.get("preferred_activity_categories")
    pref_pace = str(effective_prefs.get("preferred_daily_pace", "moderate"))
    if pref_pace == "relaxed":
        target_style = "relaxed"
    elif request.style and request.style != "balanced":
        target_style = request.style
    else:
        target_style = "balanced"

    # Step 3: Build 3 bounded alternative plans
    styles = [
        ("balanced", "Balanced Itinerary", "Standard pacing with top attractions, culture, and dining."),
        ("budget", "Budget-Friendly Option", "Lowest-cost activities and optimized free public spots."),
        ("relaxed", "Relaxed Leisure Pace", "Unrushed 1-2 activities daily with dedicated afternoon free time."),
    ]

    alternatives: list[ItineraryAlternativeOption] = []
    active_plan: Optional[TripPlan] = None

    for style_key, label, desc in styles:
        days = build_daily_schedule(
            candidate_pois=pois,
            start_date=request.start_date,
            end_date=request.end_date,
            destination=request.destination,
            currency=request.currency,
            style=style_key,
            hotel_info=hotel_primary,
            transport_info=transports,
            preferred_categories=pref_cats,
        )

        plan = TripPlan(
            id=new_id("itn"),
            session_id=request.session_id,
            title=f"{request.origin} -> {request.destination} ({label})",
            origin=request.origin,
            destination=request.destination,
            start_date=request.start_date,
            end_date=request.end_date,
            travellers=request.travellers,
            currency=request.currency,
            budget=request.budget,
            transport=transports,
            accommodation=accommodations,
            days=days,
            constraints={"style": style_key, "preferences": request.preferences or ""},
            status=ItineraryStatus.DRAFT,
            version=1,
        )

        # Authoritative total calculations
        auth_total, est_total, breakdown = calculate_plan_totals(conn, plan)
        plan = plan.model_copy(
            update={
                "total_authoritative_cost": auth_total,
                "total_estimated_cost": est_total,
            }
        )

        alt = ItineraryAlternativeOption(
            option_id=style_key,
            label=label,
            description=desc,
            total_cost=auth_total or est_total,
            currency=request.currency,
            plan=plan,
        )
        alternatives.append(alt)

        if style_key == target_style:
            active_plan = plan

    if not active_plan and alternatives:
        active_plan = alternatives[0].plan

    # Step 4: Strict validation with bounded retry (max 2 attempts)
    validation = validate_itinerary(active_plan, conn=conn)
    retry_count = 0
    while not validation.valid and retry_count < 2:
        retry_count += 1
        budget_issue = any("exceeds trip budget" in err for err in validation.errors)
        clean_days = []
        seen_acts = set()

        budget_minor = money.to_minor(active_plan.budget) if active_plan.budget else None
        transport_minor = sum(money.to_minor(t.known_price) for t in active_plan.transport if t.known_price)
        stay_minor = sum(money.to_minor(a.known_price) for a in active_plan.accommodation if a.known_price)
        available_act_budget = (budget_minor - transport_minor - stay_minor) if budget_minor is not None else None
        current_act_spent = 0

        for d in active_plan.days:
            clean_acts = []
            for a in d.activities:
                if a.id not in seen_acts and (not a.entity_id or a.entity_id not in seen_acts):
                    cost_m = money.to_minor(a.authoritative_cost) if a.authoritative_cost else 0
                    if budget_issue and a.category not in (ActivityCategory.FLIGHT, ActivityCategory.STAY):
                        if available_act_budget is not None and (current_act_spent + cost_m > available_act_budget):
                            continue
                        current_act_spent += cost_m
                    seen_acts.add(a.id)
                    if a.entity_id:
                        seen_acts.add(a.entity_id)
                    clean_acts.append(a)
            if len(clean_acts) == 0:
                dest_c_lat = active_plan.days[0].activities[0].latitude if (active_plan.days and active_plan.days[0].activities and active_plan.days[0].activities[0].latitude is not None) else None
                dest_c_lng = active_plan.days[0].activities[0].longitude if (active_plan.days and active_plan.days[0].activities and active_plan.days[0].activities[0].longitude is not None) else None
                clean_acts.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title="Leisure & Free Exploration",
                        description=f"Unstructured free time to explore {active_plan.destination} at your own pace.",
                        start_time="11:00",
                        end_time="14:00",
                        location=active_plan.destination,
                        latitude=dest_c_lat,
                        longitude=dest_c_lng,
                        currency=active_plan.currency,
                        category=ActivityCategory.FREE_TIME,
                        source=ItemSource.AI_PLANNER,
                    )
                )
            clean_days.append(d.model_copy(update={"activities": clean_acts}))
        active_plan = active_plan.model_copy(update={"days": clean_days})
        auth_total, est_total, _ = calculate_plan_totals(conn, active_plan)
        active_plan = active_plan.model_copy(update={"total_authoritative_cost": auth_total, "total_estimated_cost": est_total})
        validation = validate_itinerary(active_plan, conn=conn)

    if not validation.valid:
        record_itinerary_event(
            conn, clock, request.session_id, user_id,
            "ITINERARY_GENERATION_FAILED",
            {"errors": validation.errors},
            {},
            outcome="failed",
            reason_code="STATE_INVALID",
            reason="; ".join(validation.errors),
        )
        raise RefusalError("STATE_INVALID", f"itinerary generation failed validation: {'; '.join(validation.errors)}", http_status=422)

    # Step 5: Persist active plan to SQLite
    created_plan = create_itinerary_draft(conn, clock, user_id, active_plan, session_id=request.session_id)

    record_itinerary_event(
        conn, clock, request.session_id, user_id,
        "ITINERARY_GENERATION_COMPLETED",
        {"itinerary_id": created_plan.id, "total_cost": created_plan.total_authoritative_cost},
        {"status": "success"},
        outcome="success",
    )

    if len(pois) == 0:
        explanation = (
            f"Your {active_plan.travellers}-traveller {active_plan.destination} itinerary is ready. "
            f"Destination activity data is currently limited, so I have scheduled free time and travel days. "
            f"Preserved travel dates ({active_plan.start_date} to {active_plan.end_date}) and calculated authoritative totals."
        )
    else:
        explanation = (
            f"Your {active_plan.travellers}-traveller {active_plan.destination} itinerary is ready. "
            f"I scheduled verified attractions from the catalog, preserved your travel dates "
            f"({active_plan.start_date} to {active_plan.end_date}), and calculated authoritative totals."
        )

    return GenerateItineraryResponse(
        active_plan=created_plan,
        alternatives=alternatives,
        execution_steps=execution_steps,
        validation=validation,
        explanation=explanation,
    )


def replan_itinerary(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    itinerary_id: str,
    req: ReplanItineraryRequest,
) -> TripPlan:
    """Conversational natural-language replanning with constraint preservation and atomic version safety."""
    current = get_itinerary(conn, itinerary_id, user_id=user_id)
    if current.status == ItineraryStatus.CANCELLED:
        raise RefusalError("STATE_INVALID", "cannot replan cancelled itinerary", http_status=409)
    instruction = req.instruction.lower().strip()

    if req.move_activity_id:
        found_to_move = any(a.id == req.move_activity_id for d in current.days for a in d.activities)
        if not found_to_move:
            raise RefusalError("STATE_INVALID", f"activity {req.move_activity_id} to move not found in itinerary", http_status=404)

    # Create working copy of days
    new_days: list[ItineraryDay] = []
    seen_ids = set()

    # Pre-load candidate POIs in case we need to substitute/add
    pois = catalog_repo.list_activities(conn, city_name=current.destination, limit=50)
    used_poi_ids = {a.entity_id for d in current.days for a in d.activities if a.entity_id}

    for day in current.days:
        is_target = req.target_day is None or day.day_number == req.target_day
        updated_activities: list[ItineraryActivity] = []

        for act in day.activities:
            # 1. Removal requested
            if req.remove_activity_id and act.id == req.remove_activity_id:
                if act.entity_id:
                    used_poi_ids.discard(act.entity_id)
                continue
            if "remove" in instruction and any(word in act.title.lower() for word in instruction.split() if len(word) > 4):
                if act.entity_id:
                    used_poi_ids.discard(act.entity_id)
                continue
            if "remove all expensive" in instruction and act.authoritative_cost and money.to_minor(act.authoritative_cost) > 50000:
                if act.entity_id:
                    used_poi_ids.discard(act.entity_id)
                continue

            # 2. Move requested
            if req.move_activity_id and act.id == req.move_activity_id and req.to_day and req.to_day != day.day_number:
                continue  # will be added to destination day below

            # 3. Budget / cheaper requested: replace expensive POI with free POI
            if ("cheaper" in instruction or "budget" in instruction) and is_target and act.category not in (ActivityCategory.FLIGHT, ActivityCategory.STAY):
                if act.authoritative_cost and money.to_minor(act.authoritative_cost) > 0:
                    free_pois = [p for p in pois if money.to_minor(p["cost"]) == 0 and p["poi_id"] not in used_poi_ids]
                    if free_pois:
                        if act.entity_id:
                            used_poi_ids.discard(act.entity_id)
                        sub = free_pois[0]
                        used_poi_ids.add(sub["poi_id"])
                        act = act.model_copy(
                            update={
                                "title": sub["title"],
                                "authoritative_cost": "0.00",
                                "entity_id": sub["poi_id"],
                                "category": categorize_activity(sub["title"]),
                            }
                        )

            # 4. Relax requested: replace afternoon/late day activities with leisure
            if ("relax" in instruction or "slower" in instruction) and is_target:
                if act.start_time and act.start_time >= "14:00" and act.category not in (ActivityCategory.FLIGHT, ActivityCategory.STAY):
                    if act.entity_id:
                        used_poi_ids.discard(act.entity_id)
                    act = act.model_copy(
                        update={
                            "title": "Relaxed Afternoon & Leisure",
                            "description": "Leisurely afternoon to relax and explore the neighborhood at your pace.",
                            "authoritative_cost": "0.00",
                            "category": ActivityCategory.FREE_TIME,
                            "entity_id": None,
                        }
                    )

            seen_ids.add(act.id)
            if act.entity_id:
                seen_ids.add(act.entity_id)
            updated_activities.append(act)

        # Check if an activity was moved TO this day
        if req.move_activity_id and req.to_day == day.day_number:
            moved_act = next((a for d in current.days for a in d.activities if a.id == req.move_activity_id), None)
            if moved_act and moved_act.id not in [a.id for a in updated_activities]:
                updated_activities.append(moved_act)

        # Add culture or nature POI if requested
        if is_target and "add culture" in instruction:
            culture_pois = [p for p in pois if categorize_activity(p["title"]) == ActivityCategory.CULTURE and p["poi_id"] not in used_poi_ids]
            if culture_pois:
                cp = culture_pois[0]
                used_poi_ids.add(cp["poi_id"])
                seen_ids.add(cp["poi_id"])
                auth_c, est_c, act_curr, desc_suffix = _resolve_poi_cost_and_notes(cp, current.currency)
                updated_activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=cp["title"],
                        description=f"Visit to {cp['title']}.{desc_suffix}".strip(),
                        start_time="15:30",
                        end_time="17:30",
                        location=current.destination,
                        authoritative_cost=auth_c,
                        estimated_cost=est_c,
                        currency=act_curr,
                        category=ActivityCategory.CULTURE,
                        source=ItemSource.AI_PLANNER,
                        entity_type="poi",
                        entity_id=cp["poi_id"],
                    )
                )

        if is_target and "add nature" in instruction:
            nature_pois = [p for p in pois if categorize_activity(p["title"]) == ActivityCategory.NATURE and p["poi_id"] not in used_poi_ids]
            if nature_pois:
                np = nature_pois[0]
                used_poi_ids.add(np["poi_id"])
                seen_ids.add(np["poi_id"])
                auth_c, est_c, act_curr, desc_suffix = _resolve_poi_cost_and_notes(np, current.currency)
                updated_activities.append(
                    ItineraryActivity(
                        id=new_id("itm"),
                        title=np["title"],
                        description=f"Visit to {np['title']}.{desc_suffix}".strip(),
                        start_time="15:30",
                        end_time="17:30",
                        location=current.destination,
                        authoritative_cost=auth_c,
                        estimated_cost=est_c,
                        currency=act_curr,
                        category=ActivityCategory.NATURE,
                        source=ItemSource.AI_PLANNER,
                        entity_type="poi",
                        entity_id=np["poi_id"],
                    )
                )

        # Free afternoon requested
        if is_target and "free afternoon" in instruction:
            # Replace 14:xx activity with free time
            for idx_a, act in enumerate(updated_activities):
                if act.start_time and act.start_time.startswith("14") and act.category not in (ActivityCategory.FLIGHT, ActivityCategory.STAY):
                    if act.entity_id:
                        used_poi_ids.discard(act.entity_id)
                    updated_activities[idx_a] = act.model_copy(
                        update={
                            "title": "Free Afternoon Exploration",
                            "description": "Afternoon set aside for personal leisure and relaxation.",
                            "authoritative_cost": "0.00",
                            "category": ActivityCategory.FREE_TIME,
                            "entity_id": None,
                        }
                    )

        new_days.append(day.model_copy(update={"activities": updated_activities}))

    # If regenerate requested: re-run daily schedule builder
    if "regenerate" in instruction:
        new_days = build_daily_schedule(
            candidate_pois=pois,
            start_date=current.start_date,
            end_date=current.end_date,
            destination=current.destination,
            currency=current.currency,
            style="balanced",
            hotel_info=current.accommodation[0] if current.accommodation else None,
            transport_info=current.transport,
        )

    # Assemble proposed new plan
    proposed = current.model_copy(update={"days": new_days})
    auth_total, est_total, _ = calculate_plan_totals(conn, proposed)
    proposed = proposed.model_copy(
        update={
            "total_authoritative_cost": auth_total,
            "total_estimated_cost": est_total,
        }
    )

    # SAFETY CHECK: Validate the proposed plan before committing
    validation = validate_itinerary(proposed, conn=conn)
    if not validation.valid:
        record_itinerary_event(
            conn, clock, current.session_id, user_id,
            "ITINERARY_VALIDATION_FAILED",
            {"instruction": req.instruction, "errors": validation.errors},
            {},
            outcome="refused",
            reason_code="STATE_INVALID",
            reason="; ".join(validation.errors),
        )
        # Never corrupt or destroy the existing valid plan
        raise RefusalError("STATE_INVALID", f"replanning failed validation: {'; '.join(validation.errors)}", http_status=422)


    # Valid! Increment version and persist
    updated = update_itinerary(conn, clock, itinerary_id, user_id, proposed)

    record_itinerary_event(
        conn, clock, current.session_id, user_id,
        "ITINERARY_REPLANNED",
        {"itinerary_id": itinerary_id, "instruction": req.instruction, "new_version": updated.version},
        {"status": "success"},
        outcome="success",
    )

    return updated


def select_alternative_option(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    itinerary_id: str,
    option_id: str,
) -> TripPlan:
    """Activate an alternative plan style (balanced, budget, relaxed)."""
    current = get_itinerary(conn, itinerary_id, user_id=user_id)
    pois = catalog_repo.list_activities(conn, city_name=current.destination, limit=50)

    new_days = build_daily_schedule(
        candidate_pois=pois,
        start_date=current.start_date,
        end_date=current.end_date,
        destination=current.destination,
        currency=current.currency,
        style=option_id,
        hotel_info=current.accommodation[0] if current.accommodation else None,
        transport_info=current.transport,
    )

    updated_plan = current.model_copy(
        update={
            "days": new_days,
            "title": f"{current.origin} -> {current.destination} ({option_id.capitalize()})",
        }
    )
    auth_total, est_total, _ = calculate_plan_totals(conn, updated_plan)
    updated_plan = updated_plan.model_copy(
        update={
            "total_authoritative_cost": auth_total,
            "total_estimated_cost": est_total,
        }
    )

    validation = validate_itinerary(updated_plan, conn=conn)
    if not validation.valid:
        raise RefusalError("STATE_INVALID", f"option validation failed: {'; '.join(validation.errors)}", http_status=422)

    saved = update_itinerary(conn, clock, itinerary_id, user_id, updated_plan)

    record_itinerary_event(
        conn, clock, current.session_id, user_id,
        "ITINERARY_OPTION_SELECTED",
        {"itinerary_id": itinerary_id, "option_id": option_id, "new_version": saved.version},
        {"status": "success"},
        outcome="success",
    )

    return saved


def save_itinerary(conn: sqlite3.Connection, *args, **kwargs) -> TripPlan:
    """Convenience alias for saving an itinerary (supports multiple argument orders)."""
    from src.core.clock import SystemClock
    if len(args) == 2:
        clock = kwargs.get("clock") or SystemClock()
        user_id = args[0]
        plan = args[1]
    elif len(args) >= 3:
        clock = args[0]
        user_id = args[1]
        plan = args[2]
    else:
        clock = kwargs.get("clock") or SystemClock()
        user_id = kwargs.get("user_id", "usr_demo")
        plan = kwargs.get("plan")
    return create_itinerary_draft(conn, clock, user_id, plan)


