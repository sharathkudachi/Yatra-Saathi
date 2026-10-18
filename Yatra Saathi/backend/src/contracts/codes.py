"""Refusal codes shared with the agent service (approved, section 12).

Both Developer 1 and Developer 2 must agree on changes to this file.
"""
from __future__ import annotations

REFUSAL_CODES = frozenset({
    "SPEND_CAP_EXCEEDED", "CURRENCY_MISMATCH", "INVALID_QUANTITY", "MALFORMED_ITEM",
    "DUPLICATE_ITEM", "UNKNOWN_INVENTORY", "ENTITY_MISMATCH", "DATE_IN_PAST",
    "DATE_OUTSIDE_TRIP", "MISSING_NIGHTS", "INSUFFICIENT_AVAILABILITY",
    "MIN_STAY_NOT_MET", "CLOSED_TO_ARRIVAL", "OCCUPANCY_EXCEEDED", "NOT_BOOKABLE",
    "UNKNOWN_OFFER_REF", "PRICE_MISMATCH", "CART_LOCKED", "CART_EMPTY",
    "REPLAN_LIMIT_REACHED", "INVALID_STATE", "SESSION_ACCESS_DENIED",
    "STATE_VERSION_CONFLICT", "STATE_INVALID", "STATE_TOO_LARGE", "STATE_CORRUPT",
    "CONFIRMATION_MISSING", "CONFIRMATION_EXPIRED", "CONFIRMATION_STALE",
    "CONFIRMATION_ALREADY_USED", "CONFIRMATION_NOT_OWNER", "SESSION_ALREADY_BOOKED",
    "PRICE_CHANGED", "SOLD_OUT", "HOLD_EXPIRED",
})

# Additional codes needed for auth/token failures, kept distinct from the
# domain refusal codes above but returned through the same envelope shape.
AUTH_REFUSAL_CODES = frozenset({
    "TOKEN_MISSING", "TOKEN_INVALID", "TOKEN_EXPIRED", "TOKEN_WRONG_ROLE",
    "USER_NOT_ALLOWED", "USER_NOT_FOUND", "USER_INACTIVE", "LOGIN_MISMATCH",
    "DUPLICATE_USERNAME", "DUPLICATE_EMAIL", "INVALID_USERNAME", "INVALID_EMAIL",
    "WEAK_PASSWORD", "INVALID_NAME", "AUTH_RATE_LIMITED", "REGISTRATION_FAILED",
})

# Phase 4: Preference & Exploration refusal codes (Section 34)
PHASE4_REFUSAL_CODES = frozenset({
    "INVALID_PREFERENCE",
    "PREFERENCE_CONFLICT",
    "PREFERENCE_NOT_FOUND",
    "DESTINATION_NOT_FOUND",
    "POI_NOT_FOUND",
    "HOTEL_NOT_FOUND",
    "ROOM_TYPE_NOT_FOUND",
    "INVALID_ITINERARY",
    "OWNERSHIP_DENIED",
    "NO_MATCHING_OPTIONS",
    "NO_FEASIBLE_SOLUTION",
    "INVALID_COORDINATES",
    "BUDGET_EXCEEDED",
    "CATALOG_GROUNDING_FAILED",
    "DUPLICATE_ACTIVITY",
    "INVALID_DAY_NUMBER",
    "DATE_MISMATCH",
    "INVALID_OPTION",
})

# Phase 5: Booking Lifecycle, Trip Management & Travel Document refusal codes
PHASE5_REFUSAL_CODES = frozenset({
    # Booking general
    "BOOKING_NOT_FOUND",
    "BOOKING_ALREADY_CONFIRMED",
    "BOOKING_ALREADY_CANCELLED",
    "BOOKING_CONFIRMATION_REQUIRED",
    "INVALID_BOOKING_STATE",
    "BOOKING_OWNERSHIP_DENIED",
    "BOOKING_TOTAL_CHANGED",
    "CURRENCY_MISMATCH",
    # Itinerary / version safety
    "ITINERARY_VERSION_CHANGED",
    "ITINERARY_NOT_BOOKABLE",
    "ITINERARY_OWNERSHIP_DENIED",
    # Inventory
    "INVENTORY_UNAVAILABLE",
    # Hold
    "HOLD_NOT_FOUND",
    # Trip
    "TRIP_NOT_FOUND",
    "TRIP_OWNERSHIP_DENIED",
    # Cancellation
    "CANCELLATION_NOT_ALLOWED",
    # Idempotency
    "INVALID_IDEMPOTENCY_KEY",
    # Catalog
    "CATALOG_ENTITY_NOT_FOUND",
    # Trip pack
    "TRIP_PACK_UNAVAILABLE",
})

# Phase 6: Multilingual, Voice, Notifications & Emergency Assistance refusal codes
PHASE6_REFUSAL_CODES = frozenset({
    "UNSUPPORTED_LANGUAGE",
    "LANGUAGE_DETECTION_LOW_CONFIDENCE",
    "VOICE_TRANSCRIPTION_FAILED",
    "EXPLICIT_CONFIRMATION_REQUIRED",
    "NOTIFICATION_NOT_FOUND",
    "NOTIFICATION_OWNERSHIP_DENIED",
    "EMERGENCY_ACCESS_DENIED",
    "EMERGENCY_CONTACT_NOT_FOUND",
    "EMERGENCY_CONFIG_UNAVAILABLE",
    "TRIP_SHARE_REFUSED",
    "INVALID_NOTIFICATION_PREFERENCE",
    "DUPLICATE_CONTACT",
})

ALL_REFUSAL_CODES = REFUSAL_CODES | AUTH_REFUSAL_CODES | PHASE4_REFUSAL_CODES | PHASE5_REFUSAL_CODES | PHASE6_REFUSAL_CODES


class RefusalError(Exception):
    """Raised by services when an action must be refused with a specific code."""

    def __init__(self, code: str, message: str, *, http_status: int = 400, **details: object):
        if code not in ALL_REFUSAL_CODES:
            raise ValueError(f"unknown refusal code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details
