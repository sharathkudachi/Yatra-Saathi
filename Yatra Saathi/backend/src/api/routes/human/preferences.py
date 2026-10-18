"""Human travel preference routes (/api/v1/preferences).

Security & Integrity:
- Authenticated user required (CurrentUser = Depends(get_current_user)).
- Strict ownership isolation: users cannot read, write, or delete another user's preferences.
- Typed validation with whitelist of approved preference keys.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.schemas.preferences import (
    ApplyPreferenceProposalRequest,
    PreferenceItem,
    UpdatePreferencesRequest,
)
from src.services import preference_service

router = APIRouter()


@router.get("/preferences")
def get_preferences_endpoint(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Retrieve the authenticated user's travel preferences profile."""
    profile = preference_service.get_user_profile(conn, user.user_id, clock=clock)
    return ok(profile.model_dump(mode="json"))


@router.put("/preferences")
def update_preferences_endpoint(
    body: UpdatePreferencesRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Update or upsert preferences for the authenticated user."""
    profile = preference_service.update_user_preferences(
        conn, clock, user.user_id, body.preferences
    )
    return ok(profile.model_dump(mode="json"))


@router.post("/preferences/proposals/apply")
def apply_proposal_endpoint(
    body: ApplyPreferenceProposalRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Apply a structured preference proposal proposed by AI."""
    if body.persist_permanently:
        profile = preference_service.update_user_preferences(
            conn, clock, user.user_id, body.proposal.preferences
        )
        return ok({"profile": profile.model_dump(mode="json"), "applied": True})
    return ok({"applied": True, "staged": True})


@router.delete("/preferences/{preference_key}")
def delete_preference_endpoint(
    preference_key: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Remove a specific preference from the authenticated user's profile."""
    deleted = preference_service.delete_user_preference(
        conn, clock, user.user_id, preference_key
    )
    return ok({"deleted": deleted, "preference_key": preference_key})


@router.post("/preferences/reset")
def reset_preferences_endpoint(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Clock = Depends(get_clock),
):
    """Clear all preferences for the authenticated user."""
    cleared_count = preference_service.reset_user_preferences(
        conn, clock, user.user_id
    )
    return ok({"cleared_count": cleared_count})
