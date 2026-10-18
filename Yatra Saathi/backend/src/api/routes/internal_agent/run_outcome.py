"""POST /internal/agent/v1/sessions/{sid}/run-outcome"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_current_agent, get_conn, require_agent_session_match
from src.contracts.envelope import ok
from src.db.repositories import sessions as sessions_repo

router = APIRouter()


class RunOutcomeRequest(BaseModel):
    status: str
    message: str = ""


@router.post("/sessions/{session_id}/run-outcome")
def run_outcome(session_id: str, body: RunOutcomeRequest, agent: CurrentAgent = Depends(get_current_agent),
                conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    # Informational only -- the backend's own state machine (session_service) is authoritative;
    # this just lets the agent report a human-readable status message for the frontend.
    session = sessions_repo.get(conn, session_id)
    return ok({"session_id": session_id, "status": session.status if session else None,
               "message": body.message})
