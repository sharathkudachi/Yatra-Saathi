"""Human destination exploration routes (/api/v1/destinations).

Security & Grounding:
- Authenticated user required (CurrentUser = Depends(get_current_user)).
- Authoritative catalog data only; zero hallucinated attractions.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.schemas.exploration import (
    DestinationExploreRequest,
    DestinationExploreResponse,
)
from src.services import exploration_service

router = APIRouter()


class ActivitySearchBody(BaseModel):
    destination: str = Field(min_length=1, max_length=100)
    query: str = Field(default="", max_length=100)
    limit: int = Field(default=20, ge=1, le=50)


@router.post("/destinations/explore")
def explore_destination_endpoint(
    request: DestinationExploreRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Explore authoritative destination POIs and supported categories."""
    resp = exploration_service.explore_destination(conn, clock, user.user_id, request)
    return ok(resp.model_dump(mode="json"))


@router.post("/destinations/activities/search")
def search_activities_endpoint(
    body: ActivitySearchBody,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Search authoritative activities in destination by keyword."""
    results = exploration_service.search_destination_activities(
        conn, clock, user.user_id, body.destination, body.query, limit=body.limit
    )
    return ok({"activities": [r.model_dump(mode="json") for r in results]})
