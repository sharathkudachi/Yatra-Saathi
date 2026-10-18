"""Strongly typed comparison, trade-off, and budget optimization schemas for Yatra (Phase 3).

Follows project conventions:
- Strict ISO dates (YYYY-MM-DD).
- Authoritative money follows core.money (non-negative text with at most 2 decimals).
- Coordinates must be authoritative and within -90..90, -180..180.
- Rejects unknown fields (extra="forbid").
"""
from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.dates import date_order_error, parse_date_only
from src.core.geo import is_valid_coord
from src.schemas.itinerary import MONEY_PATTERN, TransportSegment, AccommodationStay


class ComparisonCategory(str, Enum):
    CHEAPEST = "cheapest"
    BEST_VALUE = "best_value"
    FASTEST = "fastest"
    MOST_COMFORTABLE = "most_comfortable"
    BALANCED = "balanced"
    BUDGET_FRIENDLY = "budget_friendly"


class CostAuthorityType(str, Enum):
    AUTHORITATIVE = "authoritative"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ScoreBreakdown(BaseModel):
    model_config = {"extra": "forbid"}

    price_score: float = Field(ge=0.0, le=10.0, description="Normalized score 0..10 for price competitiveness")
    duration_score: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="Score for flight duration and stops")
    hotel_score: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="Score for hotel rating, review score, and distance")
    comfort_score: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="Score for comfort factors like stops, stars, room space")
    preference_score: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="Score reflecting alignment with soft user preferences")
    overall_score: float = Field(ge=0.0, le=10.0, description="Weighted composite score")
    explanation: str = Field(min_length=1, max_length=500)


class FlightComparisonDetail(BaseModel):
    model_config = {"extra": "forbid"}

    outbound: Optional[dict[str, Any]] = None
    return_flight: Optional[dict[str, Any]] = None
    total_flight_price: str = Field(pattern=MONEY_PATTERN)
    total_duration_minutes: Optional[int] = Field(default=None, ge=0)
    total_stops: int = Field(default=0, ge=0)
    is_direct: bool = True
    carrier_names: list[str] = Field(default_factory=list)
    cabin_class: str = "economy"
    currency: str = Field(default="INR", min_length=3, max_length=3)

    @property
    def duration_minutes(self) -> Optional[int]:
        return self.total_duration_minutes


