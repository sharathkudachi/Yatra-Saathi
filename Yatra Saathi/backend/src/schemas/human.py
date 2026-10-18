"""Pydantic request models for the human API (`/api/v1/...`)."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.dates import date_order_error, parse_date_only


class DemoLoginRequest(BaseModel):
    user_id: str


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=30)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    identifier: Optional[str] = Field(default=None, max_length=320)
    password: Optional[str] = Field(default=None, max_length=128)
    user_id: Optional[str] = Field(default=None, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def validate_payload(self) -> "LoginRequest":
        if self.identifier and self.password:
            return self
        if self.user_id and self.display_name and self.email:
            return self
        if self.password is not None or self.identifier is not None:
            if not self.identifier or not self.password:
                raise ValueError("Both identifier and password are required")
            return self
        raise ValueError("Either (identifier, password) or (user_id, display_name, email) must be provided")


# Same shape `core.money.parse_amount` accepts: non-negative, at most 2 decimals, no separators.
MONEY_PATTERN = r"^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$"


class CreateSessionRequest(BaseModel):
    trip_id: Optional[str] = None
    goal_text: str = Field(min_length=1, max_length=4000)
    goal_language: str = Field(default="en-IN", min_length=2, max_length=35)
    constraints: dict = Field(default_factory=dict)
    spend_cap: str = Field(pattern=MONEY_PATTERN)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("constraints")
    @classmethod
    def _trip_dates(cls, value: dict) -> dict:
        # The trip brief's dates: start = outbound flight / hotel check-in, end = return flight /
        # hotel check-out. Date-only strings, and the end after the start. (Not-in-the-past needs
        # the clock, so the route checks that.)
        parsed = {}
        for key in ("start_date", "end_date"):
            if value.get(key) not in (None, ""):
                parsed[key] = parse_date_only(value[key])
        error = date_order_error(parsed.get("start_date"), parsed.get("end_date"),
                                 start_label="start_date", end_label="end_date")
        if error:
            raise ValueError(error)
        return value


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ApproveConfirmationRequest(BaseModel):
    snapshot_hash: str


class DeclineConfirmationRequest(BaseModel):
    note: Optional[str] = None


def _blank_to_none(value):
    return None if isinstance(value, str) and not value.strip() else value


def _check_date_order(model):
    # Hotel stay: check-out must come after check-in, so the stay is at least one night.
    error = date_order_error(model.startDate, model.endDate, start_label="check-in date",
                             end_label="check-out date")
    if error:
        raise ValueError(error)
    return model


def _date_only(value):
    # Stay/flight dates are calendar days: a datetime string would be shifted by its offset.
    return parse_date_only(value) if value is not None else None


def _blank_or_date_only(value):
    return _date_only(_blank_to_none(value))


# Search requests use the frontend's camelCase field names; unknown fields
# (goalLanguage, preferences) are ignored.
class FlightSearchRequest(BaseModel):
    originCity: str = Field(min_length=1, max_length=200)
    destinationCity: str = Field(min_length=1, max_length=200)
    departureDate: date
    passengers: int = Field(ge=1, le=9)
    cabinClass: Literal["economy", "business", "first"] = "economy"
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")

    _blank = field_validator("currency", mode="before")(_blank_to_none)
    _day = field_validator("departureDate", mode="before")(_date_only)


class HotelSearchRequest(BaseModel):
    destination: str = Field(default="", max_length=200)
    startDate: Optional[date] = None
    endDate: Optional[date] = None
    travellers: int = Field(default=1, ge=1, le=20)
    budget: Optional[str] = Field(default=None, pattern=MONEY_PATTERN)
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")

    _blank = field_validator("budget", "currency", mode="before")(_blank_to_none)
    _day = field_validator("startDate", "endDate", mode="before")(_blank_or_date_only)
    _order = model_validator(mode="after")(_check_date_order)


class HotelRoomsRequest(BaseModel):
    startDate: date
    endDate: date
    travellers: int = Field(default=1, ge=1, le=20)
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")

    _blank = field_validator("currency", mode="before")(_blank_to_none)
    _day = field_validator("startDate", "endDate", mode="before")(_date_only)
    _order = model_validator(mode="after")(_check_date_order)
