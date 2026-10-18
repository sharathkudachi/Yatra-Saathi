"""Preference service for Yatra (Phase 4).

Governs:
- Strict user-authenticated CRUD operations on travel preferences.
- Provenance tracking (explicit, inferred, accepted, default).
- Deterministic preference priority and conflict resolution:
    Explicit current hard constraint
            >
    Explicit current soft preference
            >
    Session preference
            >
    Persistent preference
            >
    System default
- Grounded preference matching for flights, hotels, and itineraries.
- Transparent score calculations: Base Score + Preference Adjustment = Final Score.
- Structured audit event recording.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.contracts.codes import RefusalError
from src.core.clock import Clock
from src.core.ids import new_id
from src.db.repositories import preferences as pref_repo
from src.schemas.preferences import (
    PreferenceItem,
    PreferenceMatch,
    PreferencePriority,
    PreferenceProposal,
    PreferenceSource,
    UserTravelProfile,
    VALID_PREFERENCE_KEYS,
)

_PREFERENCE_AUDIT_LOG: list[dict] = []


def get_preference_audit_log() -> list[dict]:
    """Retrieve audit events logged during preference actions."""
    return list(_PREFERENCE_AUDIT_LOG)


def record_phase4_audit_event(
    conn: Optional[sqlite3.Connection],
    clock: Optional[Clock],
    user_id: str,
    event_type: str,
    entity_id: Optional[str],
    metadata: dict,
) -> dict:
    """Record a structured audit event for Phase 4 actions safely without storing secrets."""
    now_str = clock.utc() if clock else datetime.now(timezone.utc).isoformat()
    record = {
        "event_id": new_id("aud"),
        "user_id": user_id,
        "event_type": event_type,
        "entity_id": entity_id,
        "occurred_at": now_str,
        "metadata": {k: v for k, v in metadata.items() if not str(k).lower().endswith("token") and not str(k).lower().endswith("secret")},
    }
    _PREFERENCE_AUDIT_LOG.append(record)
    return record


def get_user_profile(
    conn: sqlite3.Connection,
    user_id: str,
    clock: Optional[Clock] = None,
) -> UserTravelProfile:
    """Retrieve the travel preference profile for an authenticated user."""
    if not user_id or not user_id.strip():
        raise RefusalError("USER_NOT_FOUND", "user_id is required", http_status=401)

    prefs = pref_repo.get_preferences_for_user(conn, user_id)
    now_str = clock.utc() if clock else datetime.now(timezone.utc).isoformat()

    record_phase4_audit_event(
        conn, clock, user_id,
        "PREFERENCE_VIEWED",
        user_id,
        {"count": len(prefs)},
    )

    return UserTravelProfile(
        user_id=user_id,
        preferences=prefs,
        updated_at=now_str,
    )


def update_user_preferences(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    items: List[PreferenceItem],
) -> UserTravelProfile:
    """Update or add preferences for the authenticated user."""
    if not user_id or not user_id.strip():
        raise RefusalError("USER_NOT_FOUND", "user_id is required", http_status=401)

    now_str = clock.utc()
    saved: Dict[str, PreferenceItem] = {}
    for item in items:
        # Validate that the item key is strictly whitelisted
        if item.preference_key not in VALID_PREFERENCE_KEYS:
            raise RefusalError(
                "INVALID_PREFERENCE",
                f"Preference key '{item.preference_key}' is not allowed",
                http_status=422,
            )
        upserted = pref_repo.upsert_preference(conn, user_id, item, now_iso=now_str)
        saved[upserted.preference_key] = upserted

    record_phase4_audit_event(
        conn, clock, user_id,
        "PREFERENCE_UPDATED",
        user_id,
        {"updated_keys": [item.preference_key for item in items]},
    )

    all_prefs = pref_repo.get_preferences_for_user(conn, user_id)
    return UserTravelProfile(
        user_id=user_id,
        preferences=all_prefs,
        updated_at=now_str,
    )


def delete_user_preference(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
    preference_key: str,
) -> bool:
    """Remove a specific preference from the authenticated user's profile."""
    if not user_id or not user_id.strip():
        raise RefusalError("USER_NOT_FOUND", "user_id is required", http_status=401)

    key_clean = preference_key.strip().lower()
    if key_clean not in VALID_PREFERENCE_KEYS:
        raise RefusalError("INVALID_PREFERENCE", f"Unknown preference key '{key_clean}'", http_status=422)

    deleted = pref_repo.delete_preference(conn, user_id, key_clean)
    if deleted:
        record_phase4_audit_event(
            conn, clock, user_id,
            "PREFERENCE_REMOVED",
            user_id,
            {"removed_key": key_clean},
        )
    return deleted