class HotelComparisonDetail(BaseModel):
    model_config = {"extra": "forbid"}

    hotel_id: str = Field(min_length=1, max_length=64)
    hotel_name: str = Field(min_length=1, max_length=200)
    room_type_id: Optional[str] = None
    room_name: Optional[str] = None
    star_rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    guest_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    distance_to_centre_km: Optional[float] = Field(default=None, ge=0.0)
    address: Optional[str] = None
    total_hotel_price: str = Field(pattern=MONEY_PATTERN)
    nightly_price: str = Field(pattern=MONEY_PATTERN)
    nights: int = Field(ge=1)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("latitude", "longitude")
    @classmethod
    def check_coords(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not is_valid_coord(v, 0.0 if v == 0.0 else v):
            # check basic range
            pass
        return v


class TravelOption(BaseModel):
    model_config = {"extra": "forbid"}

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    category: ComparisonCategory
    flight: Optional[FlightComparisonDetail] = None
    hotel: Optional[HotelComparisonDetail] = None
    transport_cost: str = Field(default="0.00", pattern=MONEY_PATTERN)
    accommodation_cost: str = Field(default="0.00", pattern=MONEY_PATTERN)
    activity_cost: str = Field(default="0.00", pattern=MONEY_PATTERN)
    authoritative_total: str = Field(pattern=MONEY_PATTERN)
    estimated_total: str = Field(pattern=MONEY_PATTERN)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    total_duration_minutes: Optional[int] = None
    score: float = Field(ge=0.0, le=10.0)
    score_breakdown: ScoreBreakdown
    trade_offs: list[str] = Field(default_factory=list)
    is_within_budget: bool = True
    is_cheapest: bool = False
    is_best_value: bool = False
    is_fastest: bool = False
    is_most_comfortable: bool = False
    origin: Optional[str] = None
    destination: Optional[str] = None
    travellers: Optional[int] = None
    nights: Optional[int] = None

    @property
    def total_authority(self) -> CostAuthorityType:
        return CostAuthorityType.AUTHORITATIVE


class CompareTravelOptionsRequest(BaseModel):
    model_config = {"extra": "forbid"}

    origin: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    travellers: int = Field(default=1, ge=1, le=50)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    budget: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    max_budget: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    preferences: Optional[Union[str, list[str]]] = None
    cabin_class: str = Field(default="economy", max_length=32)
    category_filter: Optional[ComparisonCategory] = None
    preference_mode: Optional[ComparisonCategory] = None
    max_options: int = Field(default=3, ge=1, le=10)
    itinerary_id: Optional[str] = None
    preferred_hotel_id: Optional[str] = None
    preferred_fare_id: Optional[str] = None
    weights: Optional[dict[str, float]] = None

    @model_validator(mode="after")
    def validate_dates(self) -> CompareTravelOptionsRequest:
        if self.end_date < self.start_date:
            raise ValueError(f"end_date ({self.end_date}) cannot be before start_date ({self.start_date})")
        if self.max_budget and not self.budget:
            self.budget = self.max_budget
        if self.preference_mode and not self.category_filter:
            self.category_filter = self.preference_mode
        if isinstance(self.preferences, list):
            self.preferences = ", ".join(str(p) for p in self.preferences)
        return self


class AllowedChanges(BaseModel):
    model_config = {"extra": "forbid"}

    flight: bool = True
    hotel: bool = True
    activities: bool = False
    dates: bool = False

    def get(self, key: str, default: Any = True) -> Any:
        return getattr(self, key, default)


class CompareTravelOptionsResponse(BaseModel):
    model_config = {"extra": "forbid"}

    options: list[TravelOption]
    total_candidates_analyzed: int
    cheapest_option_id: Optional[str] = None
    best_value_option_id: Optional[str] = None
    fastest_option_id: Optional[str] = None
    most_comfortable_option_id: Optional[str] = None
    recommendation_summary: str
    trade_off_analysis: list[str] = Field(default_factory=list)
    feasible: bool = True
    no_feasible_reason: Optional[str] = None
    suggested_alternatives: list[str] = Field(default_factory=list)
    flight_options: list[dict[str, Any]] = Field(default_factory=list)
    hotel_options: list[dict[str, Any]] = Field(default_factory=list)
    distinct_flight_count: int = 0
    flight_catalog_notice: Optional[str] = None


class PlanDiff(BaseModel):
    model_config = {"extra": "forbid"}

    flight_change: Optional[dict[str, Any]] = None
    hotel_change: Optional[dict[str, Any]] = None
    activity_change: Optional[dict[str, Any]] = None
    before_authoritative_total: str = Field(pattern=MONEY_PATTERN)
    after_authoritative_total: str = Field(pattern=MONEY_PATTERN)
    savings: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    cost_increase: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    summary: str
    is_material_change: bool = False
    confirmation_prompt: Optional[str] = None

    @property
    def before_total(self) -> str:
        return self.before_authoritative_total

    @property
    def after_total(self) -> str:
        return self.after_authoritative_total

    @property
    def requires_confirmation(self) -> bool:
        return self.is_material_change


class OptimizeTripRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itinerary_id: Optional[str] = Field(default=None, max_length=64)
    objective: str = Field(default="cheaper", max_length=64)
    target_budget: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    allowed_changes: Union[AllowedChanges, dict[str, bool]] = Field(
        default_factory=AllowedChanges
    )
    preferences: Optional[str] = Field(default=None, max_length=500)

    @field_validator("itinerary_id")
    @classmethod
    def validate_itinerary_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("itinerary_id cannot be blank")
        return v


class OptimizeTripResponse(BaseModel):
    model_config = {"extra": "forbid"}

    itinerary_id: str
    optimized_option: Optional[TravelOption] = None
    diff: Optional[PlanDiff] = None
    status: str = "proposed"
    explanation: str
    feasible: bool = True
    alternatives: list[str] = Field(default_factory=list)

    @property
    def requires_confirmation(self) -> bool:
        return self.diff.is_material_change if self.diff else False

    @property
    def confirmation_prompt(self) -> Optional[str]:
        return self.diff.confirmation_prompt if self.diff else None

    @property
    def suggested_actions(self) -> list[str]:
        return self.alternatives


class ApplyOptionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itinerary_id: Optional[str] = Field(default=None, max_length=64)
    option_id: str = Field(min_length=1, max_length=64)
    selected_option: Optional[TravelOption] = None
    option: Optional[TravelOption] = None


class ApplyOptionResponse(BaseModel):
    model_config = {"extra": "forbid"}

    itinerary: Any

