"""GET/PUT /internal/agent/v1/sessions/{sid}/state (section 6: JSON, <=1MB, versioned)."""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, get_settings, require_agent_session_match
from src.contracts.codes import RefusalError
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.core.config import Settings
from src.services import agent_state_service

router = APIRouter()


@router.get("/sessions/{session_id}/state")
def get_state(session_id: str, agent: CurrentAgent = Depends(get_current_agent),
              conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    view = agent_state_service.get_state(conn, session_id)
    if view is None:
        return ok({"state": None, "version": 0})
    return ok({"state": view.state, "version": view.version})


@router.put("/sessions/{session_id}/state")
def put_state(session_id: str, state: dict = Body(...), if_match: Optional[str] = Header(default=None),
              agent: CurrentAgent = Depends(get_current_agent), clock: Clock = Depends(get_clock),
              settings: Settings = Depends(get_settings), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    if if_match is None:
        if_match_version = None
    elif if_match.isdigit():
        if_match_version = int(if_match)
    else:
        raise RefusalError("STATE_INVALID", "If-Match must be an integer version")
    view = agent_state_service.put_state(conn, clock, session_id, state, if_match_version=if_match_version,
                                         max_bytes=settings.agent_state_max_bytes)
    return ok({"state": view.state, "version": view.version})
