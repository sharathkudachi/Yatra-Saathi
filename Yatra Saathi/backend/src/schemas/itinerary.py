"""Strongly typed itinerary and trip plan schemas for Yatra (Phase 2A).

Follows project conventions:
- Strict ISO dates (YYYY-MM-DD).
- Authoritative money follows core.money (non-negative text with at most 2 decimals).
- Coordinates must be authoritative and within -90..90, -180..180.
- Rejects unknown fields (extra="forbid").
"""
from __future__ import annotations

import math
from datetime import date
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.dates import date_order_error, parse_date_only
from src.core.geo import is_valid_coord


MONEY_PATTERN = r"^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$"


class ItineraryStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    AWAITING_INPUT = "awaiting_input"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


VALID_LIFECYCLE_TRANSITIONS: dict[ItineraryStatus, set[ItineraryStatus]] = {
    ItineraryStatus.DRAFT: {ItineraryStatus.PLANNED, ItineraryStatus.AWAITING_INPUT, ItineraryStatus.CANCELLED},
    ItineraryStatus.PLANNED: {ItineraryStatus.DRAFT, ItineraryStatus.AWAITING_INPUT, ItineraryStatus.CONFIRMED, ItineraryStatus.CANCELLED},
    ItineraryStatus.AWAITING_INPUT: {ItineraryStatus.DRAFT, ItineraryStatus.PLANNED, ItineraryStatus.CANCELLED},
    ItineraryStatus.CONFIRMED: {ItineraryStatus.CANCELLED},
    ItineraryStatus.CANCELLED: set(),
}


class ActivityCategory(str, Enum):
    ARRIVAL = "arrival"
    DEPARTURE = "departure"
    STAY = "stay"
    FLIGHT = "flight"
    FOOD = "food"
    CULTURE = "culture"
    NATURE = "nature"
    ACTIVITY = "activity"
    TRANSPORT = "transport"
    FREE_TIME = "free_time"
    OTHER = "other"


class TransportType(str, Enum):
    FLIGHT = "flight"
    TRAIN = "train"
    BUS = "bus"
    CAB = "cab"
    FERRY = "ferry"
    OTHER = "other"


class ItemSource(str, Enum):
    BACKEND = "backend"
    CATALOG = "catalog"
    USER = "user"
    AI_PLANNER = "ai_planner"
    MANUAL = "manual"


class ItineraryActivity(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    start_time: Optional[str] = Field(default=None, max_length=35)
    end_time: Optional[str] = Field(default=None, max_length=35)
    location: Optional[str] = Field(default=None, max_length=200)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    estimated_cost: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    authoritative_cost: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    category: ActivityCategory = ActivityCategory.ACTIVITY
    source: ItemSource = ItemSource.USER
    entity_type: Optional[str] = Field(default=None, max_length=64)
    entity_id: Optional[str] = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}

    @field_validator("latitude")
    @classmethod
    def _val_lat(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or not (-90.0 <= v <= 90.0):
                raise ValueError(f"latitude {v} must be between -90 and +90")
        return v

    @field_validator("longitude")
    @classmethod
    def _val_lng(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or not (-180.0 <= v <= 180.0):
                raise ValueError(f"longitude {v} must be between -180 and +180")
        return v

    @model_validator(mode="after")
    def _val_activity_times(self) -> "ItineraryActivity":
        if self.start_time and self.end_time:
            # If both are standard HH:MM format
            if len(self.start_time) == 5 and len(self.end_time) == 5 and ":" in self.start_time and ":" in self.end_time:
                if self.start_time > self.end_time:
                    raise ValueError(f"end_time {self.end_time} cannot be before start_time {self.start_time}")
        return self


class ItineraryDay(BaseModel):
    date: date
    day_number: int = Field(ge=1, le=365)
    title: str = Field(min_length=1, max_length=200)
    activities: list[ItineraryActivity] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, max_length=2000)
    estimated_cost: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)

    model_config = {"extra": "forbid"}

    @field_validator("date", mode="before")
    @classmethod
    def _val_day_date(cls, v: Any) -> date:
        return parse_date_only(v)


