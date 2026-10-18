"""Phase 5 strongly typed Pydantic contracts for booking lifecycle.

Follows project conventions:
- Strict types, no floats for money
- All booking state changes go through backend services only
- AI may read but never mutate booking state
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# Booking Lifecycle State Machine
# ============================================================

class BookingStatus(str, Enum):
    DRAFT = "draft"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    HOLDING = "holding"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    HOLD_FAILED = "hold_failed"
    CONFIRMATION_FAILED = "confirmation_failed"
    CANCELLATION_FAILED = "cancellation_failed"


# Allowed state transitions — explicit state machine
BOOKING_STATE_TRANSITIONS: dict[str, set[str]] = {
    BookingStatus.DRAFT: {BookingStatus.READY_FOR_CONFIRMATION, BookingStatus.CANCELLED},
    BookingStatus.READY_FOR_CONFIRMATION: {BookingStatus.HOLDING, BookingStatus.CANCELLED},
    BookingStatus.HOLDING: {BookingStatus.CONFIRMED, BookingStatus.HOLD_FAILED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
    BookingStatus.HOLD_FAILED: {BookingStatus.DRAFT},
    BookingStatus.CONFIRMATION_FAILED: {BookingStatus.DRAFT},
    BookingStatus.CANCELLATION_FAILED: {BookingStatus.CONFIRMED},
}


class TripLifecycleStatus(str, Enum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class HoldStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"
    CONSUMED = "consumed"


# ============================================================
# Booking Review Request / Response
# ============================================================

class BookingTravellerInfo(BaseModel):
    """Minimal safe traveller info for demo booking."""
    display_name: str = Field(min_length=1, max_length=200)
    traveller_role: str = Field(default="adult", pattern=r"^(adult|child|infant)$")

    model_config = {"extra": "forbid"}


class BookingReviewRequest(BaseModel):
    """Request to generate a booking review for an itinerary. Frontend provides itinerary_id + version.
    Backend recalculates ALL authoritative totals — no trust in frontend totals."""
    itinerary_id: str = Field(min_length=1, max_length=64)
    itinerary_version: int = Field(ge=1)
    travellers: list[BookingTravellerInfo] = Field(min_length=1, max_length=20)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    model_config = {"extra": "forbid"}


class BookingItemSummary(BaseModel):
    """Summary of one bookable component (flight, hotel, activity)."""
    item_type: str  # 'flight', 'hotel', 'activity'
    title: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    for_date: Optional[str] = None
    quantity: int = 1
    authoritative_price: Optional[str] = None  # text money e.g. "12000.00"
    estimated_price: Optional[str] = None      # for activities with uncertain pricing
    currency: str
    is_authoritative: bool = True  # False for estimated items

    model_config = {"extra": "forbid"}


class BookingReviewResponse(BaseModel):
    """Full booking review payload returned by backend. Frontend MUST display this before confirmation."""
    review_token: str                          # opaque token binding to itinerary + version + total
    itinerary_id: str
    itinerary_version: int
    destination: str
    origin: str
    start_date: str
    end_date: str
    travellers: list[BookingTravellerInfo]
    traveller_count: int
    items: list[BookingItemSummary]
    transport_total: str                       # authoritative
    accommodation_total: str                  # authoritative
    estimated_activities_total: str           # estimated, not authoritative
    authoritative_subtotal: str               # transport + accommodation only
    tax_amount: str
    authoritative_total: str                  # what will be charged (demo)
    currency: str
    booking_mode: str = "DEMO / SIMULATED"
    demo_label: str = "DEMO BOOKING — NO REAL PAYMENT"
    review_expires_at: str
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ============================================================
# Booking Confirmation
# ============================================================

class ConfirmBookingRequest(BaseModel):
    """Explicit confirmation payload. Must match the review_token exactly."""
    review_token: str = Field(min_length=1, max_length=256)
    itinerary_id: str = Field(min_length=1, max_length=64)
    itinerary_version: int = Field(ge=1)
    authoritative_total: str = Field(pattern=r"^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    travellers: list[BookingTravellerInfo] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=8, max_length=128)

    model_config = {"extra": "forbid"}


class ConfirmBookingResponse(BaseModel):
    booking_id: str
    booking_reference: str               # YTR-DEMO-XXXXXXXX, backend-generated
    status: str                          # 'confirmed'
    lifecycle_status: str
    itinerary_id: str
    itinerary_version: int
    authoritative_total: str
    currency: str
    created_at: str
    booking_mode: str = "DEMO / SIMULATED"
    demo_label: str = "Yatra Saathi demo reservation has been confirmed. This is a simulated booking."
    items: list[BookingItemSummary] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ============================================================
# Booking Status
# ============================================================

class BookingStatusResponse(BaseModel):
    booking_id: str
    booking_reference: str
    status: str
    lifecycle_status: str
    itinerary_id: Optional[str]
    itinerary_version: Optional[int]
    destination: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    authoritative_total: str
    currency: str
    created_at: str
    updated_at: str
    cancelled_at: Optional[str]
    cancellation_reason: Optional[str]
    booking_mode: str = "DEMO / SIMULATED"
    demo_label: str = "DEMO / SIMULATED"
    items: list[BookingItemSummary] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ============================================================
# Cancellation
# ============================================================

class CancelBookingRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    model_config = {"extra": "forbid"}


class CancelBookingResponse(BaseModel):
    booking_id: str
    booking_reference: str
    status: str
    cancelled_at: str
    cancellation_reason: Optional[str]
    message: str = "Your Yatra Saathi demo booking has been cancelled."

    model_config = {"extra": "forbid"}


# ============================================================
# Trip Detail
# ============================================================

class TripDetailResponse(BaseModel):
    trip_id: Optional[str]
    booking_id: Optional[str]
    booking_reference: Optional[str]
    destination: str
    origin: str
    start_date: str
    end_date: str
    traveller_count: int
    status: str
    lifecycle_status: str
    authoritative_total: Optional[str]
    currency: Optional[str]
    booking_mode: str = "DEMO / SIMULATED"
    itinerary: Optional[Any] = None
    items: list[BookingItemSummary] = Field(default_factory=list)
    timeline_events: list[dict] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ============================================================
# Trip Pack
# ============================================================

class TripPackResponse(BaseModel):
    pack_id: str
    booking_id: str
    booking_reference: str
    destination: str
    origin: str
    start_date: str
    end_date: str
    travellers: list[BookingTravellerInfo]
    transport_summary: list[BookingItemSummary]
    accommodation_summary: list[BookingItemSummary]
    activities_summary: list[BookingItemSummary]
    authoritative_total: str
    currency: str
    itinerary: Optional[Any] = None
    important_notes: list[str] = Field(default_factory=list)
    generated_at: str
    demo_label: str = "YATRA DEMO TRIP PACK"
    demo_notice: str = (
        "This is a planning/summary document for a simulated demo booking. "
        "It is NOT an official travel document, airline ticket, or hotel voucher. "
        "No real payment has been processed. No real supplier reservation exists."
    )

    model_config = {"extra": "forbid"}


# ============================================================
# AI Booking Tool Contracts (bounded — AI reads only, cannot mutate)
# ============================================================

class AIBookingStatusQuery(BaseModel):
    """AI tool: query booking status for a session. AI cannot mutate state."""
    session_id: str
    booking_id: Optional[str] = None

    model_config = {"extra": "forbid"}


class AICancelIntentRequest(BaseModel):
    """AI tool: surface cancellation intent for backend processing. Human must confirm."""
    booking_id: str
    reason: Optional[str] = None

    model_config = {"extra": "forbid"}


class AITripSummaryRequest(BaseModel):
    """AI tool: request trip summary. Read-only."""
    booking_id: Optional[str] = None
    session_id: Optional[str] = None

    model_config = {"extra": "forbid"}
