"""PUT /internal/agent/v1/sessions/{sid}/plan
POST /internal/agent/v1/sessions/{sid}/plan/steps/{step_id}/events"""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, require_agent_session_match
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.services import plan_service

router = APIRouter()


class PlanRequest(BaseModel):
    steps: list[dict]
    reason_code: Optional[str] = None
    caused_by_event_id: Optional[str] = None
    reason: Optional[str] = None


class StepEventRequest(BaseModel):
    event: str
    note: Optional[str] = None


@router.put("/sessions/{session_id}/plan")
def submit_plan(session_id: str, body: PlanRequest, agent: CurrentAgent = Depends(get_current_agent),
                 clock: Clock = Depends(get_clock), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    version = plan_service.submit_plan(
        conn, clock, session_id, agent_run_id=agent.run_id, steps=body.steps,
        reason_code=body.reason_code, caused_by_event_id=body.caused_by_event_id, reason=body.reason,
    )
    return ok({"plan_version": version})


@router.post("/sessions/{session_id}/plan/steps/{step_id}/events")
def plan_step_event(session_id: str, step_id: str, body: StepEventRequest,
                     agent: CurrentAgent = Depends(get_current_agent), clock: Clock = Depends(get_clock),
                     conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    plan_service.record_step_event(conn, clock, session_id, step_id, agent_run_id=agent.run_id,
                                   event=body.event, note=body.note)
    return ok({"step_id": step_id, "event": body.event})
