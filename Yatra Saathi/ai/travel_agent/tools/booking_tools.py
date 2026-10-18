"""Bounded AI booking and trip management tools for Yatra agent (Phase 5).

Safety Rules:
- Strictly communicates via backend HTTP endpoints or service calls.
- AI may read booking status, review breakdowns, and trip details.
- AI NEVER directly modifies or writes to the database.
- AI cannot confirm bookings without user review token and explicit confirmation.
- Rejects prompt injections attempting to bypass confirmation or modify prices.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# Prompt injection keywords to strictly reject
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"ignore\s+(the\s+)?confirmation",
    r"mark\s+(this\s+)?booking\s+as\s+confirmed",
    r"generate\s+(a\s+)?fake\s+booking\s+reference",
    r"book\s+another\s+user",
    r"use\s+sql",
    r"drop\s+table",
    r"override\s+inventory",
    r"change\s+the\s+price",
]


def _check_prompt_injection(text: Optional[str]) -> bool:
    if not text:
        return False
    lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def get_booking_review_via_backend(
    client,
    session_id: str,
    *,
    itinerary_id: str,
    itinerary_version: int,
    travellers: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Retrieves an authoritative booking review for an itinerary draft."""
    if _check_prompt_injection(itinerary_id):
        return {"error": "PROMPT_INJECTION_DETECTED", "message": "Malicious payload rejected"}

    travellers_list = travellers or [{"display_name": "Primary Traveller", "traveller_role": "adult"}]
    payload = {
        "itinerary_id": itinerary_id,
        "itinerary_version": itinerary_version,
        "travellers": travellers_list,
    }
    try:
        resp = client.post(f"/api/v1/itineraries/{itinerary_id}/booking-review", json=payload)
        return resp.get("data", resp)
    except Exception as exc:
        return {"error": "BOOKING_REVIEW_FAILED", "message": str(exc)}


def get_booking_status_via_backend(
    client,
    session_id: str,
    booking_id: str,
) -> Dict[str, Any]:
    """Queries current lifecycle status and timeline for a booking."""
    if _check_prompt_injection(booking_id):
        return {"error": "PROMPT_INJECTION_DETECTED", "message": "Malicious payload rejected"}

    try:
        resp = client.get(f"/api/v1/bookings/{booking_id}")
        return resp.get("data", resp)
    except Exception as exc:
        return {"error": "BOOKING_STATUS_QUERY_FAILED", "message": str(exc)}


def list_my_trips_via_backend(
    client,
    session_id: str,
) -> Dict[str, Any]:
    """Retrieves the authenticated user's trips and reservations."""
    try:
        resp = client.get("/api/v1/trips")
        return resp.get("data", resp)
    except Exception as exc:
        return {"error": "LIST_TRIPS_FAILED", "message": str(exc)}


def get_trip_details_via_backend(
    client,
    session_id: str,
    trip_id: str,
) -> Dict[str, Any]:
    """Retrieves detailed breakdown of a trip or booking."""
    if _check_prompt_injection(trip_id):
        return {"error": "PROMPT_INJECTION_DETECTED", "message": "Malicious payload rejected"}

    try:
        resp = client.get(f"/api/v1/trips/{trip_id}")
        return resp.get("data", resp)
    except Exception as exc:
        return {"error": "GET_TRIP_DETAILS_FAILED", "message": str(exc)}


def cancel_demo_booking_via_backend(
    client,
    session_id: str,
    booking_id: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Requests safe demo booking cancellation."""
    if _check_prompt_injection(booking_id) or _check_prompt_injection(reason):
        return {"error": "PROMPT_INJECTION_DETECTED", "message": "Malicious payload rejected"}

    payload = {"reason": reason or "Cancelled by user request"}
    try:
        resp = client.post(f"/api/v1/bookings/{booking_id}/cancel", json=payload)
        return resp.get("data", resp)
    except Exception as exc:
        return {"error": "CANCELLATION_FAILED", "message": str(exc)}


def generate_trip_pack_via_backend(
    client,
    session_id: str,
    booking_id: str,
) -> Dict[str, Any]:
    """Generates structured Trip Pack document."""
    if _check_prompt_injection(booking_id):
        return {"error": "PROMPT_INJECTION_DETECTED", "message": "Malicious payload rejected"}

    try:
        resp = client.get(f"/api/v1/bookings/{booking_id}/trip-pack")
        return resp.get("data", resp)
    except Exception as exc:
        return {"error": "TRIP_PACK_GENERATION_FAILED", "message": str(exc)}
