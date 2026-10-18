"""POST /internal/agent/v1/sessions/{sid}/replans"""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, get_settings, require_agent_session_match
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.core.config import Settings
from src.services import plan_service

router = APIRouter()


class ReplanRequest(BaseModel):
    reason_code: str
    reason: str
    caused_by_event_id: Optional[str] = None


@router.post("/sessions/{session_id}/replans")
def create_replan(session_id: str, body: ReplanRequest, agent: CurrentAgent = Depends(get_current_agent),
                   clock: Clock = Depends(get_clock), settings: Settings = Depends(get_settings),
                   conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    count = plan_service.replan(conn, clock, session_id, agent_run_id=agent.run_id,
                                reason_code=body.reason_code, reason=body.reason,
                                caused_by_event_id=body.caused_by_event_id,
                                replan_limit=settings.replan_limit)
    return ok({"replan_count": count})
