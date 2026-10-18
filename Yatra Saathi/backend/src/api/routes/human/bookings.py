"""Human booking routes (/api/v1/bookings and itinerary booking review)."""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user, require_session_owner
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.db.repositories import bookings as bookings_repo
from src.schemas.booking import (
    BookingReviewRequest,
    BookingTravellerInfo,
    CancelBookingRequest,
    ConfirmBookingRequest,
)
from src.services import phase5_booking_service

router = APIRouter()


# ============================================================
# Phase 1-4 Historical Session Route (Preserved)
# ============================================================

@router.get("/sessions/{session_id}/booking")
def get_session_booking(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    require_session_owner(conn, session_id, user)
    booking = bookings_repo.get_by_session_confirmed(conn, session_id)
    if booking is None:
        return ok({"booking": None})
    return ok({"booking": {
        "booking_id": booking["booking_id"],
        "booking_reference": booking["booking_reference"],
        "total_amount": booking["total_amount"],
        "currency": booking["currency"],
        "tax_amount": booking["tax_amount"],
        "status": booking["status"],
        "created_at": booking["created_at"],
    }})


# ============================================================
# Phase 5: Booking Review Endpoint
# ============================================================

@router.post("/itineraries/{itinerary_id}/booking-review")
def create_booking_review_endpoint(
    itinerary_id: str,
    body: BookingReviewRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Generates an authoritative booking review for an itinerary with recalculated totals."""
    # Ensure URL itinerary_id takes precedence or matches
    if body.itinerary_id != itinerary_id:
        body = body.model_copy(update={"itinerary_id": itinerary_id})
    review = phase5_booking_service.create_booking_review(conn, clock, user.user_id, body)
    return ok(review.model_dump(mode="json"))


# ============================================================
# Phase 5: Inventory Hold Simulation Endpoint
# ============================================================

@router.post("/bookings/prepare")
@router.post("/itineraries/{itinerary_id}/holds")
def create_hold_endpoint(
    body: dict,
    itinerary_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Creates a simulated inventory hold prior to explicit user confirmation."""
    itin_id = itinerary_id or body.get("itinerary_id")
    version = int(body.get("itinerary_version", 1))
    token = body.get("review_token", "")
    hold = phase5_booking_service.create_inventory_hold(
        conn, clock, user.user_id, review_token=token, itinerary_id=itin_id, itinerary_version=version
    )
    return ok(hold)


# ============================================================
# Phase 5: Explicit Booking Confirmation Endpoints
# ============================================================

@router.post("/bookings/confirm")
@router.post("/bookings/{booking_id}/confirm")
def confirm_booking_endpoint(
    body: ConfirmBookingRequest,
    booking_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Explicitly confirms a demo booking after user reviews the authoritative totals."""
    result = phase5_booking_service.confirm_booking(conn, clock, user.user_id, body)
    return ok(result.model_dump(mode="json"))


# ============================================================
# Phase 5: Booking Status & Details Endpoint
# ============================================================

@router.get("/bookings/{booking_id}")
def get_booking_status_endpoint(
    booking_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Retrieves full status and item breakdown for a booking (ownership enforced)."""
    status_resp = phase5_booking_service.get_booking_status(conn, user.user_id, booking_id)
    return ok(status_resp.model_dump(mode="json"))


# ============================================================
# Phase 5: Booking Cancellation Endpoint
# ============================================================

@router.post("/bookings/{booking_id}/cancel")
def cancel_booking_endpoint(
    booking_id: str,
    body: Optional[CancelBookingRequest] = None,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Cancels a booking safely with hold release and audit trail (idempotent)."""
    req = body or CancelBookingRequest()
    cancel_resp = phase5_booking_service.cancel_booking(conn, clock, user.user_id, booking_id, req)
    return ok(cancel_resp.model_dump(mode="json"))


# ============================================================
# Phase 5: Trip Pack Endpoints
# ============================================================

@router.get("/bookings/{booking_id}/trip-pack")
def get_trip_pack_endpoint(
    booking_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Generates and retrieves the structured Trip Pack for a booking."""
    pack = phase5_booking_service.generate_trip_pack(conn, clock, user.user_id, booking_id)
    return ok(pack.model_dump(mode="json"))


@router.get("/bookings/{booking_id}/trip-pack/export")
def export_trip_pack_endpoint(
    booking_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Renders a print-ready HTML export of the Trip Pack."""
    html_content = phase5_booking_service.export_trip_pack_html(conn, clock, user.user_id, booking_id)
    return HTMLResponse(content=html_content, status_code=200)
