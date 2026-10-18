"""Pydantic schemas for Phase 6 Emergency Assistance & SOS."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

EmergencyEventType = Literal[
    "EMERGENCY_ASSISTANCE_OPENED",
    "SOS_ACTIVATED",
    "EMERGENCY_CONTACT_SELECTED",
    "TRIP_DETAILS_SHARE_REQUESTED",
]


class LocationCoordinates(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy_meters: Optional[float] = None
    captured_at: Optional[str] = None
    address_or_landmark: Optional[str] = None
    source: Optional[str] = "gps"
    display_label: Optional[str] = None
    place_id: Optional[str] = None


class GeocodePlaceResult(BaseModel):
    place_id: str
    display_name: str
    name: str
    locality: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "India"
    latitude: float
    longitude: float
    bounding_box: Optional[List[float]] = None


class GeocodeSearchResponse(BaseModel):
    query: str
    results: List[GeocodePlaceResult] = Field(default_factory=list)
    attribution: str = "Data © OpenStreetMap contributors, ODbL 1.0"
    provider: str = "nominatim"
    rate_limited: bool = False


class OfficialEmergencyContact(BaseModel):
    service_name: str
    number: str
    description: str
    is_toll_free: bool = True
    name: Optional[str] = None

    @model_validator(mode="after")
    def populate_name(self) -> OfficialEmergencyContact:
        if not self.name:
            self.name = self.service_name
        return self


class UserTrustedContact(BaseModel):
    contact_id: str
    user_id: str
    name: str
    relationship: str
    phone_number: str
    is_primary: bool
    created_at: str
    updated_at: str
    contact_name: Optional[str] = None

    @model_validator(mode="after")
    def populate_contact_name(self) -> UserTrustedContact:
        if not self.contact_name:
            self.contact_name = self.name
        return self


class CreateTrustedContactRequest(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    relationship: str = Field(..., min_length=2, max_length=50)
    phone_number: str = Field(..., min_length=5, max_length=30)
    is_primary: bool = True

    @model_validator(mode="before")
    @classmethod
    def check_names_and_phone(cls, data: Any) -> Any:
        if isinstance(data, dict):
            n = data.get("name") or data.get("contact_name")
            if not n or len(str(n).strip()) < 2:
                raise ValueError("Contact name must be at least 2 characters")
            data["name"] = str(n).strip()
            data["contact_name"] = str(n).strip()

            p = data.get("phone_number")
            if p:
                cleaned_p = re.sub(r"[\s\-\(\)\+]", "", str(p))
                if len(cleaned_p) < 5 or not cleaned_p.isdigit():
                    raise ValueError("Phone number must contain at least 5 digits")
        return data


class UpdateTrustedContactRequest(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    relationship: Optional[str] = None
    phone_number: Optional[str] = None
    is_primary: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def check_update_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            n = data.get("name") or data.get("contact_name")
            if n is not None:
                if len(str(n).strip()) < 2:
                    raise ValueError("Contact name must be at least 2 characters")
                data["name"] = str(n).strip()
                data["contact_name"] = str(n).strip()

            p = data.get("phone_number")
            if p is not None:
                cleaned_p = re.sub(r"[\s\-\(\)\+]", "", str(p))
                if len(cleaned_p) < 5 or not cleaned_p.isdigit():
                    raise ValueError("Phone number must contain at least 5 digits")

            r = data.get("relationship")
            if r is not None and len(str(r).strip()) < 2:
                raise ValueError("Relationship must be at least 2 characters")
        return data


class EmergencyTripContext(BaseModel):
    trip_id: str
    title: str
    destination_city: str
    destination: Optional[str] = None
    start_date: str
    end_date: str
    booking_reference: Optional[str] = None
    hotel_name: Optional[str] = None
    status: str
    traveller_count: int = 1

    @model_validator(mode="after")
    def populate_destination(self) -> EmergencyTripContext:
        if not self.destination:
            self.destination = self.destination_city
        return self


class EmergencyInfoResponse(BaseModel):
    safety_notice: str = "If you are in immediate danger, contact local emergency services immediately (Dial 112)."
    disclaimer: str = "If you are in immediate danger, contact local emergency services immediately (Dial 112)."
    primary_emergency_number: str = "112"
    official_services: List[OfficialEmergencyContact]
    official_numbers: List[OfficialEmergencyContact] = Field(default_factory=list)
    trusted_contacts: List[UserTrustedContact]
    user_contacts: List[UserTrustedContact] = Field(default_factory=list)
    current_trip_context: Optional[EmergencyTripContext] = None
    trip_context: Optional[EmergencyTripContext] = None
    location_tracking_status: str = "Location tracking is disabled. Location is never collected without explicit consent."

    @model_validator(mode="after")
    def populate_aliases(self) -> EmergencyInfoResponse:
        if not self.official_numbers:
            self.official_numbers = self.official_services
        if not self.user_contacts:
            self.user_contacts = self.trusted_contacts
        if not self.trip_context:
            self.trip_context = self.current_trip_context
        if not self.disclaimer:
            self.disclaimer = self.safety_notice
        return self


class ActivateSosRequest(BaseModel):
    explicit_confirmation: bool = Field(..., description="Must be True to activate SOS")
    reason: Optional[str] = None
    trip_id: Optional[str] = None
    booking_id: Optional[str] = None
    location: Optional[LocationCoordinates] = None
    location_text: Optional[str] = None
    location_source: Optional[str] = None
    notes: Optional[str] = None


class ActivateSosResponse(BaseModel):
    sos_event_id: str
    event_id: Optional[str] = None
    status: str = "ACTIVATED"
    emergency_notice: str
    disclaimer: str = "Yatra Saathi assistance is a companion tool and does not replace official emergency dispatch (Dial 112)."
    official_number_to_dial: str = "112"
    trusted_contacts_notified_mode: str = "DEMO_SIMULATION"
    instructions: List[str] = Field(default_factory=list)
    delivery_provider_status: Dict[str, Any] = Field(default_factory=dict)
    location_captured: Optional[Dict[str, Any]] = None
    location_source: Optional[str] = None
    location_display: Optional[str] = None
    timestamp: str

    @model_validator(mode="after")
    def populate_event_id(self) -> ActivateSosResponse:
        if not self.event_id:
            self.event_id = self.sos_event_id
        return self


class ShareTripRequest(BaseModel):
    trip_id: str
    trusted_contact_id: Optional[str] = None
    explicit_user_confirmation: Optional[bool] = None
    explicit_share_consent: Optional[bool] = None
    location: Optional[LocationCoordinates] = None
    location_text: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def validate_confirmation(cls, data: Any) -> Any:
        if isinstance(data, dict):
            conf = data.get("explicit_user_confirmation") or data.get("explicit_share_consent")
            if not conf:
                raise ValueError("Explicit user confirmation is required to share trip details")
            data["explicit_user_confirmation"] = True
            data["explicit_share_consent"] = True
        return data


class ShareTripSummary(BaseModel):
    destination: str
    hotel: Optional[str] = None
    booking_reference: Optional[str] = None
    trip_dates: str
    share_preview_text: str
    location_summary: Optional[str] = None


class ShareTripResponse(BaseModel):
    share_event_id: str
    trip_id: str
    status: str = "SHARED_TO_TRUSTED_CONTACT"
    summary: ShareTripSummary
    timestamp: str
