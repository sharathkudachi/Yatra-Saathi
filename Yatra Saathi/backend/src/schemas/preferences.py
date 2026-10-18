"""Strongly typed travel preference schemas for Yatra (Phase 4).

Follows project conventions:
- Strict Pydantic models with extra="forbid" where appropriate.
- Distinct provenance (explicit_user, inferred_request, inferred_accepted, system_default).
- Clear semantic distinction between HARD constraints and SOFT preferences.
- Whitelist of approved preference keys to prevent arbitrary key injection.
- Zero floating-point arithmetic for authoritative money.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class PreferenceSource(str, Enum):
    EXPLICIT_USER = "explicit_user"
    INFERRED_REQUEST = "inferred_request"
    INFERRED_ACCEPTED = "inferred_accepted"
    SYSTEM_DEFAULT = "system_default"


class PreferencePriority(str, Enum):
    HARD = "hard"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Whitelist of valid preference keys with their expected types
VALID_PREFERENCE_KEYS = {
    "direct_flights_only": bool,
    "max_acceptable_stops": int,
    "preferred_cabin_class": str,
    "preferred_flight_style": str,
    "min_hotel_star_rating": (int, float),
    "min_hotel_guest_score": (int, float),
    "preferred_hotel_quality": str,
    "preferred_accommodation_style": str,
    "preferred_daily_pace": str,
    "sightseeing_intensity": str,
    "preferred_activity_categories": list,
    "budget_sensitivity": str,
    "comfort_priority": str,
    "speed_priority": str,
    "price_priority": str,
    "dont_change_hotels": bool,
}

VALID_PACING_VALUES = {"relaxed", "moderate", "fast", "packed"}
VALID_PRIORITY_LEVELS = {"high", "moderate", "low", "medium"}
VALID_CABIN_CLASSES = {"economy", "premium_economy", "business", "first"}
VALID_HOTEL_QUALITIES = {"budget", "standard", "upscale", "luxury"}
VALID_ACTIVITY_CATEGORIES = {
    "sightseeing",
    "culture",
    "nature",
    "food",
    "relaxation",
    "adventure",
    "shopping",
    "historical",
    "family",
    "entertainment",
}


class PreferenceItem(BaseModel):
    model_config = {"extra": "forbid"}

    preference_key: str = Field(min_length=1, max_length=64)
    value: Union[bool, int, float, str, List[str]]
    is_hard: bool = False
    priority: PreferencePriority = PreferencePriority.MEDIUM
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: PreferenceSource = PreferenceSource.EXPLICIT_USER
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    active: bool = True

    @field_validator("preference_key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in VALID_PREFERENCE_KEYS:
            raise ValueError(f"Unknown preference key '{clean}'. Must be one of: {sorted(list(VALID_PREFERENCE_KEYS.keys()))}")
        return clean

    @model_validator(mode="after")
    def validate_semantics(self) -> PreferenceItem:
        # Validate value types and ranges according to key
        key = self.preference_key
        val = self.value

        if key in ("direct_flights_only", "dont_change_hotels"):
            if not isinstance(val, bool):
                raise ValueError(f"{key} must be a boolean")
        elif key == "max_acceptable_stops":
            if not isinstance(val, int) or val < 0 or val > 5:
                raise ValueError("max_acceptable_stops must be an integer between 0 and 5")
        elif key == "min_hotel_star_rating":
            if not isinstance(val, (int, float)) or val < 1.0 or val > 5.0:
                raise ValueError("min_hotel_star_rating must be between 1.0 and 5.0")
        elif key == "min_hotel_guest_score":
            if not isinstance(val, (int, float)) or val < 1.0 or val > 10.0:
                raise ValueError("min_hotel_guest_score must be between 1.0 and 10.0")
        elif key == "preferred_daily_pace":
            if not isinstance(val, str) or val.lower() not in VALID_PACING_VALUES:
                raise ValueError(f"preferred_daily_pace must be one of {VALID_PACING_VALUES}")
        elif key in ("budget_sensitivity", "comfort_priority", "speed_priority", "price_priority", "sightseeing_intensity"):
            if not isinstance(val, str) or val.lower() not in VALID_PRIORITY_LEVELS:
                raise ValueError(f"{key} must be one of {VALID_PRIORITY_LEVELS}")
        elif key == "preferred_cabin_class":
            if not isinstance(val, str) or val.lower() not in VALID_CABIN_CLASSES:
                raise ValueError(f"preferred_cabin_class must be one of {VALID_CABIN_CLASSES}")
        elif key == "preferred_hotel_quality":
            if not isinstance(val, str) or val.lower() not in VALID_HOTEL_QUALITIES:
                raise ValueError(f"preferred_hotel_quality must be one of {VALID_HOTEL_QUALITIES}")
        elif key == "preferred_activity_categories":
            if not isinstance(val, list):
                raise ValueError("preferred_activity_categories must be a list of strings")
            for cat in val:
                if not isinstance(cat, str) or cat.lower() not in VALID_ACTIVITY_CATEGORIES:
                    raise ValueError(f"Category '{cat}' is not a valid activity category. Allowed: {sorted(list(VALID_ACTIVITY_CATEGORIES))}")

        # Inferred preferences must not be hard by default unless explicitly justified
        if self.source in (PreferenceSource.INFERRED_REQUEST, PreferenceSource.INFERRED_ACCEPTED, PreferenceSource.SYSTEM_DEFAULT):
            if self.is_hard and self.priority != PreferencePriority.HARD:
                raise ValueError("Inferred preferences cannot be silently marked as hard requirements")

        if self.is_hard:
            self.priority = PreferencePriority.HARD

        return self


class PreferenceMatch(BaseModel):
    model_config = {"extra": "forbid"}

    preference_key: str
    matched: bool
    strength: float = Field(ge=0.0, le=1.0)
    evidence: str
    source: Optional[PreferenceSource] = None


class UserTravelProfile(BaseModel):
    model_config = {"extra": "forbid"}

    user_id: str = Field(min_length=1, max_length=64)
    preferences: dict[str, PreferenceItem] = Field(default_factory=dict)
    updated_at: str


class PreferenceProposal(BaseModel):
    model_config = {"extra": "forbid"}

    proposal_id: str
    preferences: list[PreferenceItem]
    explanation: str
    requires_confirmation: bool = False
    is_ambiguous: bool = False
    clarification_question: Optional[str] = None

    @property
    def proposed_preferences(self) -> list[PreferenceItem]:
        return self.preferences

    @property
    def requires_clarification(self) -> bool:
        return self.is_ambiguous


class UpdatePreferencesRequest(BaseModel):
    model_config = {"extra": "forbid"}

    preferences: list[PreferenceItem]


class ApplyPreferenceProposalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    proposal: PreferenceProposal
    persist_permanently: bool = True
