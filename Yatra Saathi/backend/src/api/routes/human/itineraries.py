"""Human itinerary routes (/api/v1/itineraries and session itinerary)."""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.schemas.comparison import (
    ApplyOptionRequest,
    CompareTravelOptionsRequest,
    OptimizeTripRequest,
    TravelOption,
)
from src.schemas.exploration import AddActivityRequest, SelectHotelRequest
from src.schemas.itinerary import (
    GenerateItineraryRequest,
    ItineraryValidationResult,
    ReplanItineraryRequest,
    SelectAlternativeOptionRequest,
    TripPlan,
)
from src.services import comparison_service, itinerary_service

router = APIRouter()


@router.post("/itineraries/validate")
def validate_itinerary_endpoint(
    plan: TripPlan,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Validate a structured TripPlan payload against all rules (dry-run)."""
    result = itinerary_service.validate_itinerary(plan, conn=conn)
    return ok(result.model_dump(mode="json"))


@router.post("/itineraries/generate")
def generate_itinerary_endpoint(
    request: GenerateItineraryRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Generate a structured itinerary draft with grounded alternatives and verification."""
    result = itinerary_service.generate_itinerary(conn, clock, user.user_id, request)
    return ok(result.model_dump(mode="json"))


@router.post("/itineraries/{itinerary_id}/replan")
def replan_itinerary_endpoint(
    itinerary_id: str,
    body: ReplanItineraryRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Conversational natural-language replanning for an existing itinerary draft."""
    updated = itinerary_service.replan_itinerary(conn, clock, user.user_id, itinerary_id, body)
    return ok({"itinerary": updated.model_dump(mode="json")})


@router.post("/itineraries/{itinerary_id}/regenerate")
def regenerate_itinerary_endpoint(
    itinerary_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Regenerate daily activities for an existing itinerary while preserving flights and stays."""
    updated = itinerary_service.replan_itinerary(
        conn, clock, user.user_id, itinerary_id, ReplanItineraryRequest(instruction="regenerate")
    )
    return ok({"itinerary": updated.model_dump(mode="json")})


@router.post("/itineraries/{itinerary_id}/select-option")
def select_option_endpoint(
    itinerary_id: str,
    body: SelectAlternativeOptionRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Switch active plan to one of the bounded alternatives (e.g. balanced, budget, relaxed)."""
    updated = itinerary_service.select_alternative_option(conn, clock, user.user_id, itinerary_id, body.option_id)
    return ok({"itinerary": updated.model_dump(mode="json")})


@router.post("/itineraries")
def create_itinerary_endpoint(
    plan: TripPlan,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Create a structured itinerary draft owned by the authenticated user."""
    created = itinerary_service.create_itinerary_draft(conn, clock, user.user_id, plan)
    return ok({"itinerary": created.model_dump(mode="json")})


@router.get("/itineraries/{itinerary_id}")
def get_itinerary_endpoint(
    itinerary_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Retrieve a structured itinerary by ID (ownership enforced)."""
    plan = itinerary_service.get_itinerary(conn, itinerary_id, user_id=user.user_id)
    return ok({"itinerary": plan.model_dump(mode="json")})


@router.put("/itineraries/{itinerary_id}")
def update_itinerary_endpoint(
    itinerary_id: str,
    plan: TripPlan,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Update an existing itinerary (lifecycle rules and ownership enforced)."""
    updated = itinerary_service.update_itinerary(conn, clock, itinerary_id, user.user_id, plan)
    return ok({"itinerary": updated.model_dump(mode="json")})


@router.get("/sessions/{session_id}/itinerary")
def get_session_itinerary_endpoint(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Get the structured itinerary synthesized from a session's cart and constraints."""
    itin_id = f"session_plan_{session_id}"
    try:
        existing = itinerary_service.get_itinerary(conn, itin_id, user_id=user.user_id)
        if existing:
            return ok({"itinerary": existing.model_dump(mode="json")})
    except Exception:
        pass

    plan = itinerary_service.build_plan_from_session(conn, session_id, user.user_id)
    if plan:
        try:
            persisted = itinerary_service.create_itinerary(conn, clock, user.user_id, plan, session_id=session_id)
            return ok({"itinerary": persisted.model_dump(mode="json")})
        except Exception:
            return ok({"itinerary": plan.model_dump(mode="json")})
    return ok({"itinerary": None})


@router.post("/travel-options/compare")
def compare_travel_options_endpoint(
    request: CompareTravelOptionsRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Deterministically find, score, rank, and compare travel options (Phase 3)."""
    resp = comparison_service.compare_travel_options(conn, clock, user.user_id, request)
    return ok(resp.model_dump(mode="json"))


@router.post("/itineraries/{itinerary_id}/optimize")
def optimize_trip_endpoint(
    itinerary_id: str,
    body: OptimizeTripRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Optimize an existing itinerary by finding cheaper or more comfortable alternatives."""
    if not body.itinerary_id:
        body.itinerary_id = itinerary_id
    resp = comparison_service.optimize_trip(conn, clock, user.user_id, body)
    return ok(resp.model_dump(mode="json"))


@router.post("/itineraries/{itinerary_id}/apply-travel-option")
def apply_travel_option_endpoint(
    itinerary_id: str,
    body: ApplyOptionRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Atomically apply a chosen TravelOption to the itinerary, incrementing version with validation."""
    if not body.selected_option:
        # Fetch the option by id from an on-demand comparison query
        current = itinerary_service.get_itinerary(conn, itinerary_id, user_id=user.user_id)
        comp_req = CompareTravelOptionsRequest(
            origin=current.origin,
            destination=current.destination,
            start_date=current.start_date,
            end_date=current.end_date,
            travellers=current.travellers,
            currency=current.currency,
            budget=current.budget,
        )
        comp_resp = comparison_service.compare_travel_options(conn, clock, user.user_id, comp_req)
        match_opt = next((o for o in comp_resp.options if o.id == body.option_id), None)
        if not match_opt:
            raise RefusalError("STATE_INVALID", f"option {body.option_id} not found", http_status=404)
        option_to_apply = match_opt
    else:
        option_to_apply = body.selected_option

    updated = comparison_service.apply_option_to_itinerary(conn, clock, user.user_id, itinerary_id, option_to_apply)
    return ok({"itinerary": updated.model_dump(mode="json")})


@router.post("/itineraries/{itinerary_id}/activities/add")
def add_activity_endpoint(
    itinerary_id: str,
    body: AddActivityRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Add a validated catalog POI to the itinerary with pacing, duplicate, and budget checks."""
    from src.services import exploration_service
    updated = exploration_service.add_activity_to_itinerary(
        conn, clock, user.user_id, itinerary_id, body
    )
    return ok({"itinerary": updated.model_dump(mode="json")})


@router.post("/itineraries/{itinerary_id}/hotel/select")
def select_hotel_endpoint(
    itinerary_id: str,
    body: SelectHotelRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Atomically switch an itinerary's hotel accommodation to a validated catalog offer."""
    from src.services import exploration_service
    updated = exploration_service.select_hotel_for_itinerary(
        conn, clock, user.user_id, itinerary_id, body
    )
    return ok({"itinerary": updated.model_dump(mode="json")})



