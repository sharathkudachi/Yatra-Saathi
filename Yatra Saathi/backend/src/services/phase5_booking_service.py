"""Phase 5 Booking Lifecycle, Trip Management & Travel Document Service.

Authoritative backend service for:
- Booking-ready itinerary validation & review calculation
- Inventory hold simulation & expiration handling
- Simulated booking confirmation with idempotency
- Trip lifecycle management & My Trips queries
- Trip cancellation with safety checks and release of holds
- Bounded Trip Pack generation & export
- Full audit event logging

Strict Invariants:
1. All prices and totals are authoritative, recalculated by backend; no frontend totals trusted.
2. AI may read but NEVER mutate booking state directly.
3. Explicit human confirmation required for final booking.
4. Demo reservations only — no real payments or real supplier reservations.
5. Strict resource ownership: User A can never access or modify User B's resources.
6. Booking references are backend-generated: YTR-DEMO-XXXXXXXX.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from src.contracts.codes import RefusalError
from src.core import money
from src.core.clock import Clock
from src.core.dates import parse_date_only
from src.core.ids import new_booking_reference, new_id
from src.db.repositories import phase5_booking as p5_repo
from src.db.unit_of_work import transaction
from src.schemas.booking import (
    BookingItemSummary,
    BookingReviewRequest,
    BookingReviewResponse,
    BookingStatus,
    BookingStatusResponse,
    BookingTravellerInfo,
    CancelBookingRequest,
    CancelBookingResponse,
    ConfirmBookingRequest,
    ConfirmBookingResponse,
    HoldStatus,
    TripDetailResponse,
    TripLifecycleStatus,
    TripPackResponse,
)
from src.schemas.itinerary import ItineraryStatus, TripPlan
from src.services import itinerary_service

HMAC_SECRET = b"yatra-phase5-review-hmac-secret-key-2026"
HOLD_TTL_MINUTES = 15


# ============================================================
# Token Helpers (Review Token Signing & Verification)
# ============================================================

def _generate_review_token(
    *,
    itinerary_id: str,
    itinerary_version: int,
    authoritative_total: str,
    currency: str,
    expires_at_iso: str,
) -> str:
    """Creates a tamper-proof review token binding itinerary, version, total, and expiry."""
    payload_str = f"{itinerary_id}|{itinerary_version}|{authoritative_total}|{currency}|{expires_at_iso}"
    sig = hmac.new(HMAC_SECRET, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(payload_str.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"rev_{encoded}_{sig[:16]}"


def _verify_review_token(
    token: str,
    clock: Clock,
) -> dict[str, Any]:
    """Verifies review token integrity and expiration. Returns parsed payload dict."""
    if not token or not token.startswith("rev_"):
        raise RefusalError("INVALID_BOOKING_STATE", "Invalid review token format", http_status=400)

    parts = token[4:].rsplit("_", 1)
    if len(parts) != 2:
        raise RefusalError("INVALID_BOOKING_STATE", "Malformed review token", http_status=400)

    encoded, sig = parts
    # Pad base64
    pad = len(encoded) % 4
    if pad:
        encoded += "=" * (4 - pad)

    try:
        payload_str = base64.urlsafe_b64decode(encoded.encode("utf-8")).decode("utf-8")
    except Exception:
        raise RefusalError("INVALID_BOOKING_STATE", "Invalid review token encoding", http_status=400)

    expected_sig = hmac.new(HMAC_SECRET, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected_sig):
        raise RefusalError("INVALID_BOOKING_STATE", "Review token signature verification failed", http_status=400)

    fields = payload_str.split("|")
    if len(fields) != 5:
        raise RefusalError("INVALID_BOOKING_STATE", "Malformed token contents", http_status=400)

    itinerary_id, version_str, total, currency, expires_at_iso = fields

    # Expiry check
    try:
        exp_dt = datetime.fromisoformat(expires_at_iso)
        current_dt = datetime.fromisoformat(clock.utc())
        if current_dt > exp_dt:
            raise RefusalError("HOLD_EXPIRED", "Booking review has expired. Please review again.", http_status=409)
    except (ValueError, TypeError) as exc:
        if isinstance(exc, RefusalError):
            raise
        raise RefusalError("INVALID_BOOKING_STATE", "Invalid expiry in review token", http_status=400)

    return {
        "itinerary_id": itinerary_id,
        "itinerary_version": int(version_str),
        "authoritative_total": total,
        "currency": currency,
        "expires_at": expires_at_iso,
    }


# ============================================================
# Recalculation & Validation Core
# ============================================================

def _money_add(a: str, b: str) -> str:
    return money.format_minor(money.to_minor(a) + money.to_minor(b))


def _money_div_floor(a: str, divisor: int) -> str:
    if divisor <= 0:
        return a
    return money.format_minor(money.to_minor(a) // divisor)


def _money_tax(subtotal: str, rate_bp: int = 1200) -> str:
    return money.format_minor(money.tax_minor(money.to_minor(subtotal), rate_bp))


def _recalculate_authoritative_costs(
    conn: sqlite3.Connection,
    itinerary: TripPlan,
) -> tuple[str, str, str, str, str, str, str, list[BookingItemSummary]]:
    """Recalculates transport total, accommodation total, authoritative activities,
    estimated activities, taxes, and authoritative total from authoritative catalog/inventory data.
    Never trusts totals from client or cache.
    """
    currency = itinerary.currency
    transport_total = "0.00"
    accommodation_total = "0.00"
    authoritative_activities_total = "0.00"
    estimated_activities_total = "0.00"
    items: list[BookingItemSummary] = []

    # 1. Transport items (flights / trains)
    for seg in itinerary.transport:
        # Check segment cost
        seg_cost = seg.known_price or "0.00"
        if seg.currency != currency:
            raise RefusalError("CURRENCY_MISMATCH", f"Transport currency {seg.currency} != {currency}", http_status=400)

        # Check inventory calendar if flight_fare entity_id or reference is available
        fare_id = getattr(seg, "entity_id", None) or getattr(seg, "reference", None)
        dep_date = seg.departs_at[:10] if seg.departs_at else itinerary.start_date.isoformat()
        if fare_id:
            inv_row = conn.execute(
                """SELECT ic.price,
                          (ic.total_units - ic.booked_units -
                           COALESCE((SELECT SUM(h.units) FROM holds h WHERE h.inventory_id = ic.inventory_id AND h.status = 'active'), 0)
                          ) AS available
                   FROM inventory_calendar ic
                   WHERE ic.entity_type = 'flight_fare' AND ic.entity_id = ? AND ic.for_date = ? AND ic.currency = ?""",
                (fare_id, dep_date, currency),
            ).fetchone()
            if inv_row:
                if inv_row["available"] < itinerary.travellers:
                    raise RefusalError("INVENTORY_UNAVAILABLE", f"Flight {seg.carrier or ''} has insufficient inventory", http_status=409)
                per_person_minor = money.to_minor(inv_row["price"])
                seg_cost = money.format_minor(per_person_minor * itinerary.travellers)

        transport_total = _money_add(transport_total, seg_cost)
        carrier = seg.carrier or "Flight"
        ref = seg.reference or ""
        items.append(
            BookingItemSummary(
                item_type="flight" if seg.type.value == "flight" else "transport",
                title=f"{carrier} ({ref}): {seg.origin} -> {seg.destination}".strip() if ref else f"{carrier}: {seg.origin} -> {seg.destination}",
                entity_type="flight_fare",
                entity_id=fare_id or seg.id,
                for_date=dep_date,
                quantity=itinerary.travellers,
                authoritative_price=seg_cost,
                estimated_price=None,
                currency=currency,
                is_authoritative=True,
            )
        )

    # 2. Accommodation items (hotels / stays)
    for stay in itinerary.accommodation:
        stay_cost = stay.known_price or "0.00"
        if stay.currency != currency:
            raise RefusalError("CURRENCY_MISMATCH", f"Accommodation currency {stay.currency} != {currency}", http_status=400)

        # Nights count
        nights = (stay.check_out_date - stay.check_in_date).days
        if nights < 1:
            nights = 1

        # Check inventory if room_type_id is available
        room_type_id = stay.room_type_id or getattr(stay, "entity_id", None)
        if room_type_id:
            curr_date = stay.check_in_date
            total_room_cost = "0.00"
            for _ in range(nights):
                d_str = curr_date.isoformat()
                inv_row = conn.execute(
                    """SELECT ic.price,
                              (ic.total_units - ic.booked_units -
                               COALESCE((SELECT SUM(h.units) FROM holds h WHERE h.inventory_id = ic.inventory_id AND h.status = 'active'), 0)
                              ) AS available
                       FROM inventory_calendar ic
                       WHERE ic.entity_type = 'room_type' AND ic.entity_id = ? AND ic.for_date = ? AND ic.currency = ?""",
                    (room_type_id, d_str, currency),
                ).fetchone()
                if inv_row:
                    if inv_row["available"] < 1:
                        raise RefusalError("INVENTORY_UNAVAILABLE", f"Hotel {stay.hotel_name} has no availability for {d_str}", http_status=409)
                    total_room_cost = _money_add(total_room_cost, inv_row["price"])
                else:
                    # fallback to per-night proportional cost
                    night_price = _money_div_floor(stay.known_price or "0.00", nights)
                    total_room_cost = _money_add(total_room_cost, night_price)
                curr_date += timedelta(days=1)
            stay_cost = total_room_cost if total_room_cost != "0.00" else (stay.known_price or "0.00")

        accommodation_total = _money_add(accommodation_total, stay_cost)
        items.append(
            BookingItemSummary(
                item_type="hotel",
                title=f"{stay.hotel_name} ({stay.room_name or 'Standard Room'}, {nights} nights)",
                entity_type="room_type" if room_type_id else "hotel",
                entity_id=room_type_id or stay.hotel_id or stay.id,
                for_date=stay.check_in_date.isoformat(),
                quantity=1,
                authoritative_price=stay_cost,
                estimated_price=None,
                currency=currency,
                is_authoritative=True,
            )
        )

    # 3. Activities
    for day in itinerary.days:
        for act in day.activities:
            if act.currency != currency:
                raise RefusalError("CURRENCY_MISMATCH", f"Activity currency {act.currency} != {currency}", http_status=400)

            if act.authoritative_cost:
                authoritative_activities_total = _money_add(authoritative_activities_total, act.authoritative_cost)
                items.append(
                    BookingItemSummary(
                        item_type="activity",
                        title=act.title,
                        entity_type=act.entity_type or "poi",
                        entity_id=act.entity_id or act.id,
                        for_date=day.date.isoformat(),
                        quantity=1,
                        authoritative_price=act.authoritative_cost,
                        estimated_price=None,
                        currency=currency,
                        is_authoritative=True,
                    )
                )
            elif act.estimated_cost and act.estimated_cost != "0.00":
                estimated_activities_total = _money_add(estimated_activities_total, act.estimated_cost)
                items.append(
                    BookingItemSummary(
                        item_type="activity",
                        title=act.title,
                        entity_type=act.entity_type or "poi",
                        entity_id=act.entity_id or act.id,
                        for_date=day.date.isoformat(),
                        quantity=1,
                        authoritative_price=None,
                        estimated_price=act.estimated_cost,
                        currency=currency,
                        is_authoritative=False,
                    )
                )

    # Authoritative Subtotal: Transport + Accommodation + Authoritative Activities
    authoritative_subtotal = _money_add(
        transport_total,
        _money_add(accommodation_total, authoritative_activities_total),
    )

    # 12% standard tax (1200 basis points) on authoritative subtotal
    tax_amount = _money_tax(authoritative_subtotal, 1200)

    # Authoritative Total
    authoritative_total = _money_add(authoritative_subtotal, tax_amount)

    return (
        transport_total,
        accommodation_total,
        authoritative_activities_total,
        estimated_activities_total,
        authoritative_subtotal,
        tax_amount,
        authoritative_total,
        items,
    )


# ============================================================
# Service API: Review, Hold, Confirm, Status, Cancel, Trips
# ============================================================

def create_booking_review(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    request: BookingReviewRequest,
) -> BookingReviewResponse:
    """Generates a booking review for an existing itinerary.
    Recalculates all authoritative totals from scratch.
    """
    # 1. Fetch itinerary and verify ownership
    try:
        itinerary = itinerary_service.get_itinerary(conn, request.itinerary_id, user_id=user_id)
    except RefusalError as exc:
        if exc.code == "SESSION_ACCESS_DENIED":
            raise RefusalError("BOOKING_OWNERSHIP_DENIED", "Access denied to itinerary", http_status=403) from exc
        raise RefusalError("ITINERARY_NOT_BOOKABLE", f"Itinerary not found or not bookable: {exc}", http_status=404) from exc

    # 2. Check bookability
    if itinerary.status == ItineraryStatus.CANCELLED:
        raise RefusalError("ITINERARY_NOT_BOOKABLE", "Cancelled itinerary cannot be booked", http_status=400)

    # 3. Version safety check
    if itinerary.version != request.itinerary_version:
        raise RefusalError(
            "ITINERARY_VERSION_CHANGED",
            f"Itinerary version changed from {request.itinerary_version} to {itinerary.version}",
            http_status=409,
        )

    # 4. Traveller validation
    if not request.travellers:
        raise RefusalError("INVALID_BOOKING_STATE", "At least one traveller is required", http_status=400)

    # 5. Recalculate costs
    (
        transport_total,
        accommodation_total,
        auth_activities_total,
        estimated_activities_total,
        authoritative_subtotal,
        tax_amount,
        authoritative_total,
        items,
    ) = _recalculate_authoritative_costs(conn, itinerary)

    # 6. Budget cap check
    if itinerary.budget:
        if money.to_minor(authoritative_total) > money.to_minor(itinerary.budget):
            raise RefusalError(
                "BUDGET_EXCEEDED",
                f"Authoritative total {authoritative_total} {itinerary.currency} exceeds budget of {itinerary.budget} {itinerary.currency}",
                http_status=400,
            )

    # 7. Expiration
    now_dt = datetime.fromisoformat(clock.utc())
    expires_dt = now_dt + timedelta(minutes=HOLD_TTL_MINUTES)
    expires_at_iso = expires_dt.isoformat()

    # 8. Token creation
    review_token = _generate_review_token(
        itinerary_id=itinerary.id,
        itinerary_version=itinerary.version,
        authoritative_total=authoritative_total,
        currency=itinerary.currency,
        expires_at_iso=expires_at_iso,
    )

    # 9. Audit event
    event_id = new_id("p5e")
    # Record review audit
    conn.execute(
        """INSERT INTO phase5_booking_events
           (event_id, booking_id, user_id, event_type, occurred_at, actor, prev_status, new_status, metadata_json)
           VALUES (?, ?, ?, 'BOOKING_REVIEW_VALIDATED', ?, 'user', NULL, 'ready_for_confirmation', ?)""",
        (
            event_id,
            itinerary.id,  # reference itinerary for pre-booking review
            user_id,
            clock.utc(),
            json.dumps({
                "itinerary_id": itinerary.id,
                "version": itinerary.version,
                "authoritative_total": authoritative_total,
                "currency": itinerary.currency,
                "traveller_count": len(request.travellers),
            }),
        ),
    )

    return BookingReviewResponse(
        review_token=review_token,
        itinerary_id=itinerary.id,
        itinerary_version=itinerary.version,
        destination=itinerary.destination,
        origin=itinerary.origin,
        start_date=itinerary.start_date.isoformat(),
        end_date=itinerary.end_date.isoformat(),
        travellers=request.travellers,
        traveller_count=len(request.travellers),
        items=items,
        transport_total=transport_total,
        accommodation_total=accommodation_total,
        estimated_activities_total=estimated_activities_total,
        authoritative_subtotal=authoritative_subtotal,
        tax_amount=tax_amount,
        authoritative_total=authoritative_total,
        currency=itinerary.currency,
        booking_mode="DEMO / SIMULATED",
        demo_label="DEMO BOOKING — NO REAL PAYMENT",
        review_expires_at=expires_at_iso,
    )


def create_inventory_hold(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    *,
    review_token: str,
    itinerary_id: str,
    itinerary_version: int,
) -> dict[str, Any]:
    """Creates a simulated inventory hold for the reviewable trip components."""
    token_data = _verify_review_token(review_token, clock)
    if token_data["itinerary_id"] != itinerary_id or token_data["itinerary_version"] != itinerary_version:
        raise RefusalError("INVALID_BOOKING_STATE", "Review token does not match itinerary or version", http_status=400)

    itinerary = itinerary_service.get_itinerary(conn, itinerary_id, user_id=user_id)
    if itinerary.version != itinerary_version:
        raise RefusalError("ITINERARY_VERSION_CHANGED", "Itinerary version changed", http_status=409)

    now_iso = clock.utc()
    expires_at = token_data["expires_at"]
    hold_id = new_id("hld")

    # Log audit event
    conn.execute(
        """INSERT INTO phase5_booking_events
           (event_id, booking_id, user_id, event_type, occurred_at, actor, prev_status, new_status, metadata_json)
           VALUES (?, ?, ?, 'INVENTORY_HOLD_CREATED', ?, 'system', 'ready_for_confirmation', 'holding', ?)""",
        (
            new_id("aud"),
            itinerary_id,
            user_id,
            now_iso,
            json.dumps({"hold_id": hold_id, "expires_at": expires_at}),
        ),
    )

    return {
        "hold_id": hold_id,
        "status": "active",
        "created_at": now_iso,
        "expires_at": expires_at,
        "itinerary_id": itinerary_id,
        "itinerary_version": itinerary_version,
    }


def confirm_booking(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    request: ConfirmBookingRequest,
) -> ConfirmBookingResponse:
    """Explicit booking confirmation endpoint.
    Guarantees:
    - Idempotency on idempotency_key
    - Cryptographic verification of review_token
    - Total / currency consistency
    - Fresh itinerary version match
    - Backend-generated demo reference (YTR-DEMO-XXXXXXXX)
    - Full transaction safety and audit events
    """
    # 1. Idempotency Check
    existing_row = conn.execute(
        "SELECT * FROM bookings WHERE idempotency_key = ?",
        (request.idempotency_key,),
    ).fetchone()
    if existing_row:
        # Check ownership
        if existing_row["user_id"] != user_id:
            raise RefusalError("BOOKING_OWNERSHIP_DENIED", "Idempotency key owned by another user", http_status=403)
        # Idempotent response: return existing booking
        items_rows = conn.execute(
            "SELECT * FROM booking_items WHERE booking_id = ? AND status = 'active'",
            (existing_row["booking_id"],),
        ).fetchall()
        items = [
            BookingItemSummary(
                item_type=r["entity_type"],
                title=r["title"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                for_date=r["for_date"],
                quantity=r["units"],
                authoritative_price=r["line_total"],
                currency=r["currency"],
                is_authoritative=True,
            )
            for r in items_rows
        ]
        return ConfirmBookingResponse(
            booking_id=existing_row["booking_id"],
            booking_reference=existing_row["booking_reference"],
            status=existing_row["status"],
            lifecycle_status=existing_row["lifecycle_status"],
            itinerary_id=existing_row["itinerary_id"],
            itinerary_version=existing_row["itinerary_version"] or request.itinerary_version,
            authoritative_total=existing_row["total_amount"],
            currency=existing_row["currency"],
            created_at=existing_row["created_at"],
            booking_mode="DEMO / SIMULATED",
            demo_label="Yatra Saathi demo reservation has been confirmed. This is a simulated booking.",
            items=items,
        )

    # 2. Verify review token
    token_data = _verify_review_token(request.review_token, clock)

    if token_data["itinerary_id"] != request.itinerary_id:
        raise RefusalError("INVALID_BOOKING_STATE", "Review token itinerary ID mismatch", http_status=400)
    if token_data["itinerary_version"] != request.itinerary_version:
        raise RefusalError("ITINERARY_VERSION_CHANGED", "Itinerary version changed since review", http_status=409)
    if token_data["currency"] != request.currency:
        raise RefusalError("CURRENCY_MISMATCH", "Review currency mismatch", http_status=400)
    if token_data["authoritative_total"] != request.authoritative_total:
        raise RefusalError("BOOKING_TOTAL_CHANGED", "Authoritative total changed since review", http_status=409)

    # 3. Fetch itinerary and verify ownership
    itinerary = itinerary_service.get_itinerary(conn, request.itinerary_id, user_id=user_id)
    if itinerary.status == ItineraryStatus.CANCELLED:
        raise RefusalError("ITINERARY_NOT_BOOKABLE", "Cannot confirm booking on cancelled itinerary", http_status=400)
    if itinerary.version != request.itinerary_version:
        raise RefusalError("ITINERARY_VERSION_CHANGED", f"Itinerary version changed to {itinerary.version}", http_status=409)

    # 4. Live recalculation to prevent price drift / race conditions
    (
        transport_total,
        accommodation_total,
        auth_activities_total,
        estimated_activities_total,
        authoritative_subtotal,
        tax_amount,
        recalculated_total,
        items,
    ) = _recalculate_authoritative_costs(conn, itinerary)

    if recalculated_total != request.authoritative_total:
        raise RefusalError(
            "BOOKING_TOTAL_CHANGED",
            f"Live rate changed: current {recalculated_total} != confirmed {request.authoritative_total}",
            http_status=409,
        )

    # 5. Execute booking in transaction
    now_iso = clock.utc()
    booking_id = new_id("bkg")
    booking_reference = new_booking_reference()

    with transaction(conn):
        # Insert booking
        conn.execute(
            """INSERT INTO bookings (
                booking_id, user_id, trip_id, itinerary_id, itinerary_version,
                booking_reference, channel, total_amount, currency, tax_amount,
                idempotency_key, status, lifecycle_status, booking_mode, demo_label,
                confirmed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'web', ?, ?, ?, ?, 'confirmed', 'confirmed', 'demo', 'DEMO / SIMULATED', ?, ?, ?)""",
            (
                booking_id,
                user_id,
                itinerary.trip_id,
                itinerary.id,
                itinerary.version,
                booking_reference,
                recalculated_total,
                itinerary.currency,
                tax_amount,
                request.idempotency_key,
                now_iso,
                now_iso,
                now_iso,
            ),
        )

        # Insert booking items
        for itm in items:
            item_id = new_id("bit")
            conn.execute(
                """INSERT INTO booking_items (
                    booking_item_id, booking_id, entity_type, entity_id, title,
                    for_date, units, unit_price, line_total, currency, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
                (
                    item_id,
                    booking_id,
                    itm.item_type,
                    itm.entity_id or item_id,
                    itm.title,
                    itm.for_date,
                    itm.quantity,
                    itm.authoritative_price or "0.00",
                    itm.authoritative_price or "0.00",
                    itm.currency,
                    now_iso,
                ),
            )

        # Insert travellers
        for seq, trv in enumerate(request.travellers, start=1):
            traveller_id = new_id("btv")
            conn.execute(
                """INSERT INTO booking_travellers (
                    traveller_id, booking_id, traveller_seq, display_name, traveller_role, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    traveller_id,
                    booking_id,
                    seq,
                    trv.display_name,
                    trv.traveller_role,
                    now_iso,
                ),
            )

        # Write audit event
        conn.execute(
            """INSERT INTO phase5_booking_events (
                event_id, booking_id, user_id, event_type, occurred_at, actor,
                prev_status, new_status, metadata_json
            ) VALUES (?, ?, ?, 'DEMO_BOOKING_CONFIRMED', ?, 'user', 'holding', 'confirmed', ?)""",
            (
                new_id("aud"),
                booking_id,
                user_id,
                now_iso,
                json.dumps({
                    "booking_reference": booking_reference,
                    "authoritative_total": recalculated_total,
                    "currency": itinerary.currency,
                    "itinerary_id": itinerary.id,
                    "itinerary_version": itinerary.version,
                    "travellers": len(request.travellers),
                }),
            ),
        )

    return ConfirmBookingResponse(
        booking_id=booking_id,
        booking_reference=booking_reference,
        status="confirmed",
        lifecycle_status="confirmed",
        itinerary_id=itinerary.id,
        itinerary_version=itinerary.version,
        authoritative_total=recalculated_total,
        currency=itinerary.currency,
        created_at=now_iso,
        booking_mode="DEMO / SIMULATED",
        demo_label="Yatra Saathi demo reservation has been confirmed. This is a simulated booking.",
        items=items,
    )


def get_booking_status(
    conn: sqlite3.Connection,
    user_id: str,
    booking_id: str,
) -> BookingStatusResponse:
    """Retrieves full status and timeline for a booking with strict ownership validation."""
    booking_row = conn.execute(
        "SELECT * FROM bookings WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()

    if not booking_row:
        raise RefusalError("BOOKING_NOT_FOUND", f"Booking {booking_id} not found", http_status=404)

    if booking_row["user_id"] != user_id:
        raise RefusalError("BOOKING_OWNERSHIP_DENIED", "Access denied to booking", http_status=403)

    items_rows = conn.execute(
        "SELECT * FROM booking_items WHERE booking_id = ?",
        (booking_id,),
    ).fetchall()

    items = [
        BookingItemSummary(
            item_type=r["entity_type"],
            title=r["title"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            for_date=r["for_date"],
            quantity=r["units"],
            authoritative_price=r["line_total"],
            currency=r["currency"],
            is_authoritative=True,
        )
        for r in items_rows
    ]

    # Destination / dates from trip or itinerary
    dest, orig, start_d, end_d = None, None, None, None
    if booking_row["itinerary_id"]:
        itin_row = conn.execute(
            """SELECT t.start_date, t.end_date, cd.name AS destination, co.name AS origin
               FROM itineraries i
               JOIN trips t ON t.trip_id = i.trip_id
               LEFT JOIN cities cd ON cd.city_id = t.destination_city_id
               LEFT JOIN cities co ON co.city_id = t.origin_city_id
               WHERE i.itinerary_id = ?""",
            (booking_row["itinerary_id"],),
        ).fetchone()
        if itin_row:
            dest = itin_row["destination"]
            orig = itin_row["origin"]
            start_d = itin_row["start_date"]
            end_d = itin_row["end_date"]

    return BookingStatusResponse(
        booking_id=booking_row["booking_id"],
        booking_reference=booking_row["booking_reference"],
        status=booking_row["status"],
        lifecycle_status=booking_row["lifecycle_status"],
        itinerary_id=booking_row["itinerary_id"],
        itinerary_version=booking_row["itinerary_version"],
        destination=dest,
        start_date=start_d,
        end_date=end_d,
        authoritative_total=booking_row["total_amount"],
        currency=booking_row["currency"],
        created_at=booking_row["created_at"],
        updated_at=booking_row["updated_at"],
        cancelled_at=booking_row["cancelled_at"],
        cancellation_reason=booking_row["cancellation_reason"],
        booking_mode=booking_row["booking_mode"] or "DEMO / SIMULATED",
        demo_label=booking_row["demo_label"] or "DEMO / SIMULATED",
        items=items,
    )


def cancel_booking(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    booking_id: str,
    request: CancelBookingRequest,
) -> CancelBookingResponse:
    """Cancels a booking safely.
    Guarantees:
    - Ownership validation (User A cannot cancel User B's booking)
    - Idempotency (cancelling an already-cancelled booking returns success without error)
    - Release of any active holds
    - Audit event logging
    """
    booking_row = conn.execute(
        "SELECT * FROM bookings WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()

    if not booking_row:
        raise RefusalError("BOOKING_NOT_FOUND", f"Booking {booking_id} not found", http_status=404)

    if booking_row["user_id"] != user_id:
        raise RefusalError("BOOKING_OWNERSHIP_DENIED", "Access denied to booking", http_status=403)

    # Idempotency check: if already cancelled, return existing cancelled state
    if booking_row["status"] == "cancelled":
        return CancelBookingResponse(
            booking_id=booking_id,
            booking_reference=booking_row["booking_reference"],
            status="cancelled",
            cancelled_at=booking_row["cancelled_at"] or clock.utc(),
            cancellation_reason=booking_row["cancellation_reason"],
            message="Your Yatra Saathi demo booking has been cancelled.",
        )

    # Validate state transition
    if booking_row["status"] not in ("confirmed", "holding", "draft", "ready_for_confirmation"):
        raise RefusalError(
            "CANCELLATION_NOT_ALLOWED",
            f"Cannot cancel booking with status '{booking_row['status']}'",
            http_status=400,
        )

    now_iso = clock.utc()
    with transaction(conn):
        # Update booking
        conn.execute(
            """UPDATE bookings
               SET status = 'cancelled', lifecycle_status = 'cancelled',
                   cancelled_at = ?, cancellation_reason = ?, updated_at = ?
               WHERE booking_id = ?""",
            (now_iso, request.reason, now_iso, booking_id),
        )

        # Cancel items
        conn.execute(
            "UPDATE booking_items SET status = 'cancelled', updated_at = ? WHERE booking_id = ?",
            (now_iso, booking_id),
        )

        # Release any holds associated with this booking
        conn.execute(
            "UPDATE holds SET status = 'released', released_at = ?, updated_at = ? WHERE booking_id = ? AND status = 'active'",
            (now_iso, now_iso, booking_id),
        )

        # Write audit event
        conn.execute(
            """INSERT INTO phase5_booking_events (
                event_id, booking_id, user_id, event_type, occurred_at, actor,
                prev_status, new_status, metadata_json
            ) VALUES (?, ?, ?, 'DEMO_BOOKING_CANCELLED', ?, 'user', ?, 'cancelled', ?)""",
            (
                new_id("aud"),
                booking_id,
                user_id,
                now_iso,
                booking_row["status"],
                json.dumps({"reason": request.reason}),
            ),
        )

    return CancelBookingResponse(
        booking_id=booking_id,
        booking_reference=booking_row["booking_reference"],
        status="cancelled",
        cancelled_at=now_iso,
        cancellation_reason=request.reason,
        message="Your Yatra Saathi demo booking has been cancelled.",
    )


def list_user_trips(
    conn: sqlite3.Connection,
    user_id: str,
) -> list[dict[str, Any]]:
    """Lists all confirmed, active, and past bookings for the authenticated user (My Trips).
    Guarantees strict user isolation.
    """
    bookings_rows = conn.execute(
        """SELECT b.*,
                  (SELECT cd.name FROM trips t JOIN cities cd ON cd.city_id = t.destination_city_id WHERE t.trip_id = b.trip_id) AS destination,
                  (SELECT co.name FROM trips t JOIN cities co ON co.city_id = t.origin_city_id WHERE t.trip_id = b.trip_id) AS origin,
                  (SELECT t.start_date FROM trips t WHERE t.trip_id = b.trip_id) AS start_date,
                  (SELECT t.end_date FROM trips t WHERE t.trip_id = b.trip_id) AS end_date,
                  (SELECT COUNT(*) FROM booking_travellers bt WHERE bt.booking_id = b.booking_id) AS traveller_count,
                  (SELECT COUNT(*) FROM booking_items bi WHERE bi.booking_id = b.booking_id) AS item_count
           FROM bookings b
           WHERE b.user_id = ?
           ORDER BY b.created_at DESC""",
        (user_id,),
    ).fetchall()

    trips = []
    for r in bookings_rows:
        trips.append({
            "booking_id": r["booking_id"],
            "booking_reference": r["booking_reference"],
            "itinerary_id": r["itinerary_id"],
            "itinerary_version": r["itinerary_version"],
            "status": r["status"],
            "lifecycle_status": r["lifecycle_status"],
            "destination": r["destination"] or "Travel Destination",
            "origin": r["origin"] or "Origin",
            "start_date": r["start_date"] or r["created_at"][:10],
            "end_date": r["end_date"] or r["created_at"][:10],
            "traveller_count": r["traveller_count"] or 1,
            "item_count": r["item_count"] or 0,
            "total_amount": r["total_amount"],
            "currency": r["currency"],
            "booking_mode": r["booking_mode"] or "DEMO / SIMULATED",
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "cancelled_at": r["cancelled_at"],
        })
    return trips


def get_trip_detail(
    conn: sqlite3.Connection,
    user_id: str,
    booking_id: str,
) -> TripDetailResponse:
    """Full detail view for a trip booking, including transport, hotel, itinerary and events."""
    booking_row = conn.execute(
        "SELECT * FROM bookings WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()

    if not booking_row:
        raise RefusalError("TRIP_NOT_FOUND", f"Trip booking {booking_id} not found", http_status=404)

    if booking_row["user_id"] != user_id:
        raise RefusalError("TRIP_OWNERSHIP_DENIED", "Access denied to trip", http_status=403)

    # Fetch items
    items_rows = conn.execute(
        "SELECT * FROM booking_items WHERE booking_id = ?",
        (booking_id,),
    ).fetchall()
    items = [
        BookingItemSummary(
            item_type=r["entity_type"],
            title=r["title"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            for_date=r["for_date"],
            quantity=r["units"],
            authoritative_price=r["line_total"],
            currency=r["currency"],
            is_authoritative=True,
        )
        for r in items_rows
    ]

    # Travellers count
    trv_count = conn.execute(
        "SELECT COUNT(*) FROM booking_travellers WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()[0]

    # Fetch Itinerary details
    itinerary_plan = None
    dest, orig, start_d, end_d = "Travel Destination", "Origin", "2026-05-01", "2026-05-05"
    if booking_row["itinerary_id"]:
        try:
            itinerary_plan = itinerary_service.get_itinerary(conn, booking_row["itinerary_id"], user_id=user_id)
            dest = itinerary_plan.destination
            orig = itinerary_plan.origin
            start_d = itinerary_plan.start_date.isoformat()
            end_d = itinerary_plan.end_date.isoformat()
        except Exception:
            pass

    # Timeline events
    event_rows = conn.execute(
        "SELECT event_id, event_type, occurred_at, actor, prev_status, new_status, metadata_json "
        "FROM phase5_booking_events WHERE booking_id = ? ORDER BY occurred_at ASC",
        (booking_id,),
    ).fetchall()
    timeline = [
        {
            "event_id": ev["event_id"],
            "event_type": ev["event_type"],
            "occurred_at": ev["occurred_at"],
            "actor": ev["actor"],
            "prev_status": ev["prev_status"],
            "new_status": ev["new_status"],
            "metadata": json.loads(ev["metadata_json"] or "{}"),
        }
        for ev in event_rows
    ]

    return TripDetailResponse(
        trip_id=booking_row["trip_id"],
        booking_id=booking_row["booking_id"],
        booking_reference=booking_row["booking_reference"],
        destination=dest,
        origin=orig,
        start_date=start_d,
        end_date=end_d,
        traveller_count=max(trv_count, 1),
        status=booking_row["status"],
        lifecycle_status=booking_row["lifecycle_status"],
        authoritative_total=booking_row["total_amount"],
        currency=booking_row["currency"],
        booking_mode=booking_row["booking_mode"] or "DEMO / SIMULATED",
        itinerary=itinerary_plan.model_dump(mode="json") if itinerary_plan else None,
        items=items,
        timeline_events=timeline,
    )


def generate_trip_pack(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    booking_id: str,
) -> TripPackResponse:
    """Generates a structured, exportable Trip Pack for a confirmed booking.
    Contains clear DEMO / SIMULATED notices and disclaimers.
    """
    booking_row = conn.execute(
        "SELECT * FROM bookings WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()

    if not booking_row:
        raise RefusalError("BOOKING_NOT_FOUND", f"Booking {booking_id} not found", http_status=404)

    if booking_row["user_id"] != user_id:
        raise RefusalError("BOOKING_OWNERSHIP_DENIED", "Access denied to trip pack", http_status=403)

    # Travellers
    trv_rows = conn.execute(
        "SELECT display_name, traveller_role FROM booking_travellers WHERE booking_id = ? ORDER BY traveller_seq",
        (booking_id,),
    ).fetchall()
    travellers = [
        BookingTravellerInfo(display_name=r["display_name"], traveller_role=r["traveller_role"])
        for r in trv_rows
    ]
    if not travellers:
        travellers = [BookingTravellerInfo(display_name="Primary Traveller", traveller_role="adult")]

    # Items categorized
    items_rows = conn.execute(
        "SELECT * FROM booking_items WHERE booking_id = ?",
        (booking_id,),
    ).fetchall()

    transport_summary: list[BookingItemSummary] = []
    accommodation_summary: list[BookingItemSummary] = []
    activities_summary: list[BookingItemSummary] = []

    for r in items_rows:
        summary = BookingItemSummary(
            item_type=r["entity_type"],
            title=r["title"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            for_date=r["for_date"],
            quantity=r["units"],
            authoritative_price=r["line_total"],
            currency=r["currency"],
            is_authoritative=True,
        )
        if r["entity_type"] in ("flight", "transport"):
            transport_summary.append(summary)
        elif r["entity_type"] in ("hotel", "stay"):
            accommodation_summary.append(summary)
        else:
            activities_summary.append(summary)

    # Itinerary
    itinerary_plan = None
    dest, orig, start_d, end_d = "Travel Destination", "Origin", "2026-05-01", "2026-05-05"
    if booking_row["itinerary_id"]:
        try:
            itinerary_plan = itinerary_service.get_itinerary(conn, booking_row["itinerary_id"], user_id=user_id)
            dest = itinerary_plan.destination
            orig = itinerary_plan.origin
            start_d = itinerary_plan.start_date.isoformat()
            end_d = itinerary_plan.end_date.isoformat()
        except Exception:
            pass

    now_iso = clock.utc()
    pack_id = new_id("aud")

    important_notes = [
        "SIMULATED RESERVATION: This is a demo booking confirmation generated for travel intelligence testing.",
        "NO REAL PAYMENT PROCESSED: No card or bank account has been charged.",
        "NOT AN AIRLINE TICKET OR HOTEL VOUCHER: Official travel documents must be obtained from real suppliers.",
        "Check-in at accommodation requires valid government photo identification.",
        "Please review standard baggage and check-in policies before your departure date.",
    ]

    pack_response = TripPackResponse(
        pack_id=pack_id,
        booking_id=booking_id,
        booking_reference=booking_row["booking_reference"],
        destination=dest,
        origin=orig,
        start_date=start_d,
        end_date=end_d,
        travellers=travellers,
        transport_summary=transport_summary,
        accommodation_summary=accommodation_summary,
        activities_summary=activities_summary,
        authoritative_total=booking_row["total_amount"],
        currency=booking_row["currency"],
        itinerary=itinerary_plan.model_dump(mode="json") if itinerary_plan else None,
        important_notes=important_notes,
        generated_at=now_iso,
        demo_label="YATRA DEMO TRIP PACK",
        demo_notice=(
            "This is a planning/summary document for a simulated demo booking. "
            "It is NOT an official travel document, airline ticket, or hotel voucher. "
            "No real payment has been processed. No real supplier reservation exists."
        ),
    )

    # Persist in trip_packs table
    p5_repo.upsert_trip_pack(
        conn,
        pack_id=pack_id,
        booking_id=booking_id,
        user_id=user_id,
        pack_data=pack_response.model_dump(mode="json"),
        generated_at=now_iso,
    )

    # Audit event
    conn.execute(
        """INSERT INTO phase5_booking_events (
            event_id, booking_id, user_id, event_type, occurred_at, actor,
            prev_status, new_status, metadata_json
        ) VALUES (?, ?, ?, 'TRIP_PACK_GENERATED', ?, 'user', NULL, NULL, ?)""",
        (
            new_id("aud"),
            booking_id,
            user_id,
            now_iso,
            json.dumps({"pack_id": pack_id, "booking_reference": booking_row["booking_reference"]}),
        ),
    )

    return pack_response


def export_trip_pack_html(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    booking_id: str,
) -> str:
    """Renders a clean, print-friendly HTML trip pack document with demo watermarks."""
    pack = generate_trip_pack(conn, clock, user_id, booking_id)

    travellers_html = "".join(
        f"<li><strong>{t.display_name}</strong> ({t.traveller_role.title()})</li>" for t in pack.travellers
    )
    transport_html = "".join(
        f"<tr><td>{t.title}</td><td>{t.for_date or ''}</td><td>{t.authoritative_price or '0.00'} {t.currency}</td></tr>"
        for t in pack.transport_summary
    ) or "<tr><td colspan='3'>No flight segments recorded</td></tr>"
    hotel_html = "".join(
        f"<tr><td>{h.title}</td><td>{h.for_date or ''}</td><td>{h.authoritative_price or '0.00'} {h.currency}</td></tr>"
        for h in pack.accommodation_summary
    ) or "<tr><td colspan='3'>No hotel reservations recorded</td></tr>"
    activities_html = "".join(
        f"<tr><td>{a.title}</td><td>{a.for_date or ''}</td><td>{a.authoritative_price or a.estimated_price or '0.00'} {a.currency}</td></tr>"
        for a in pack.activities_summary
    ) or "<tr><td colspan='3'>No activities recorded</td></tr>"
    notes_html = "".join(f"<li>{note}</li>" for note in pack.important_notes)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Yatra Saathi Demo Trip Pack - {pack.booking_reference}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 32px; color: #1e293b; background: #fff; }}
  .banner {{ background: #fef3c7; border: 2px dashed #f59e0b; padding: 16px; border-radius: 8px; margin-bottom: 24px; text-align: center; }}
  .banner h2 {{ margin: 0 0 6px 0; color: #b45309; font-size: 1.15rem; }}
  .banner p {{ margin: 0; font-size: 0.85rem; color: #78350f; }}
  .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #e2e8f0; padding-bottom: 16px; margin-bottom: 24px; }}
  .ref {{ font-size: 1.5rem; font-weight: 700; color: #0284c7; letter-spacing: 1px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #e2e8f0; font-size: 0.9rem; }}
  th {{ background: #f8fafc; font-weight: 600; color: #475569; }}
  .total-box {{ text-align: right; margin-top: 24px; padding: 16px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; }}
  .total-amount {{ font-size: 1.5rem; font-weight: 700; color: #166534; }}
  ul {{ padding-left: 20px; font-size: 0.9rem; color: #475569; }}
</style>
</head>
<body>
  <div class="banner">
    <h2>YATRA DEMO TRIP PACK — SIMULATED RESERVATION</h2>
    <p>{pack.demo_notice}</p>
  </div>
  <div class="header">
    <div>
      <h1 style="margin:0 0 4px 0; font-size: 1.75rem;">Trip to {pack.destination}</h1>
      <p style="margin:0; color:#64748b;">From {pack.origin} &bull; {pack.start_date} to {pack.end_date}</p>
    </div>
    <div style="text-align: right;">
      <div style="font-size:0.8rem; color:#64748b;">BOOKING REFERENCE</div>
      <div class="ref">{pack.booking_reference}</div>
    </div>
  </div>
  <h3>Travellers</h3>
  <ul>{travellers_html}</ul>
  <h3>Transport & Flights</h3>
  <table>
    <tr><th>Description</th><th>Date</th><th>Amount</th></tr>
    {transport_html}
  </table>
  <h3>Accommodation</h3>
  <table>
    <tr><th>Property</th><th>Check-in</th><th>Amount</th></tr>
    {hotel_html}
  </table>
  <h3>Itinerary Activities</h3>
  <table>
    <tr><th>Activity</th><th>Date</th><th>Amount</th></tr>
    {activities_html}
  </table>
  <div class="total-box">
    <div>Authoritative Total (Demo)</div>
    <div class="total-amount">{pack.authoritative_total} {pack.currency}</div>
  </div>
  <h3>Important Information</h3>
  <ul>{notes_html}</ul>
</body>
</html>"""
    return html
