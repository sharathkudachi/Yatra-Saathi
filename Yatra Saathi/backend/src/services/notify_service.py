"""Notifications: recorded once per event (in-app history) and pushed to the user's devices.

Kinds and the preference (set per device in the bell panel) that controls pushing them:
  plan_ready, approval_ready -> tripUpdates      booking_confirmed -> bookingUpdates
  flight_departing, flight_landed -> itineraryReminders           test -> always

`notify` never raises into the caller: a notification must not break planning or booking.
Pushing happens on a background thread with its own connection, so requests stay fast.
Without VAPID keys the notification is still recorded and shown in-app, just not pushed.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Optional

from src.core.clock import Clock
from src.core.config import Settings
from src.core.ids import new_id

logger = logging.getLogger("tech4ce.notify")

PREF_FOR_KIND = {"plan_ready": "tripUpdates", "approval_ready": "tripUpdates", "booking_confirmed": "bookingUpdates",
                 "flight_departing": "itineraryReminders", "flight_landed": "itineraryReminders"}


def notify(conn: sqlite3.Connection, clock: Clock, settings: Settings, *, user_id: str, kind: str,
           dedupe_key: str, title: str, body: str, url: str = "/", session_id: Optional[str] = None) -> bool:
    """Record the notification (once per dedupe_key) and push it. Returns False if already sent."""
    try:
        notification_id = new_id("ntf")
        cur = conn.execute(
            """INSERT OR IGNORE INTO notifications_sent
                 (notification_id, user_id, session_id, kind, dedupe_key, title, body, url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (notification_id, user_id, session_id, kind, dedupe_key, title, body, url, clock.utc()))
        if cur.rowcount == 0:
            return False
    except sqlite3.Error:
        logger.exception("could not record notification %s", dedupe_key)
        return False
    if settings.vapid_private_key and settings.vapid_public_key:
        threading.Thread(target=_push, args=(settings, notification_id, user_id, kind, title, body, url),
                         daemon=True).start()
    return True


def _push(settings: Settings, notification_id: str, user_id: str, kind: str, title: str, body: str, url: str) -> None:
    from pywebpush import WebPushException, webpush
    from src.db.connection import connect

    conn = connect(settings, check_same_thread=False)
    try:
        subs = conn.execute("SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)).fetchall()
        payload = json.dumps({"title": title, "body": body, "url": url, "tag": kind})
        delivered = 0
        for sub in subs:
            prefs = json.loads(sub["prefs_json"] or "{}")
            pref = PREF_FOR_KIND.get(kind)
            if pref and prefs.get(pref) is False:
                continue
            try:
                webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                        data=payload, vapid_private_key=settings.vapid_private_key,
                        vapid_claims={"sub": settings.vapid_subject}, ttl=24 * 3600)
                delivered += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):  # the browser unsubscribed: forget that device
                    conn.execute("DELETE FROM push_subscriptions WHERE subscription_id = ?", (sub["subscription_id"],))
                else:
                    logger.warning("push to %s failed: %s", sub["endpoint"][:40], exc)
            except Exception:
                logger.exception("push failed")
        conn.execute("UPDATE notifications_sent SET delivered_count = ? WHERE notification_id = ?", (delivered, notification_id))
    finally:
        conn.close()


def subscribe(conn, clock: Clock, *, user_id: str, endpoint: str, p256dh: str, auth: str, prefs: dict) -> str:
    """Add or refresh this device's subscription (an endpoint belongs to one user at a time)."""
    now = clock.utc()
    existing = conn.execute("SELECT subscription_id FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()
    if existing:
        conn.execute("""UPDATE push_subscriptions SET user_id = ?, p256dh = ?, auth = ?, prefs_json = ?, updated_at = ?
                        WHERE subscription_id = ?""", (user_id, p256dh, auth, json.dumps(prefs), now, existing[0]))
        return existing[0]
    subscription_id = new_id("psb")
    conn.execute("""INSERT INTO push_subscriptions (subscription_id, user_id, endpoint, p256dh, auth, prefs_json,
                    created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                 (subscription_id, user_id, endpoint, p256dh, auth, json.dumps(prefs), now, now))
    return subscription_id


def recent(conn, user_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute("""SELECT notification_id, kind, title, body, url, session_id, created_at FROM notifications_sent
                           WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""", (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def trip_name(conn, session_id: str) -> str:
    """The destination as the user would say it, for notification text."""
    row = conn.execute("""SELECT s.constraints_json, st.state_json FROM agent_sessions s
                          LEFT JOIN agent_session_state st ON st.session_id = s.session_id WHERE s.session_id = ?""",
                       (session_id,)).fetchone()
    if not row:
        return ""
    remembered = (json.loads(row["state_json"]).get("requirements") or {}) if row["state_json"] else {}
    constraints = json.loads(row["constraints_json"] or "{}")
    return remembered.get("destination_name") or constraints.get("destination_name") or ""


def money_text(amount: str, currency: str) -> str:
    whole, _, frac = f"{float(amount):.2f}".partition(".")
    return f"{currency} {int(whole):,}.{frac}"


def session_user(conn, session_id: str) -> Optional[str]:
    row = conn.execute("SELECT user_id FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return row[0] if row else None


def landing_message(conn, cart_id: str, flight_item_id: str) -> tuple[str, str]:
    """'You've landed in X' with the stay's check-in, for one booked flight."""
    flight = conn.execute(
        """SELECT cd.name AS city, ad.iata AS code, f.arrives_at FROM agent_cart_items ci
           JOIN flight_fares ff ON ff.fare_id = ci.entity_id JOIN flights f ON f.flight_id = ff.flight_id
           JOIN airports ad ON ad.airport_id = f.dest_airport_id JOIN cities cd ON cd.city_id = ad.city_id
           WHERE ci.cart_item_id = ?""", (flight_item_id,)).fetchone()
    stay = conn.execute(
        """SELECT h.name AS hotel, h.checkin_time, c.name AS city FROM agent_cart_items ci
           JOIN hotel_room_types r ON r.room_type_id = ci.entity_id JOIN hotels h ON h.hotel_id = r.hotel_id
           JOIN cities c ON c.city_id = h.city_id
           WHERE ci.cart_id = ? AND ci.kind = 'hotel_stay' AND ci.status = 'active' ORDER BY ci.for_date LIMIT 1""",
        (cart_id,)).fetchone()
    city = flight["city"] if flight else "your destination"
    title = f"Welcome to {city}! ✈"
    if stay and stay["city"] == city:
        body = f"Your flight has landed. Check in at {stay['hotel']} from {stay['checkin_time'] or 'the afternoon'}."
    else:
        body = "Your flight has landed. Have a wonderful trip!"
    return title, body
