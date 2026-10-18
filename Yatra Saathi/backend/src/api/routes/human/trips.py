"""GET /api/v1/trips and /api/v1/trips/{trip_id} -- signed-in user's trips."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.services import my_trips_service, phase5_booking_service

router = APIRouter()


@router.get("/trips")
def list_trips(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Lists all trips for the authenticated user."""
    return ok({"trips": my_trips_service.my_trips(conn, user.user_id)})


@router.get("/trips/{trip_id}")
def get_trip(
    trip_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Retrieves full details for a trip or booking (ownership enforced)."""
    # Check if trip_id matches a booking_id directly
    booking_row = conn.execute(
        "SELECT booking_id FROM bookings WHERE booking_id = ? OR trip_id = ?",
        (trip_id, trip_id),
    ).fetchone()
    target_id = booking_row["booking_id"] if booking_row else trip_id
    detail = phase5_booking_service.get_trip_detail(conn, user.user_id, target_id)
    return ok(detail.model_dump(mode="json"))


@router.get("/trips/{trip_id}/trip-pack")
def get_trip_trip_pack(
    trip_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Generates and retrieves the Trip Pack for a trip."""
    booking_row = conn.execute(
        "SELECT booking_id FROM bookings WHERE booking_id = ? OR trip_id = ?",
        (trip_id, trip_id),
    ).fetchone()
    target_id = booking_row["booking_id"] if booking_row else trip_id
    pack = phase5_booking_service.generate_trip_pack(conn, clock, user.user_id, target_id)
    return ok(pack.model_dump(mode="json"))
