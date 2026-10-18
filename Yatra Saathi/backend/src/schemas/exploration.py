"""Strongly typed destination and hotel exploration schemas for Yatra (Phase 4).

Follows project conventions:
- Strict Pydantic models with extra="forbid".
- ISO dates and integer minor unit money (no floating-point money).
- Authoritative coordinates validated within range (-90..90, -180..180).
- Pure backend grounding: no hallucinated POIs, hotels, coordinates, or amenities.
"""
from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.geo import is_valid_coord
from src.schemas.itinerary import MONEY_PATTERN
from src.schemas.preferences import PreferenceMatch


class POIExploreItem(BaseModel):
    model_config = {"extra": "forbid"}

    poi_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    city_id: str = Field(min_length=1, max_length=64)
    city_name: str = Field(min_length=1, max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    category: str = Field(min_length=1, max_length=64)
    cost: str = Field(pattern=MONEY_PATTERN)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    duration_minutes: Optional[int] = Field(default=None, ge=0)
    times_planned: int = Field(default=0, ge=0)
    description: Optional[str] = None
    preference_matches: List[PreferenceMatch] = Field(default_factory=list)

    @field_validator("latitude", "longitude")
    @classmethod
    def check_coords(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not is_valid_coord(v, 0.0 if v == 0.0 else v):
            raise ValueError(f"Coordinate {v} out of bounds")
        return v


class DestinationExploreRequest(BaseModel):
    model_config = {"extra": "forbid"}

    destination: str = Field(min_length=1, max_length=100)
    category_filter: Optional[str] = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    limit: int = Field(default=20, ge=1, le=100)


class DestinationExploreResponse(BaseModel):
    model_config = {"extra": "forbid"}

    destination: str
    city_id: str
    city_name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    activities: List[POIExploreItem]
    supported_categories: List[str]
    total_activities: int


class HotelExploreItem(BaseModel):
    model_config = {"extra": "forbid"}

    hotel_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    city_id: str = Field(min_length=1, max_length=64)
    city_name: str = Field(min_length=1, max_length=100)
    property_type: Optional[str] = None
    star_rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    guest_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    review_count: Optional[int] = Field(default=None, ge=0)
    address_line: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_to_centre_km: Optional[float] = Field(default=None, ge=0.0)
    room_type_id: str = Field(min_length=1, max_length=64)
    room_name: str = Field(min_length=1, max_length=200)
    nightly_price: str = Field(pattern=MONEY_PATTERN)
    total_stay_price: str = Field(pattern=MONEY_PATTERN)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    preference_matches: List[PreferenceMatch] = Field(default_factory=list)
    match_score: float = Field(default=0.0, ge=0.0, le=10.0)
    why_it_matches: List[str] = Field(default_factory=list)

    @field_validator("latitude", "longitude")
    @classmethod
    def check_coords(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not is_valid_coord(v, 0.0 if v == 0.0 else v):
            raise ValueError(f"Coordinate {v} out of bounds")
        return v


class HotelExploreRequest(BaseModel):
    model_config = {"extra": "forbid"}

    destination: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    travellers: int = Field(default=1, ge=1, le=20)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    min_stars: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    min_guest_score: Optional[float] = Field(default=None, ge=1.0, le=10.0)
    max_nightly_price: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    sort_by: str = Field(default="match", max_length=32)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_dates(self) -> HotelExploreRequest:
        if self.end_date < self.start_date:
            raise ValueError(f"end_date ({self.end_date}) cannot be before start_date ({self.start_date})")
        return self


class HotelExploreResponse(BaseModel):
    model_config = {"extra": "forbid"}

    destination: str
    hotels: List[HotelExploreItem]
    total_found: int


class AddActivityRequest(BaseModel):
    model_config = {"extra": "forbid"}

    poi_id: str = Field(min_length=1, max_length=64)
    day_number: int = Field(ge=1, le=30)
    slot_time: Optional[str] = Field(default=None, max_length=10)


class SelectHotelRequest(BaseModel):
    model_config = {"extra": "forbid"}

    hotel_id: str = Field(min_length=1, max_length=64)
    room_type_id: str = Field(min_length=1, max_length=64)