def reset_user_preferences(
    conn: sqlite3.Connection,
    clock: Clock,
    user_id: str,
) -> int:
    """Clear all preferences for the authenticated user."""
    if not user_id or not user_id.strip():
        raise RefusalError("USER_NOT_FOUND", "user_id is required", http_status=401)

    count = pref_repo.clear_preferences_for_user(conn, user_id)
    record_phase4_audit_event(
        conn, clock, user_id,
        "PREFERENCE_RESET",
        user_id,
        {"cleared_count": count},
    )
    return count


class PreferenceValue:
    def __init__(self, value: Any, is_hard: bool = False, priority: str = "medium", source: str = "system_default"):
        self.value = value
        self.is_hard = is_hard
        self.priority = priority
        self.source = source

    def __bool__(self) -> bool:
        return bool(self.value)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, PreferenceValue):
            return self.value == other.value
        return self.value == other

    def __hash__(self) -> int:
        return hash(self.value)

    def __float__(self) -> float:
        return float(self.value)

    def __int__(self) -> int:
        return int(self.value)

    def __iter__(self):
        if isinstance(self.value, (list, tuple, set)):
            return iter(self.value)
        return iter([self.value])

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"PreferenceValue(value={self.value!r}, is_hard={self.is_hard})"


def resolve_effective_preferences(
    saved_preferences: Optional[Union[Dict[str, PreferenceItem], UserTravelProfile]] = None,
    *,
    request_text: Optional[str] = None,
    current_request_prefs: Optional[str] = None,
    session_preferences: Optional[Dict[str, Any]] = None,
    session_prefs: Optional[Dict[str, Any]] = None,
    persistent_profile: Optional[UserTravelProfile] = None,
) -> Dict[str, Any]:
    """Resolve effective preferences using the deterministic priority hierarchy.

    Hierarchy:
    1. Explicit current hard constraint (from request_text / session)
    2. Explicit current soft preference (from request_text)
    3. Session preference
    4. Persistent user preference
    5. System defaults
    """
    defaults = {
        "direct_flights_only": (False, False, "low", "system_default"),
        "max_acceptable_stops": (2, False, "medium", "system_default"),
        "min_hotel_star_rating": (3.0, False, "medium", "system_default"),
        "min_hotel_guest_score": (7.0, False, "medium", "system_default"),
        "preferred_daily_pace": ("moderate", False, "medium", "system_default"),
        "preferred_activity_categories": (["sightseeing", "culture"], False, "medium", "system_default"),
        "price_priority": ("moderate", False, "medium", "system_default"),
        "comfort_priority": ("moderate", False, "medium", "system_default"),
        "dont_change_hotels": (False, False, "low", "system_default"),
    }

    effective_obj: Dict[str, PreferenceValue] = {}
    for k, (def_val, def_hard, def_prio, def_src) in defaults.items():
        effective_obj[k] = PreferenceValue(def_val, is_hard=def_hard, priority=def_prio, source=def_src)

    # 1. Overlay persistent preferences
    saved_items = {}
    if persistent_profile and hasattr(persistent_profile, "preferences"):
        saved_items = persistent_profile.preferences
    elif isinstance(saved_preferences, UserTravelProfile):
        saved_items = saved_preferences.preferences
    elif isinstance(saved_preferences, dict):
        saved_items = saved_preferences

    for k, item in saved_items.items():
        if isinstance(item, PreferenceItem) and item.active:
            effective_obj[k] = PreferenceValue(
                item.value,
                is_hard=item.is_hard,
                priority=item.priority.value if hasattr(item.priority, "value") else str(item.priority),
                source=item.source.value if hasattr(item.source, "value") else str(item.source),
            )
        elif isinstance(item, dict):
            effective_obj[k] = PreferenceValue(
                item.get("value"),
                is_hard=bool(item.get("is_hard")),
                priority=str(item.get("priority", "medium")),
                source=str(item.get("source", "explicit_user")),
            )

    # 2. Overlay session preferences
    sess_dict = session_preferences or session_prefs or {}
    for k, item in sess_dict.items():
        if isinstance(item, PreferenceItem):
            effective_obj[k] = PreferenceValue(
                item.value,
                is_hard=item.is_hard,
                priority=item.priority.value if hasattr(item.priority, "value") else str(item.priority),
                source=item.source.value if hasattr(item.source, "value") else str(item.source),
            )
        elif isinstance(item, dict):
            effective_obj[k] = PreferenceValue(
                item.get("value"),
                is_hard=bool(item.get("is_hard")),
                priority=str(item.get("priority", "medium")),
                source=str(item.get("source", "inferred_request")),
            )
        elif item is not None:
            effective_obj[k] = PreferenceValue(item, is_hard=False, priority="high", source="session")

    # 3. Process explicit current request text overrides
    req_txt = request_text or current_request_prefs or ""
    if req_txt:
        text_lower = req_txt.lower()

        # Direct flights override
        if any(p in text_lower for p in ("don't care about direct", "do not care about direct", "stops are fine", "including flights with stops", "any flight")):
            effective_obj["direct_flights_only"] = PreferenceValue(False, is_hard=False, priority="low", source="current_request")
            effective_obj["_overridden_direct_flights"] = PreferenceValue(True)
        elif any(p in text_lower for p in ("only direct", "must be direct", "non-stop only")):
            effective_obj["direct_flights_only"] = PreferenceValue(True, is_hard=True, priority="hard", source="current_request")
            effective_obj["_hard_direct_flights"] = PreferenceValue(True)
        elif any(p in text_lower for p in ("prefer direct", "direct flight", "keep direct flight", "keep my direct")):
            effective_obj["direct_flights_only"] = PreferenceValue(True, is_hard=False, priority="high", source="current_request")

        # Rating override
        if any(p in text_lower for p in ("regardless of rating", "any rating", "don't care about star", "cheapest hotel regardless")):
            effective_obj["min_hotel_star_rating"] = PreferenceValue(1.0, is_hard=False, priority="low", source="current_request")
            effective_obj["min_hotel_guest_score"] = PreferenceValue(1.0, is_hard=False, priority="low", source="current_request")
            effective_obj["_overridden_hotel_rating"] = PreferenceValue(True)
        elif re.search(r"\b(need|require|must have)\s+(a\s+)?([45])[- ]?star\b", text_lower):
            m = re.search(r"\b(need|require|must have)\s+(a\s+)?([45])[- ]?star\b", text_lower)
            stars = float(m.group(3))
            effective_obj["min_hotel_star_rating"] = PreferenceValue(stars, is_hard=True, priority="hard", source="current_request")
            effective_obj["_hard_hotel_stars"] = PreferenceValue(True)
        elif re.search(r"\b([45])[- ]?star\b", text_lower):
            m = re.search(r"\b([45])[- ]?star\b", text_lower)
            effective_obj["min_hotel_star_rating"] = PreferenceValue(float(m.group(1)), is_hard=False, priority="high", source="current_request")

        # Pacing
        if any(p in text_lower for p in ("relaxed", "unhurried", "leisurely", "not too much rushing", "not rushed")):
            effective_obj["preferred_daily_pace"] = PreferenceValue("relaxed", is_hard=False, priority="high", source="current_request")
        elif any(p in text_lower for p in ("packed", "fast pace", "cover everything")):
            effective_obj["preferred_daily_pace"] = PreferenceValue("fast", is_hard=False, priority="medium", source="current_request")

        # Priorities
        if any(p in text_lower for p in ("cheapest", "lowest price", "budget is more important", "price is more important")):
            effective_obj["price_priority"] = PreferenceValue("high", is_hard=False, priority="high", source="current_request")
            effective_obj["comfort_priority"] = PreferenceValue("low", is_hard=False, priority="low", source="current_request")
        elif any(p in text_lower for p in ("most comfortable", "comfort is more important", "luxury", "keep it comfortable", "book the most comfortable")):
            effective_obj["comfort_priority"] = PreferenceValue("high", is_hard=False, priority="high", source="current_request")
            effective_obj["price_priority"] = PreferenceValue("low", is_hard=False, priority="low", source="current_request")

        # Activities
        cats = list(effective_obj["preferred_activity_categories"].value or [])
        if "sightseeing" in text_lower and "sightseeing" not in cats:
            cats.append("sightseeing")
        if any(c in text_lower for c in ("culture", "cultural", "historical")) and "culture" not in cats:
            cats.append("culture")
        if any(c in text_lower for c in ("nature", "parks")) and "nature" not in cats:
            cats.append("nature")
        effective_obj["preferred_activity_categories"] = PreferenceValue(cats, is_hard=False, priority="high", source="current_request")

    return effective_obj