class TransportSegment(BaseModel):
    id: Optional[str] = Field(default=None, max_length=64)
    type: TransportType = TransportType.FLIGHT
    origin: str = Field(min_length=1, max_length=200)
    origin_code: Optional[str] = Field(default=None, max_length=10)
    destination: str = Field(min_length=1, max_length=200)
    dest_code: Optional[str] = Field(default=None, max_length=10)
    carrier: Optional[str] = Field(default=None, max_length=200)
    reference: Optional[str] = Field(default=None, max_length=64)
    departs_at: str = Field(min_length=1, max_length=35)
    arrives_at: str = Field(min_length=1, max_length=35)
    known_price: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    origin_latitude: Optional[float] = None
    origin_longitude: Optional[float] = None
    dest_latitude: Optional[float] = None
    dest_longitude: Optional[float] = None
    entity_type: Optional[str] = Field(default=None, max_length=64)
    entity_id: Optional[str] = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}

    @field_validator("origin_latitude", "dest_latitude")
    @classmethod
    def _val_segment_lat(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or not (-90.0 <= v <= 90.0):
                raise ValueError(f"latitude {v} must be between -90 and +90")
        return v

    @field_validator("origin_longitude", "dest_longitude")
    @classmethod
    def _val_segment_lng(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or not (-180.0 <= v <= 180.0):
                raise ValueError(f"longitude {v} must be between -180 and +180")
        return v


class AccommodationStay(BaseModel):
    id: Optional[str] = Field(default=None, max_length=64)
    hotel_id: Optional[str] = Field(default=None, max_length=64)
    hotel_name: str = Field(min_length=1, max_length=200)
    room_type_id: Optional[str] = Field(default=None, max_length=64)
    room_name: Optional[str] = Field(default=None, max_length=200)
    address: Optional[str] = Field(default=None, max_length=500)
    check_in_date: date
    check_out_date: date
    known_price: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    model_config = {"extra": "forbid"}

    @field_validator("check_in_date", "check_out_date", mode="before")
    @classmethod
    def _val_stay_date(cls, v: Any) -> date:
        return parse_date_only(v)

    @field_validator("latitude")
    @classmethod
    def _val_stay_lat(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or not (-90.0 <= v <= 90.0):
                raise ValueError(f"latitude {v} must be between -90 and +90")
        return v

    @field_validator("longitude")
    @classmethod
    def _val_stay_lng(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v) or not (-180.0 <= v <= 180.0):
                raise ValueError(f"longitude {v} must be between -180 and +180")
        return v

    @model_validator(mode="after")
    def _val_stay_order(self) -> "AccommodationStay":
        if self.check_out_date <= self.check_in_date:
            raise ValueError(f"check_out_date {self.check_out_date.isoformat()} must be after check_in_date {self.check_in_date.isoformat()}")
        return self


class TripPlan(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    trip_id: Optional[str] = Field(default=None, max_length=64)
    session_id: Optional[str] = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    travellers: int = Field(ge=1, le=50)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    budget: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    total_estimated_cost: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    total_authoritative_cost: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    transport: list[TransportSegment] = Field(default_factory=list)
    accommodation: list[AccommodationStay] = Field(default_factory=list)
    days: list[ItineraryDay] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    status: ItineraryStatus = ItineraryStatus.DRAFT
    version: int = Field(default=1, ge=1)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"extra": "forbid"}

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _val_trip_date(cls, v: Any) -> date:
        return parse_date_only(v)

    @model_validator(mode="after")
    def _val_trip_plan_constraints(self) -> "TripPlan":
        if self.end_date < self.start_date:
            raise ValueError(f"end_date {self.end_date.isoformat()} cannot be before start_date {self.start_date.isoformat()}")
        for day in self.days:
            if day.date < self.start_date or day.date > self.end_date:
                raise ValueError(
                    f"itinerary day date {day.date.isoformat()} must be between trip start_date {self.start_date.isoformat()} and end_date {self.end_date.isoformat()}"
                )
        return self

    @property
    def itinerary(self) -> "TripPlan":
        return self

    @property
    def accommodations(self) -> list[AccommodationStay]:
        return self.accommodation


class GenerateItineraryRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=64)
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    travellers: int = Field(ge=1, le=50)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    budget: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    preferences: Optional[str] = Field(default=None, max_length=1000)
    style: Optional[str] = Field(default="balanced", max_length=50)
    selected_transport_reference: Optional[str] = Field(default=None, max_length=64)
    selected_hotel_id: Optional[str] = Field(default=None, max_length=64)
    transport_options: list[TransportSegment] = Field(default_factory=list)
    accommodation_options: list[AccommodationStay] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _val_gen_date(cls, v: Any) -> date:
        return parse_date_only(v)

    @model_validator(mode="after")
    def _val_gen_dates(self) -> "GenerateItineraryRequest":
        if self.end_date < self.start_date:
            raise ValueError(f"end_date {self.end_date.isoformat()} cannot be before start_date {self.start_date.isoformat()}")
        return self


class ReplanItineraryRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    target_day: Optional[int] = Field(default=None, ge=1, le=365)
    remove_activity_id: Optional[str] = Field(default=None, max_length=64)
    move_activity_id: Optional[str] = Field(default=None, max_length=64)
    to_day: Optional[int] = Field(default=None, ge=1, le=365)
    preference_update: Optional[str] = Field(default=None, max_length=500)

    model_config = {"extra": "forbid"}


class SelectAlternativeOptionRequest(BaseModel):
    option_id: str = Field(min_length=1, max_length=64)

    model_config = {"extra": "forbid"}


class ItineraryAlternativeOption(BaseModel):
    option_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    total_cost: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    plan: TripPlan

    model_config = {"extra": "forbid"}


class ItineraryValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    itinerary: Optional[TripPlan] = None

    model_config = {"extra": "forbid"}


class GenerateItineraryResponse(BaseModel):
    active_plan: TripPlan
    alternatives: list[ItineraryAlternativeOption] = Field(default_factory=list)
    execution_steps: list[str] = Field(default_factory=list)
    validation: ItineraryValidationResult
    explanation: Optional[str] = Field(default=None, max_length=2000)

    model_config = {"extra": "forbid"}

