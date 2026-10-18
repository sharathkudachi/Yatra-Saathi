"""POST /internal/agent/v1/sessions/{sid}/booking-requests (section 9.1)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, get_settings, require_agent_session_match
from src.contracts.envelope import ok
from src.core import money
from src.core.clock import Clock
from src.core.config import Settings
from src.services import confirmation_service, notify_service

router = APIRouter()


@router.post("/sessions/{session_id}/booking-requests")
def create_booking_request(session_id: str, agent: CurrentAgent = Depends(get_current_agent),
                            clock: Clock = Depends(get_clock), settings: Settings = Depends(get_settings),
                            conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    confirmation = confirmation_service.request_booking(
        conn, clock, session_id, agent_run_id=agent.run_id, tax_rate_bp=settings.tax_rate_bp,
        ttl_seconds=settings.confirmation_ttl_seconds,
    )
    user_id = notify_service.session_user(conn, session_id)
    if user_id:
        minutes = settings.confirmation_ttl_seconds // 60
        notify_service.notify(
            conn, clock, settings, user_id=user_id, kind="approval_ready", session_id=session_id,
            dedupe_key=f"approval:{confirmation.confirmation_id}", url="/#plan",
            title=f"Your {(notify_service.trip_name(conn, session_id) + ' ') if notify_service.trip_name(conn, session_id) else ''}trip is ready to approve",
            body=f"Total {notify_service.money_text(money.format_minor(confirmation.total_minor), confirmation.currency)} "
                 f"incl. tax. Approve within {minutes} minutes to book.")
    return ok({
        "confirmation_id": confirmation.confirmation_id, "status": "awaiting_confirmation",
        "expires_at": confirmation.expires_at, "total": money.format_minor(confirmation.total_minor),
    })
