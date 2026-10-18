"""Pydantic schemas for Phase 6 Notifications and Event Alerts."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from .multilingual import SupportedLanguageCode

NotificationEventType = Literal[
    "TRIP_UPCOMING",
    "TRIP_STARTING",
    "BOOKING_CONFIRMED",
    "BOOKING_CANCELLED",
    "HOLD_EXPIRING",
    "HOLD_EXPIRED",
    "TRIP_PACK_READY",
    "ITINERARY_UPDATED",
    "TRAVEL_DAY_REMINDER",
]

ALL_NOTIFICATION_CATEGORIES = [
    "TRIP_UPCOMING",
    "TRIP_STARTING",
    "BOOKING_CONFIRMED",
    "BOOKING_CANCELLED",
    "HOLD_EXPIRING",
    "HOLD_EXPIRED",
    "TRIP_PACK_READY",
    "ITINERARY_UPDATED",
    "TRAVEL_DAY_REMINDER",
]


class NotificationItem(BaseModel):
    notification_id: str
    user_id: str
    event_type: NotificationEventType
    title: str
    body: str
    language: SupportedLanguageCode
    is_read: bool
    read_at: Optional[str] = None
    trip_id: Optional[str] = None
    booking_id: Optional[str] = None
    dedupe_key: str
    created_at: str


class NotificationListResponse(BaseModel):
    user_id: str
    total_count: int
    unread_count: int
    notifications: List[NotificationItem]


class MarkReadResponse(BaseModel):
    marked_count: int
    notification_ids: List[str]


class QuietHoursConfig(BaseModel):
    enabled: bool = False
    start: str = "22:00"
    end: str = "08:00"


class NotificationPreferencesResponse(BaseModel):
    user_id: str
    enabled: bool
    preferred_language: SupportedLanguageCode
    categories: List[NotificationEventType]
    in_app_enabled: bool
    browser_enabled: bool
    quiet_hours: QuietHoursConfig
    updated_at: str


class UpdateNotificationPreferencesRequest(BaseModel):
    enabled: Optional[bool] = None
    preferred_language: Optional[SupportedLanguageCode] = None
    categories: Optional[List[NotificationEventType]] = None
    in_app_enabled: Optional[bool] = None
    browser_enabled: Optional[bool] = None
    quiet_hours: Optional[QuietHoursConfig] = None


class TriggerNotificationEventRequest(BaseModel):
    event_type: NotificationEventType
    user_id: str
    entity_id: str  # trip_id, booking_id, or hold_id
    trip_id: Optional[str] = None
    booking_id: Optional[str] = None
    language: Optional[SupportedLanguageCode] = None
    extra_context: Dict[str, Any] = Field(default_factory=dict)
