"""Bounded preference, destination, and hotel exploration tools for AI agent (Phase 4).

Rules:
- Strictly bounded HTTP requests only (via BackendClient).
- Zero database access, zero raw SQL, zero shell commands.
- Input validation on all parameters.
"""
from typing import Any, Dict, List, Optional


def get_user_preferences_via_backend(client, session_id: str) -> Dict[str, Any]:
    """Fetch structured preferences for the session's user from backend."""
    try:
        return client.get_preferences(session_id)
    except Exception as exc:
        return {"preferences": {}, "error": str(exc)}


def propose_preferences_via_backend(client, session_id: str, proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Send structured preference proposal to backend for validation and staging."""
    try:
        return client.propose_preferences(session_id, proposal)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def explore_destination_via_backend(
    client,
    session_id: str,
    destination: str,
    category_filter: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Retrieve grounded destination activities and POIs from backend catalog."""
    try:
        payload = {"destination": destination, "category_filter": category_filter, "limit": limit}
        return client.explore_destination(session_id, payload)
    except Exception as exc:
        return {"activities": [], "error": str(exc), "total_activities": 0}


def explore_hotels_via_backend(
    client,
    session_id: str,
    destination: str,
    start_date: str,
    end_date: str,
    travellers: int = 1,
    min_stars: Optional[float] = None,
    min_guest_score: Optional[float] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Retrieve grounded hotels and preference matches from backend."""
    try:
        payload = {
            "destination": destination,
            "start_date": start_date,
            "end_date": end_date,
            "travellers": travellers,
            "min_stars": min_stars,
            "min_guest_score": min_guest_score,
            "limit": limit,
        }
        return client.explore_hotels(session_id, payload)
    except Exception as exc:
        return {"hotels": [], "error": str(exc), "total_found": 0}


def add_activity_to_itinerary_via_backend(
    client,
    session_id: str,
    itinerary_id: str,
    poi_id: str,
    day_number: int,
    slot_time: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a validated catalog POI to an existing itinerary via backend."""
    try:
        payload = {"poi_id": poi_id, "day_number": day_number, "slot_time": slot_time}
        return client.add_itinerary_activity(session_id, itinerary_id, payload)
    except Exception as exc:
        return {"error": str(exc)}


def select_hotel_for_itinerary_via_backend(
    client,
    session_id: str,
    itinerary_id: str,
    hotel_id: str,
    room_type_id: str,
) -> Dict[str, Any]:
    """Update itinerary hotel to a validated catalog hotel/room via backend."""
    try:
        payload = {"hotel_id": hotel_id, "room_type_id": room_type_id}
        return client.select_itinerary_hotel(session_id, itinerary_id, payload)
    except Exception as exc:
        return {"error": str(exc)}
