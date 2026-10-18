"""Human session routes (section 12)."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user, get_settings, require_session_owner
from src.contracts.envelope import ok
from src.core import money
from src.core.clock import Clock
from src.core.config import Settings
from src.core.dates import local_today, parse_date_only, past_date_error
from src.contracts.codes import RefusalError
from src.db.repositories import carts as carts_repo
from src.db.repositories import sessions as sessions_repo
from src.schemas.human import CreateSessionRequest, SendMessageRequest
from src.db.unit_of_work import transaction
from src.services import agent_dispatch, audit_service, confirmation_service, session_service

router = APIRouter()


def _session_view(conn: sqlite3.Connection, settings: Settings, session: sessions_repo.Session) -> dict:
    # The enforced cap, budget position and plan use the same computation the agent sees in
    # /context, so the user is shown exactly what the backend enforces.
    cap = session_service.compute_cap_snapshot(conn, session.session_id)
    committed_minor = money.to_minor(sessions_repo.committed_total(conn, session.session_id))
    cart = carts_repo.get_active_cart(conn, session.session_id)
    cart_total_minor = cart.total_minor if cart else 0
    # plan_steps_json is "[]" until the agent submits a plan, then {"version": n, "steps": [...]}.
    plan = json.loads(session.plan_steps_json)
    plan = plan if isinstance(plan, dict) else {}
    return {
        "session_id": session.session_id, "user_id": session.user_id, "trip_id": session.trip_id,
        "status": session.status, "currency": session.currency, "spend_cap": session.spend_cap,
        "spend_committed": session.spend_committed, "replan_count": session.replan_count,
        "last_error_code": session.last_error_code, "created_at": session.created_at,
        "updated_at": session.updated_at,
        "goal_text": session.goal_text, "goal_language": session.goal_language,
        "effective_cap": money.format_minor(cap.effective_cap_minor), "cap_source": cap.cap_source,
        "committed": money.format_minor(committed_minor), "cart_total": money.format_minor(cart_total_minor),
        "remaining": money.format_minor(max(cap.effective_cap_minor - committed_minor - cart_total_minor, 0)),
        "plan_version": int(plan.get("version", 0)), "plan_steps": list(plan.get("steps", [])),
        "current_step": session.current_step, "replan_limit": settings.replan_limit,
    }


@router.post("/sessions")
def create_session(
    body: CreateSessionRequest, user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
    conn: sqlite3.Connection = Depends(get_conn),
):
    # Order and format are checked by the request model; the trip may not start in the past.
    start = body.constraints.get("start_date")
    error = past_date_error(parse_date_only(start), local_today(clock), label="start_date") if start else None
    if error:
        raise RefusalError("DATE_IN_PAST", error, http_status=422)
    session = session_service.create_session(
        conn, clock, user_id=user.user_id, trip_id=body.trip_id, goal_text=body.goal_text,
        goal_language=body.goal_language, constraints=body.constraints, spend_cap=body.spend_cap,
        currency=body.currency, tax_rate_bp=settings.tax_rate_bp, replan_limit=settings.replan_limit,
    )
    return ok(_session_view(conn, settings, session))


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str, user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings), conn: sqlite3.Connection = Depends(get_conn),
):
    session = require_session_owner(conn, session_id, user)
    return ok(_session_view(conn, settings, session))


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str, body: SendMessageRequest, request: Request,
    user: CurrentUser = Depends(get_current_user), settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock), conn: sqlite3.Connection = Depends(get_conn),
):
    require_session_owner(conn, session_id, user)
    with transaction(conn):
        # Replying while an approval waits means "change the plan": that approval is withdrawn.
        confirmation_service.supersede_pending(conn, clock, session_id, user_id=user.user_id)
        session_service.transition(conn, clock, session_id, "executing")
        # The user's words are part of the trip's history (shown when the trip is reopened,
        # in My trips, and after a reload), recorded in the same hash-chained audit trail.
        audit_service.append(
            conn, session_id=session_id, event_type="SESSION_RESUMED", actor="user",
            actor_user_id=user.user_id, occurred_at=clock.utc(), outcome="info",
            input_data={"message": body.message}, result_data={},
        )
    dispatcher = getattr(request.app.state, "agent_dispatcher", None)
    agent_run_id = agent_dispatch.dispatch(settings, clock, session_id=session_id, trigger="start",
                                           reason=body.message, dispatcher=dispatcher)
    return ok({"session_id": session_id, "agent_run_id": agent_run_id, "status": "executing"})


@router.post("/sessions/{session_id}/resume")
def resume_session(
    session_id: str, request: Request, user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
    conn: sqlite3.Connection = Depends(get_conn),
):
    session = require_session_owner(conn, session_id, user)
    if session.status == "paused":
        session = session_service.transition(conn, clock, session_id, "executing")
    dispatcher = getattr(request.app.state, "agent_dispatcher", None)
    agent_run_id = agent_dispatch.dispatch(settings, clock, session_id=session_id, trigger="resume",
                                           reason="resume", dispatcher=dispatcher)
    return ok({"session_id": session_id, "agent_run_id": agent_run_id, "status": session.status})
