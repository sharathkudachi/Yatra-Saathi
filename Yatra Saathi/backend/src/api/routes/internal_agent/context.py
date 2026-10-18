"""GET /internal/agent/v1/sessions/{sid}/context"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import CurrentAgent, get_conn, get_current_agent, get_settings, require_agent_session_match
from src.contracts.codes import RefusalError
from src.contracts.envelope import ok
from src.core import money
from src.core.config import Settings
from src.db.repositories import carts as carts_repo
from src.db.repositories import sessions as sessions_repo
from src.db.repositories import trips as trips_repo
from src.services import budget_service, pricing_service, session_service

router = APIRouter()


@router.get("/sessions/{session_id}/context")
def get_context(session_id: str, settings: Settings = Depends(get_settings),
                 agent: CurrentAgent = Depends(get_current_agent), conn: sqlite3.Connection = Depends(get_conn)):
    require_agent_session_match(session_id, agent)
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise RefusalError("SESSION_ACCESS_DENIED", "no such session", http_status=404)

    trip = trips_repo.get_trip(conn, session.trip_id) if session.trip_id else None
    cap = session_service.compute_cap_snapshot(conn, session_id)
    committed_minor = money.to_minor(sessions_repo.committed_total(conn, session_id))
    cart = carts_repo.get_active_cart(conn, session_id)
    cart_total_minor = cart.total_minor if cart else 0

    category_minor = {"transport": 0, "accommodation": 0}
    items = carts_repo.list_active_items(conn, cart.cart_id) if cart else []
    if cart:
        for it in items:
            category = pricing_service.CATEGORY_OF_KIND.get(it.kind)
            if category:
                category_minor[category] += it.line_total_minor
    warnings = budget_service.category_warnings(conn, session, category_minor)

    return ok({
        "session_id": session.session_id, "goal_text": session.goal_text,
        "goal_language": session.goal_language, "constraints": json.loads(session.constraints_json),
        "trip": None if trip is None else {
            "trip_id": trip.trip_id, "start_date": trip.start_date, "end_date": trip.end_date,
            "party_size": trip.party_size, "adults": trip.adults, "children": trip.children,
        },
        "currency": session.currency,
        "effective_cap": money.format_minor(cap.effective_cap_minor), "cap_source": cap.cap_source,
        "committed": money.format_minor(committed_minor),
        "cart": None if cart is None else {"cart_id": cart.cart_id, "version": cart.version,
                                           "status": cart.status,
                                           "total": money.format_minor(cart_total_minor),
                                           # so a re-plan can clear the previous choice first
                                           "item_group_ids": sorted({it.item_group_id for it in items})},
        "remaining": money.format_minor(max(cap.effective_cap_minor - committed_minor - cart_total_minor, 0)),
        "category_warnings": warnings, "status": session.status,
        "plan": json.loads(session.plan_steps_json), "replan_count": session.replan_count,
        "replan_limit": settings.replan_limit, "tax_rate_bp": settings.tax_rate_bp,
    })
