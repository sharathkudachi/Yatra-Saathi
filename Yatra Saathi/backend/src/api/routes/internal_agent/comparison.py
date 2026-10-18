"""Internal agent endpoints for travel comparison and optimization.

Enforces:
- Agent token auth (get_current_agent).
- Session ownership (require_agent_session_match).
- Strict validation of inputs.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from src.api.deps import (
    CurrentAgent,
    get_clock,
    get_conn,
    get_current_agent,
    require_agent_session_match,
)
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.db.repositories import sessions as sessions_repo
from src.schemas.comparison import (
    CompareTravelOptionsRequest,
    OptimizeTripRequest,
)
from src.services import comparison_service

router = APIRouter()


@router.post("/sessions/{session_id}/comparison/options")
def compare_options_for_agent(
    session_id: str,
    request: CompareTravelOptionsRequest,
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    session = sessions_repo.get(conn, session_id)
    user_id = session.user_id if session else "usr_agent_internal"
    resp = comparison_service.compare_travel_options(conn, clock, user_id, request)
    return ok(resp.model_dump(mode="json"))


@router.post("/sessions/{session_id}/comparison/optimize")
def optimize_trip_for_agent(
    session_id: str,
    request: OptimizeTripRequest,
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    session = sessions_repo.get(conn, session_id)
    user_id = session.user_id if session else "usr_agent_internal"
    resp = comparison_service.optimize_trip(conn, clock, user_id, request)
    return ok(resp.model_dump(mode="json"))