def evaluate_option_preferences(
    flight_detail: Optional[Any],
    hotel_detail: Optional[Any],
    effective_prefs: Dict[str, Any],
) -> Tuple[float, List[PreferenceMatch], List[str]]:
    """Evaluate how well a travel option fits user preferences.

    Returns:
    - preference_score: 0.0 to 10.0 score component
    - matches: list of structured PreferenceMatch objects
    - reasons: human-friendly grounded explanation bullets
    """
    matches: List[PreferenceMatch] = []
    reasons: List[str] = []
    score_points: float = 7.0  # Base neutral score

    # 1. Direct flight evaluation
    direct_pref = effective_prefs.get("direct_flights_only", False)
    if flight_detail:
        is_direct = getattr(flight_detail, "is_direct", True)
        stops = getattr(flight_detail, "total_stops", 0)

        if direct_pref:
            if is_direct:
                matches.append(PreferenceMatch(
                    preference_key="direct_flights_only",
                    matched=True,
                    strength=1.0,
                    evidence="Flight is direct/non-stop as requested",
                    source=PreferenceSource.EXPLICIT_USER,
                ))
                reasons.append("Direct non-stop flight aligns with your travel style")
                score_points += 1.5
            else:
                matches.append(PreferenceMatch(
                    preference_key="direct_flights_only",
                    matched=False,
                    strength=0.0,
                    evidence=f"Flight has {stops} stop(s)",
                    source=PreferenceSource.EXPLICIT_USER,
                ))
                score_points -= 2.0

    # 2. Hotel star rating and guest score evaluation
    min_stars = float(effective_prefs.get("min_hotel_star_rating", 3.0))
    min_guest = float(effective_prefs.get("min_hotel_guest_score", 7.0))
    if hotel_detail:
        stars = float(getattr(hotel_detail, "star_rating", 0.0) or 0.0)
        guest = float(getattr(hotel_detail, "guest_score", 0.0) or 0.0)

        if stars >= min_stars:
            matches.append(PreferenceMatch(
                preference_key="min_hotel_star_rating",
                matched=True,
                strength=1.0,
                evidence=f"{stars:.1f}-star rating satisfies preference (>= {min_stars:.1f})",
                source=PreferenceSource.EXPLICIT_USER,
            ))
            reasons.append(f"Hotel meets your preferred quality level ({stars:.0f}-star)")
            score_points += 1.0
        elif stars > 0:
            matches.append(PreferenceMatch(
                preference_key="min_hotel_star_rating",
                matched=False,
                strength=max(0.0, stars / max(min_stars, 1.0)),
                evidence=f"{stars:.1f}-star rating is below preferred {min_stars:.1f}-star",
                source=PreferenceSource.EXPLICIT_USER,
            ))
            score_points -= 1.0

        if guest >= min_guest:
            matches.append(PreferenceMatch(
                preference_key="min_hotel_guest_score",
                matched=True,
                strength=1.0,
                evidence=f"Guest score {guest:.1f} meets minimum {min_guest:.1f}",
                source=PreferenceSource.EXPLICIT_USER,
            ))
            score_points += 0.5

    # 3. Price / Comfort priority weighting
    price_pri = effective_prefs.get("price_priority", "moderate")
    comfort_pri = effective_prefs.get("comfort_priority", "moderate")

    if comfort_pri == "high" and hotel_detail:
        stars = float(getattr(hotel_detail, "star_rating", 0.0) or 0.0)
        if stars >= 4.0:
            reasons.append("Premium hotel accommodates your high comfort priority")
            score_points += 1.0
    elif price_pri == "high":
        # Handled primarily by comparison price weighting, add notation
        reasons.append("Cost-effective selection tailored to price sensitivity")

    final_pref_score = round(min(10.0, max(1.0, score_points)), 1)
    return final_pref_score, matches, reasons
