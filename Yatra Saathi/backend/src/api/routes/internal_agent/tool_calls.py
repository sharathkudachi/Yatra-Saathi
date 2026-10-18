"""POST /internal/agent/v1/sessions/{sid}/tool-calls"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, require_agent_session_match
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.services import audit_service

router = APIRouter()


class ToolCallRequest(BaseModel):
    tool: str
    arguments: dict = {}


@router.post("/sessions/{session_id}/tool-calls")
def create_tool_call(session_id: str, body: ToolCallRequest, agent: CurrentAgent = Depends(get_current_agent),
                      clock: Clock = Depends(get_clock), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    event = audit_service.append(
        conn, session_id=session_id, event_type="TOOL_CALL", actor="agent", agent_run_id=agent.run_id,
        occurred_at=clock.utc(), outcome="success",
        input_data={"tool": body.tool, "arguments": body.arguments}, result_data={},
    )
    return ok({"tool_call_id": event.event_id})
