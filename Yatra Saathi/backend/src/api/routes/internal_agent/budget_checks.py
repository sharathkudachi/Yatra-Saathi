"""POST /internal/agent/v1/sessions/{sid}/budget-checks (section 12): advisory
figures only. Nothing is written to the cart; it's purely "would this fit."
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import CurrentAgent, get_clock, get_conn, get_current_agent, get_settings, require_agent_session_match
from src.contracts.envelope import ok
from src.core import money
from src.core.clock import Clock
from src.core.config import Settings
from src.services import budget_service, cart_service

router = APIRouter()


class BudgetCheckRequest(BaseModel):
    offer_refs: list[str]


@router.post("/sessions/{session_id}/budget-checks")
def advisory_budget_check(session_id: str, body: BudgetCheckRequest,
                           agent: CurrentAgent = Depends(get_current_agent), clock: Clock = Depends(get_clock),
                           settings: Settings = Depends(get_settings), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    preview = cart_service.preview_addition(conn, session_id, body.offer_refs, tax_rate_bp=settings.tax_rate_bp)
    result = budget_service.evaluate(
        conn, session_id, checkpoint="advisory", subtotal_minor=preview.totals.subtotal_minor,
        tax_minor=preview.totals.tax_minor, total_minor=preview.totals.total_minor,
        category_minor=preview.category_minor,
    )
    budget_service.record(conn, clock, session_id, result, actor="agent", agent_run_id=agent.run_id)
    # remaining_minor is signed (negative when over cap); format_minor requires
    # a non-negative amount, so the sign is applied separately.
    remaining_sign = "-" if result.remaining_minor < 0 else ""
    return ok({
        "checkpoint": "advisory", "passed": result.passed,
        "subtotal": money.format_minor(result.subtotal_minor), "tax": money.format_minor(result.tax_minor),
        "total": money.format_minor(result.total_minor), "committed": money.format_minor(result.committed_minor),
        "effective_cap": money.format_minor(result.effective_cap_minor),
        "remaining": f"{remaining_sign}{money.format_minor(abs(result.remaining_minor))}",
        "category_warnings": result.category_warnings,
    })
