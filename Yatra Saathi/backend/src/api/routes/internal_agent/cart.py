"""POST /internal/agent/v1/sessions/{sid}/cart/items
DELETE /internal/agent/v1/sessions/{sid}/cart/item-groups/{grp}"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, get_settings, require_agent_session_match
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.core.config import Settings
from src.services import cart_service

router = APIRouter()


class AddCartItemsRequest(BaseModel):
    offer_refs: list[str]


@router.post("/sessions/{session_id}/cart/items")
def add_cart_items(session_id: str, body: AddCartItemsRequest, agent: CurrentAgent = Depends(get_current_agent),
                    clock: Clock = Depends(get_clock), settings: Settings = Depends(get_settings),
                    conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    result = cart_service.add_items(conn, clock, session_id, offer_refs=body.offer_refs,
                                    agent_run_id=agent.run_id, tax_rate_bp=settings.tax_rate_bp)
    return ok(result)


@router.delete("/sessions/{session_id}/cart/item-groups/{item_group_id}")
def remove_cart_item_group(session_id: str, item_group_id: str, agent: CurrentAgent = Depends(get_current_agent),
                            clock: Clock = Depends(get_clock), settings: Settings = Depends(get_settings),
                            conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    result = cart_service.remove_item_group(conn, clock, session_id, item_group_id,
                                            agent_run_id=agent.run_id, tax_rate_bp=settings.tax_rate_bp)
    return ok(result)
