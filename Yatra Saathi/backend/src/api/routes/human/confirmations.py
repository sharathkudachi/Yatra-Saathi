"""Confirmation gate, human-only (section 9). Approve/decline require a
human token whose user owns the session -- an agent token here is rejected by
`get_current_user` itself (it can't be verified as a human token)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user, get_settings, require_session_owner
from src.contracts.envelope import ok
from src.core import money
from src.core.clock import Clock
from src.core.config import Settings
from src.services import booking_service, confirmation_service, notify_service
from src.services.mock_booking_provider import MockBookingProvider
from src.schemas.human import ApproveConfirmationRequest, DeclineConfirmationRequest

router = APIRouter()


def _confirmation_view(confirmation) -> dict:
    return {
        "confirmation_id": confirmation.confirmation_id, "cart_id": confirmation.cart_id,
        "cart_version": confirmation.cart_version, "status": confirmation.status,
        "snapshot_hash": confirmation.snapshot_hash, "currency": confirmation.currency,
        "subtotal": money.format_minor(confirmation.subtotal_minor),
        "tax": money.format_minor(confirmation.tax_minor),
        "total": money.format_minor(confirmation.total_minor),
        "effective_cap": money.format_minor(confirmation.effective_cap_minor),
        "requested_at": confirmation.requested_at, "expires_at": confirmation.expires_at,
    }


@router.get("/sessions/{session_id}/confirmations/current")
def get_current_confirmation(session_id: str, user: CurrentUser = Depends(get_current_user),
                              clock: Clock = Depends(get_clock), conn: sqlite3.Connection = Depends(get_conn)):
    require_session_owner(conn, session_id, user)
    confirmation = confirmation_service.get_current(conn, session_id)
    if confirmation is None:
        return ok({"confirmation": None})
    confirmation = confirmation_service.expire_if_due(conn, clock, confirmation)
    if confirmation.status != "pending":
        return ok({"confirmation": None})
    return ok(_confirmation_view(confirmation))


@router.post("/sessions/{session_id}/confirmations/{confirmation_id}/approve")
def approve_confirmation(
    session_id: str, confirmation_id: str, body: ApproveConfirmationRequest,
    user: CurrentUser = Depends(get_current_user), clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings), conn: sqlite3.Connection = Depends(get_conn),
):
    require_session_owner(conn, session_id, user)
    confirmation_service.approve(conn, clock, session_id, confirmation_id, user_id=user.user_id,
                                 submitted_snapshot_hash=body.snapshot_hash)
    outcome = booking_service.attempt_booking(conn, clock, session_id, confirmation_id,
                                              tax_rate_bp=settings.tax_rate_bp, provider=MockBookingProvider())
    currency = conn.execute("SELECT currency FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone()[0]
    notify_service.notify(conn, clock, settings, user_id=user.user_id, kind="booking_confirmed", session_id=session_id,
                          dedupe_key=f"booked:{outcome.booking_id}", url="/#my-trips",
                          title=f"Booking confirmed ✓ {notify_service.trip_name(conn, session_id)}".rstrip(),
                          body=f"Reference {outcome.booking_reference} · "
                               f"{notify_service.money_text(outcome.total_amount, currency)} incl. tax. Have a great trip!")
    return ok({"booking_id": outcome.booking_id, "booking_reference": outcome.booking_reference,
               "total_amount": outcome.total_amount})


@router.post("/sessions/{session_id}/confirmations/{confirmation_id}/decline")
def decline_confirmation(
    session_id: str, confirmation_id: str, body: DeclineConfirmationRequest,
    user: CurrentUser = Depends(get_current_user), clock: Clock = Depends(get_clock),
    conn: sqlite3.Connection = Depends(get_conn),
):
    require_session_owner(conn, session_id, user)
    confirmation = confirmation_service.decline(conn, clock, session_id, confirmation_id,
                                                user_id=user.user_id, note=body.note)
    return ok(_confirmation_view(confirmation))
