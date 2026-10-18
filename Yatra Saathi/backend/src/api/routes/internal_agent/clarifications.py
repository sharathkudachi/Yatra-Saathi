"""POST /internal/agent/v1/sessions/{sid}/clarifications"""
from __future__ import annotations

import sqlite3

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, get_settings, require_agent_session_match
from src.core.config import Settings
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.db.unit_of_work import transaction
from src.services import audit_service, notify_service, session_service

router = APIRouter()


class ClarificationRequest(BaseModel):
    question: str
    # Optional structured choices shown as cards (e.g. three trip packages); the user answers
    # with a normal message. Informational only: nothing here is priced or booked.
    options: Optional[list[dict]] = None
    # Optional one-tap replies, e.g. the next scheduled flight dates when the asked date has none.
    suggestions: Optional[list[dict]] = None


@router.post("/sessions/{session_id}/clarifications")
def request_clarification(session_id: str, body: ClarificationRequest,
                           agent: CurrentAgent = Depends(get_current_agent), clock: Clock = Depends(get_clock),
                           settings: Settings = Depends(get_settings), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    with transaction(conn):
        session_service.transition(conn, clock, session_id, "awaiting_input")
        audit_service.append(
            conn, session_id=session_id, event_type="CLARIFICATION_REQUESTED", actor="agent",
            agent_run_id=agent.run_id, occurred_at=clock.utc(), outcome="info",
            input_data={"question": body.question, **({"options": body.options} if body.options else {}),
                        **({"suggestions": body.suggestions} if body.suggestions else {})},
            result_data={},
        )
    if body.options:
        # Planning is done: tell the user their options are ready (they may have left the app).
        user_id = notify_service.session_user(conn, session_id)
        totals = [o.get("total") for o in body.options if isinstance(o, dict) and o.get("total")]
        currency = next((o.get("currency") for o in body.options if isinstance(o, dict) and o.get("currency")), "")
        cheapest = min(totals, key=lambda x: float(x)) if totals else None
        destination = next((o.get("destination") for o in body.options if isinstance(o, dict) and o.get("destination")),
                           None) or notify_service.trip_name(conn, session_id)
        if user_id:
            notify_service.notify(
                conn, clock, settings, user_id=user_id, kind="plan_ready", session_id=session_id,
                dedupe_key=f"plan:{session_id}:{agent.run_id}", url="/#plan",
                title=f"Your {destination + ' ' if destination else ''}trip options are ready",
                body=f"{len(body.options)} options" + (f" from {notify_service.money_text(cheapest, currency)}" if cheapest else "")
                     + " — tap to choose one.")
    return ok({"status": "awaiting_input"})
