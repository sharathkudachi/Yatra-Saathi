"""Human Phase 6 notification center & preferences routes (/api/v1/notifications)."""
from __future__ import annotations

import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query

from src.api.deps import CurrentUser, get_conn, get_current_user
from src.contracts.envelope import ok
from src.schemas.notifications import (
    TriggerNotificationEventRequest,
    UpdateNotificationPreferencesRequest,
)
from src.services.phase6_notification_service import Phase6NotificationService

router = APIRouter()


@router.get("/notifications")
def list_notifications_endpoint(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """List in-app notifications for the authenticated user."""
    service = Phase6NotificationService(conn)
    res = service.list_notifications(user.user_id, limit=limit, unread_only=unread_only)
    return ok(res.dict())


@router.get("/notifications/unread-count")
def get_unread_count_endpoint(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Get the unread notification count for the authenticated user."""
    service = Phase6NotificationService(conn)
    count = service.repo.count_unread_notifications(user.user_id)
    return ok({"unread_count": count})


@router.post("/notifications/{notification_id}/read")
def mark_notification_read_endpoint(
    notification_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Mark a specific notification as read, enforcing user ownership."""
    service = Phase6NotificationService(conn)
    success = service.mark_notification_read(user.user_id, notification_id)
    return ok({"notification_id": notification_id, "is_read": True})


@router.post("/notifications/read-all")
def mark_all_read_endpoint(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Mark all notifications for the authenticated user as read."""
    service = Phase6NotificationService(conn)
    count = service.mark_all_read(user.user_id)
    return ok({"marked_count": count})


@router.get("/notification-preferences")
def get_notification_preferences_endpoint(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Retrieve notification preferences for the authenticated user."""
    service = Phase6NotificationService(conn)
    res = service.get_preferences(user.user_id)
    return ok(res.dict())


@router.put("/notification-preferences")
def update_notification_preferences_endpoint(
    body: UpdateNotificationPreferencesRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Update notification preferences for the authenticated user."""
    service = Phase6NotificationService(conn)
    res = service.update_preferences(user.user_id, body)
    return ok(res.dict())


@router.post("/notifications/trigger-event")
def trigger_notification_event_endpoint(
    body: TriggerNotificationEventRequest,
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Trigger an authoritative backend lifecycle event."""
    service = Phase6NotificationService(conn)
    # Target either request user_id or body user_id if matching
    target_user = user.user_id
    created = service.trigger_event(
        user_id=target_user,
        event_type=body.event_type,
        entity_id=body.entity_id,
        trip_id=body.trip_id,
        booking_id=body.booking_id,
        language=body.language,
        extra_context=body.extra_context,
    )
    return ok({"created": created is not None, "notification": created})
