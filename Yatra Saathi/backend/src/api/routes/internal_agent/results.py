"""POST /internal/agent/v1/sessions/{sid}/tool-calls/{id}/results"""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, require_agent_session_match
from src.contracts.codes import RefusalError
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.db.repositories import sessions as sessions_repo
from src.db.repositories import trips as trips_repo
from src.services import offer_service

router = APIRouter()


class ToolResultRequest(BaseModel):
    offers: list[dict] = []
    activities: list[dict] = []
    error: Optional[str] = None


@router.post("/sessions/{session_id}/tool-calls/{tool_call_id}/results")
def submit_results(session_id: str, tool_call_id: str, body: ToolResultRequest,
                    agent: CurrentAgent = Depends(get_current_agent), clock: Clock = Depends(get_clock),
                    conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise RefusalError("SESSION_ACCESS_DENIED", "no such session", http_status=404)
    trip = trips_repo.get_trip(conn, session.trip_id) if session.trip_id else None
    result = offer_service.process_tool_result(
        conn, clock, session_id, tool_call_id=tool_call_id, agent_run_id=agent.run_id,
        offers=body.offers, activities=body.activities, trip=trip, session_currency=session.currency,
        error=body.error,
    )
    return ok(result)
