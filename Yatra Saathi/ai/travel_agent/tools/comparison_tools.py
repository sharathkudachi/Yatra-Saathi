# travel_agent/tools/comparison_tools.py
"""Bounded comparison and budget optimization tools for the AI agent service.

Rules:
- Strictly communicates via backend HTTP endpoints.
- No direct database access or execution of raw SQL.
- All pricing and scoring are calculated by the authoritative backend.
"""
from typing import Any, Dict, List, Optional


def compare_travel_options_via_backend(
    client,
    session_id: str,
    *,
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    travellers: int = 1,
    currency: str = "INR",
    budget: Optional[str] = None,
    preferences: Optional[str] = None,
    cabin_class: str = "economy",
    category: Optional[str] = None,
    max_options: int = 3,
) -> Dict[str, Any]:
    """Invoke backend comparison service over HTTP to get grounded travel options."""
    payload = {
        "origin": origin,
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "travellers": travellers,
        "currency": currency,
        "budget": budget,
        "preferences": preferences,
        "cabin_class": cabin_class,
        "category_filter": category,
        "max_options": max_options,
    }
    try:
        data = client.compare_travel_options(session_id, payload)
        return data.get("data", data)
    except Exception as exc:
        return {
            "options": [],
            "feasible": False,
            "no_feasible_reason": str(exc),
            "trade_off_analysis": [],
            "recommendation_summary": "Comparison could not be completed via backend.",
        }


def optimize_trip_via_backend(
    client,
    session_id: str,
    *,
    itinerary_id: str,
    objective: str = "cheaper",
    target_budget: Optional[str] = None,
    allowed_changes: Optional[Dict[str, bool]] = None,
    preferences: Optional[str] = None,
) -> Dict[str, Any]:
    """Invoke backend budget and comfort optimization service over HTTP."""
    payload = {
        "itinerary_id": itinerary_id,
        "objective": objective,
        "target_budget": target_budget,
        "allowed_changes": allowed_changes or {"flight": True, "hotel": True, "activities": False, "dates": False},
        "preferences": preferences,
    }
    try:
        data = client.optimize_trip(session_id, payload)
        return data.get("data", data)
    except Exception as exc:
        return {
            "feasible": False,
            "status": "failed",
            "explanation": f"Optimization failed: {exc}",
            "diff": None,
        }


def evaluate_tradeoffs(
    option_a: Optional[Dict[str, Any]] = None,
    option_b: Optional[Dict[str, Any]] = None,
    *,
    option_a_id: Optional[str] = None,
    option_b_id: Optional[str] = None,
    tradeoffs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Deterministically explain trade-offs between two options using supplied factual fields."""
    points: List[str] = list(tradeoffs or [])

    if option_a and option_b:
        price_a = option_a.get("authoritative_total") or option_a.get("total")
        price_b = option_b.get("authoritative_total") or option_b.get("total")
        cur = option_a.get("currency", "INR")

        if price_a and price_b:
            try:
                from decimal import Decimal
                diff = abs(Decimal(price_a) - Decimal(price_b))
                if Decimal(price_a) < Decimal(price_b):
                    points.append(f"Option {option_a.get('id', 'A')} is {cur} {diff} cheaper than Option {option_b.get('id', 'B')}.")
                elif Decimal(price_b) < Decimal(price_a):
                    points.append(f"Option {option_b.get('id', 'B')} is {cur} {diff} cheaper than Option {option_a.get('id', 'A')}.")
                else:
                    points.append(f"Both options have the identical total price of {cur} {price_a}.")
            except Exception:
                pass

        dur_a = option_a.get("total_duration_minutes")
        dur_b = option_b.get("total_duration_minutes")
        if dur_a is not None and dur_b is not None:
            diff_mins = abs(dur_a - dur_b)
            if dur_a < dur_b:
                points.append(f"Option {option_a.get('id', 'A')} saves {diff_mins // 60}h {diff_mins % 60}m of travel time.")
            elif dur_b < dur_a:
                points.append(f"Option {option_b.get('id', 'B')} saves {diff_mins // 60}h {diff_mins % 60}m of travel time.")

        h_a = option_a.get("hotel") or {}
        h_b = option_b.get("hotel") or {}
        if h_a and h_b:
            stars_a = h_a.get("star_rating") or h_a.get("stars")
            stars_b = h_b.get("star_rating") or h_b.get("stars")
            if stars_a and stars_b and stars_a != stars_b:
                points.append(f"Option {option_a.get('id', 'A')} offers a {stars_a}★ hotel ({h_a.get('hotel_name', 'Hotel A')}) vs {stars_b}★ in Option {option_b.get('id', 'B')}.")

    return {
        "grounded": True,
        "tradeoffs": points,
        "tradeoff_summary": " ".join(points) if points else "No trade-offs identified.",
    }
