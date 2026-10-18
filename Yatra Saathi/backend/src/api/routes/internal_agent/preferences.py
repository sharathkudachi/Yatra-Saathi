"""Internal agent endpoints for preferences, destination exploration, and hotel exploration.

Security:
- Agent token auth required (get_current_agent).
- Session ownership enforced (require_agent_session_match).
- Scoped to authenticated session user.
- Input validation on all payloads.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.deps import (
    CurrentAgent,
    get_clock,
    get_conn,
    get_current_agent,
    require_agent_session_match,
)
from src.contracts.codes import RefusalError
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.db.repositories import sessions as sessions_repo
from src.schemas.exploration import (
    AddActivityRequest,
    DestinationExploreRequest,
    HotelExploreRequest,
    SelectHotelRequest,
)
from src.schemas.preferences import (
    ApplyPreferenceProposalRequest,
    PreferenceProposal,
)
from src.services import exploration_service, preference_service

router = APIRouter()


def _get_session_user(conn: sqlite3.Connection, session_id: str) -> str:
    session = sessions_repo.get(conn, session_id)
    if not session:
        raise RefusalError("SESSION_NOT_FOUND", f"Session {session_id} not found", http_status=404)
    return session.user_id


@router.get("/sessions/{session_id}/preferences")
def get_preferences_for_agent(
    session_id: str,
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    user_id = _get_session_user(conn, session_id)
    profile = preference_service.get_user_profile(conn, user_id, clock=clock)
    return ok(profile.model_dump(mode="json"))


@router.post("/sessions/{session_id}/preferences/proposals")
def propose_preferences_for_agent(
    session_id: str,
    body: Dict[str, Any],
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    user_id = _get_session_user(conn, session_id)

    proposal = PreferenceProposal.model_validate(body)
    preference_service.record_phase4_audit_event(
        conn, clock, user_id,
        "PREFERENCE_PROPOSED",
        proposal.proposal_id,
        {
            "proposal_id": proposal.proposal_id,
            "preferences_count": len(proposal.preferences),
            "explanation": proposal.explanation,
        },
    )
    return ok({"proposal": proposal.model_dump(mode="json")})


@router.post("/sessions/{session_id}/destinations/explore")
def explore_destination_for_agent(
    session_id: str,
    request: DestinationExploreRequest,
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    user_id = _get_session_user(conn, session_id)
    resp = exploration_service.explore_destination(conn, clock, user_id, request)
    return ok(resp.model_dump(mode="json"))


@router.post("/sessions/{session_id}/hotels/explore")
def explore_hotels_for_agent(
    session_id: str,
    request: HotelExploreRequest,
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    user_id = _get_session_user(conn, session_id)
    resp = exploration_service.explore_hotels(conn, clock, user_id, request)
    return ok(resp.model_dump(mode="json"))


@router.post("/sessions/{session_id}/itineraries/{itinerary_id}/activities/add")
def add_activity_for_agent(
    session_id: str,
    itinerary_id: str,
    request: AddActivityRequest,
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    user_id = _get_session_user(conn, session_id)
    plan = exploration_service.add_activity_to_itinerary(
        conn, clock, user_id, itinerary_id, request
    )
    return ok({"itinerary": plan.model_dump(mode="json")})


@router.post("/sessions/{session_id}/itineraries/{itinerary_id}/hotel/select")
def select_hotel_for_agent(
    session_id: str,
    itinerary_id: str,
    request: SelectHotelRequest,
    agent: CurrentAgent = Depends(get_current_agent),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    require_agent_session_match(session_id, agent)
    user_id = _get_session_user(conn, session_id)
    plan = exploration_service.select_hotel_for_itinerary(
        conn, clock, user_id, itinerary_id, request
    )
    return ok({"itinerary": plan.model_dump(mode="json")})
