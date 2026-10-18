"""Human hotel exploration routes (/api/v1/hotels).

Security & Grounding:
- Authenticated user required (CurrentUser = Depends(get_current_user)).
- Authoritative catalog offers only; zero fabricated amenities or prices.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.schemas.exploration import (
    HotelExploreRequest,
    HotelExploreResponse,
)
from src.services import exploration_service

router = APIRouter()


@router.post("/hotels/explore")
def explore_hotels_endpoint(
    request: HotelExploreRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Explore authoritative hotels and room night offers matching user preferences."""
    resp = exploration_service.explore_hotels(conn, clock, user.user_id, request)
    return ok(resp.model_dump(mode="json"))
