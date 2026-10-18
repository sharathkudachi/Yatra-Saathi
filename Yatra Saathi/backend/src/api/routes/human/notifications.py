"""Web Push notifications for the signed-in user.

GET    /api/v1/notifications/public-key       VAPID key the browser subscribes with (public)
POST   /api/v1/notifications/subscriptions    save this device's push subscription + preferences
DELETE /api/v1/notifications/subscriptions    forget this device
GET    /api/v1/notifications                  recent notifications (in-app history)
POST   /api/v1/notifications/test             send a test; kind="flight_landed" previews the landing
                                              notification for the user's latest booked trip
"""
from __future__ import annotations

import secrets
import sqlite3
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user, get_settings
from src.contracts.envelope import ok
from src.core.clock import Clock
from src.core.config import Settings
from src.services import notify_service

router = APIRouter()


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=500)
    auth: str = Field(min_length=1, max_length=200)


class Subscription(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: SubscriptionKeys


class SubscribeRequest(BaseModel):
    subscription: Subscription
    prefs: dict = Field(default_factory=dict)


class TestRequest(BaseModel):
    kind: Literal["test", "flight_landed"] = "test"


@router.get("/notifications/public-key")
def public_key(settings: Settings = Depends(get_settings)):
    return ok({"publicKey": settings.vapid_public_key, "enabled": bool(settings.vapid_public_key and settings.vapid_private_key)})


@router.post("/notifications/subscriptions")
def subscribe(body: SubscribeRequest, user: CurrentUser = Depends(get_current_user), clock: Clock = Depends(get_clock),
              conn: sqlite3.Connection = Depends(get_conn)):
    prefs = {k: bool(v) for k, v in body.prefs.items() if isinstance(v, bool)}
    subscription_id = notify_service.subscribe(conn, clock, user_id=user.user_id, endpoint=body.subscription.endpoint,
                                               p256dh=body.subscription.keys.p256dh, auth=body.subscription.keys.auth,
                                               prefs=prefs)
    return ok({"subscription_id": subscription_id})


@router.delete("/notifications/subscriptions")
def unsubscribe(endpoint: str = Body(..., embed=True), user: CurrentUser = Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_conn)):
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?", (endpoint, user.user_id))
    return ok({"removed": True})


@router.get("/notifications")
def history(user: CurrentUser = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_conn)):
    return ok({"notifications": notify_service.recent(conn, user.user_id)})


@router.post("/notifications/test")
def test(body: Optional[TestRequest] = None, user: CurrentUser = Depends(get_current_user),
         settings: Settings = Depends(get_settings), clock: Clock = Depends(get_clock),
         conn: sqlite3.Connection = Depends(get_conn)):
    kind = (body or TestRequest()).kind
    title, text = "Notifications are on ✓", "Yatra Saathi will tell you when your plan is ready, when you book, and when you land."
    if kind == "flight_landed":
        # Preview of the real landing notification, using the latest booked trip's first flight.
        row = conn.execute(
            """SELECT c.cart_id, ci.cart_item_id FROM agent_carts c JOIN agent_sessions s ON s.session_id = c.session_id
               JOIN agent_cart_items ci ON ci.cart_id = c.cart_id AND ci.kind = 'flight' AND ci.status = 'active'
               WHERE s.user_id = ? AND c.status = 'booked' ORDER BY c.updated_at DESC, ci.for_date LIMIT 1""",
            (user.user_id,)).fetchone()
        if row:
            title, text = notify_service.landing_message(conn, row["cart_id"], row["cart_item_id"])
            title = f"(Preview) {title}"
    notify_service.notify(conn, clock, settings, user_id=user.user_id, kind="test",
                          dedupe_key=f"test:{secrets.token_hex(6)}", title=title, body=text, url="/#my-trips")
    return ok({"sent": True, "title": title, "body": text, "pushEnabled": bool(settings.vapid_private_key)})
