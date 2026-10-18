"""SQLite Repository for Phase 6 Multilingual, Notifications, and Emergency Assistance."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.clock import now_iso
from src.core.ids import new_id


class Phase6Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -------------------------------------------------------------------------
    # 1. Language Preferences
    # -------------------------------------------------------------------------
    def get_user_language_preference(self, user_id: str) -> str:
        row = self.conn.execute(
            "SELECT preferred_language FROM user_language_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return row[0]
        # Check user profile locale default
        u_row = self.conn.execute(
            "SELECT locale FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if u_row and u_row[0] in ("hi", "hi-IN"):
            return "hi-IN"
        if u_row and u_row[0] in ("ta", "ta-IN"):
            return "ta-IN"
        return "en-IN"

    def set_user_language_preference(self, user_id: str, language_code: str) -> str:
        now = now_iso()
        self.conn.execute(
            """INSERT INTO user_language_preferences (user_id, preferred_language, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 preferred_language = excluded.preferred_language,
                 updated_at = excluded.updated_at""",
            (user_id, language_code, now),
        )
        return language_code

    # -------------------------------------------------------------------------
    # 2. Notification Preferences
    # -------------------------------------------------------------------------
    def get_notification_preferences(self, user_id: str) -> Dict[str, Any]:
        row = self.conn.execute(
            """SELECT enabled, preferred_language, categories_json, in_app_enabled,
                      browser_enabled, quiet_hours_json, updated_at
               FROM phase6_notification_preferences WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        if row:
            return {
                "user_id": user_id,
                "enabled": bool(row[0]),
                "preferred_language": row[1],
                "categories": json.loads(row[2]),
                "in_app_enabled": bool(row[3]),
                "browser_enabled": bool(row[4]),
                "quiet_hours": json.loads(row[5]),
                "updated_at": row[6],
            }
        # Return default
        now = now_iso()
        return {
            "user_id": user_id,
            "enabled": True,
            "preferred_language": "en-IN",
            "categories": [
                "TRIP_UPCOMING", "TRIP_STARTING", "BOOKING_CONFIRMED",
                "BOOKING_CANCELLED", "HOLD_EXPIRING", "HOLD_EXPIRED",
                "TRIP_PACK_READY", "ITINERARY_UPDATED", "TRAVEL_DAY_REMINDER",
            ],
            "in_app_enabled": True,
            "browser_enabled": True,
            "quiet_hours": {"enabled": False, "start": "22:00", "end": "08:00"},
            "updated_at": now,
        }

    def set_notification_preferences(self, user_id: str, prefs: Dict[str, Any]) -> Dict[str, Any]:
        now = now_iso()
        enabled = int(prefs.get("enabled", True))
        preferred_lang = prefs.get("preferred_language", "en-IN")
        categories_json = json.dumps(prefs.get("categories", [
            "TRIP_UPCOMING", "TRIP_STARTING", "BOOKING_CONFIRMED",
            "BOOKING_CANCELLED", "HOLD_EXPIRING", "HOLD_EXPIRED",
            "TRIP_PACK_READY", "ITINERARY_UPDATED", "TRAVEL_DAY_REMINDER",
        ]))
        in_app = int(prefs.get("in_app_enabled", True))
        browser = int(prefs.get("browser_enabled", True))
        quiet_hours_json = json.dumps(prefs.get("quiet_hours", {"enabled": False, "start": "22:00", "end": "08:00"}))

        self.conn.execute(
            """INSERT INTO phase6_notification_preferences
               (user_id, enabled, preferred_language, categories_json, in_app_enabled, browser_enabled, quiet_hours_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 enabled = excluded.enabled,
                 preferred_language = excluded.preferred_language,
                 categories_json = excluded.categories_json,
                 in_app_enabled = excluded.in_app_enabled,
                 browser_enabled = excluded.browser_enabled,
                 quiet_hours_json = excluded.quiet_hours_json,
                 updated_at = excluded.updated_at""",
            (user_id, enabled, preferred_lang, categories_json, in_app, browser, quiet_hours_json, now),
        )
        return self.get_notification_preferences(user_id)

    # -------------------------------------------------------------------------
    # 3. Notifications Store & Queries
    # -------------------------------------------------------------------------
    def insert_notification(
        self,
        *,
        user_id: str,
        event_type: str,
        title: str,
        body: str,
        language: str,
        trip_id: Optional[str] = None,
        booking_id: Optional[str] = None,
        dedupe_key: str,
    ) -> Optional[Dict[str, Any]]:
        """Inserts a notification idempotently. Returns the notification or existing on dedupe match."""
        # Check if already exists by dedupe_key
        existing = self.conn.execute(
            """SELECT notification_id, user_id, event_type, title, body, language, is_read, read_at,
                      trip_id, booking_id, dedupe_key, created_at
               FROM phase6_notifications WHERE dedupe_key = ?""",
            (dedupe_key,),
        ).fetchone()
        if existing:
            return self._row_to_notification(existing)

        notif_id = new_id("not")
        now = now_iso()
        try:
            self.conn.execute(
                """INSERT INTO phase6_notifications
                   (notification_id, user_id, event_type, title, body, language, is_read, read_at,
                    trip_id, booking_id, dedupe_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?)""",
                (notif_id, user_id, event_type, title, body, language, trip_id, booking_id, dedupe_key, now),
            )
        except sqlite3.IntegrityError:
            # Race condition dedupe
            existing = self.conn.execute(
                """SELECT notification_id, user_id, event_type, title, body, language, is_read, read_at,
                          trip_id, booking_id, dedupe_key, created_at
                   FROM phase6_notifications WHERE dedupe_key = ?""",
                (dedupe_key,),
            ).fetchone()
            return self._row_to_notification(existing) if existing else None

        return {
            "notification_id": notif_id,
            "user_id": user_id,
            "event_type": event_type,
            "title": title,
            "body": body,
            "language": language,
            "is_read": False,
            "read_at": None,
            "trip_id": trip_id,
            "booking_id": booking_id,
            "dedupe_key": dedupe_key,
            "created_at": now,
        }

    def list_user_notifications(
        self,
        user_id: str,
        *,
        limit: int = 50,
        unread_only: bool = False,
    ) -> List[Dict[str, Any]]:
        query = """SELECT notification_id, user_id, event_type, title, body, language, is_read, read_at,
                          trip_id, booking_id, dedupe_key, created_at
                   FROM phase6_notifications
                   WHERE user_id = ?"""
        params: List[Any] = [user_id]
        if unread_only:
            query += " AND is_read = 0"
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_notification(r) for r in rows]

    def count_unread_notifications(self, user_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM phase6_notifications WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()
        return row[0] if row else 0

    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        """Marks a notification as read, enforcing user ownership."""
        now = now_iso()
        res = self.conn.execute(
            """UPDATE phase6_notifications
               SET is_read = 1, read_at = ?
               WHERE notification_id = ? AND user_id = ?""",
            (now, notification_id, user_id),
        )
        return res.rowcount > 0

    def mark_all_notifications_read(self, user_id: str) -> int:
        now = now_iso()
        res = self.conn.execute(
            """UPDATE phase6_notifications
               SET is_read = 1, read_at = ?
               WHERE user_id = ? AND is_read = 0""",
            (now, user_id),
        )
        return res.rowcount

    def _row_to_notification(self, row: tuple) -> Dict[str, Any]:
        return {
            "notification_id": row[0],
            "user_id": row[1],
            "event_type": row[2],
            "title": row[3],
            "body": row[4],
            "language": row[5],
            "is_read": bool(row[6]),
            "read_at": row[7],
            "trip_id": row[8],
            "booking_id": row[9],
            "dedupe_key": row[10],
            "created_at": row[11],
        }

    # -------------------------------------------------------------------------
    # 4. Emergency Contacts & Events
    # -------------------------------------------------------------------------
    def list_emergency_contacts(self, user_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT contact_id, user_id, name, relationship, phone_number, is_primary, created_at, updated_at
               FROM phase6_emergency_contacts
               WHERE user_id = ?
               ORDER BY is_primary DESC, created_at ASC""",
            (user_id,),
        ).fetchall()
        return [
            {
                "contact_id": r[0],
                "user_id": r[1],
                "name": r[2],
                "relationship": r[3],
                "phone_number": r[4],
                "is_primary": bool(r[5]),
                "created_at": r[6],
                "updated_at": r[7],
            }
            for r in rows
        ]

    def get_emergency_contact(self, user_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """SELECT contact_id, user_id, name, relationship, phone_number, is_primary, created_at, updated_at
               FROM phase6_emergency_contacts
               WHERE contact_id = ? AND user_id = ?""",
            (contact_id, user_id),
        ).fetchone()
        if not row:
            return None
        return {
            "contact_id": row[0],
            "user_id": row[1],
            "name": row[2],
            "relationship": row[3],
            "phone_number": row[4],
            "is_primary": bool(row[5]),
            "created_at": row[6],
            "updated_at": row[7],
        }

    def add_emergency_contact(
        self,
        *,
        user_id: str,
        name: str,
        relationship: str,
        phone_number: str,
        is_primary: bool = True,
    ) -> Dict[str, Any]:
        cleaned_phone = phone_number.strip()
        existing_phone = self.conn.execute(
            "SELECT contact_id FROM phase6_emergency_contacts WHERE user_id = ? AND phone_number = ?",
            (user_id, cleaned_phone),
        ).fetchone()
        if existing_phone:
            raise ValueError(f"A trusted contact with phone number {phone_number} already exists.")

        contact_id = new_id("emc")
        now = now_iso()
        if is_primary:
            self.conn.execute(
                "UPDATE phase6_emergency_contacts SET is_primary = 0 WHERE user_id = ?",
                (user_id,),
            )
        self.conn.execute(
            """INSERT INTO phase6_emergency_contacts
               (contact_id, user_id, name, relationship, phone_number, is_primary, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (contact_id, user_id, name.strip(), relationship.strip(), cleaned_phone, int(is_primary), now, now),
        )
        return {
            "contact_id": contact_id,
            "user_id": user_id,
            "name": name.strip(),
            "relationship": relationship.strip(),
            "phone_number": cleaned_phone,
            "is_primary": is_primary,
            "created_at": now,
            "updated_at": now,
        }

    def update_emergency_contact(
        self,
        *,
        user_id: str,
        contact_id: str,
        name: Optional[str] = None,
        relationship: Optional[str] = None,
        phone_number: Optional[str] = None,
        is_primary: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_emergency_contact(user_id, contact_id)
        if not existing:
            return None

        new_name = name.strip() if name is not None else existing["name"]
        new_rel = relationship.strip() if relationship is not None else existing["relationship"]
        new_phone = phone_number.strip() if phone_number is not None else existing["phone_number"]
        new_primary = bool(is_primary) if is_primary is not None else existing["is_primary"]
        now = now_iso()

        # If phone changed, verify not duplicate with another contact of same user
        if phone_number is not None and new_phone != existing["phone_number"]:
            dup = self.conn.execute(
                "SELECT contact_id FROM phase6_emergency_contacts WHERE user_id = ? AND phone_number = ? AND contact_id != ?",
                (user_id, new_phone, contact_id),
            ).fetchone()
            if dup:
                raise ValueError(f"A trusted contact with phone number {new_phone} already exists.")

        if new_primary and not existing["is_primary"]:
            self.conn.execute(
                "UPDATE phase6_emergency_contacts SET is_primary = 0 WHERE user_id = ?",
                (user_id,),
            )

        self.conn.execute(
            """UPDATE phase6_emergency_contacts
               SET name = ?, relationship = ?, phone_number = ?, is_primary = ?, updated_at = ?
               WHERE contact_id = ? AND user_id = ?""",
            (new_name, new_rel, new_phone, int(new_primary), now, contact_id, user_id),
        )
        return self.get_emergency_contact(user_id, contact_id)

    def delete_emergency_contact(self, *, user_id: str, contact_id: str) -> bool:
        res = self.conn.execute(
            "DELETE FROM phase6_emergency_contacts WHERE contact_id = ? AND user_id = ?",
            (contact_id, user_id),
        )
        return res.rowcount > 0

    def record_emergency_event(
        self,
        *,
        user_id: str,
        event_type: str,
        trip_id: Optional[str] = None,
        booking_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_id = new_id("sos")
        now = now_iso()
        details_json = json.dumps(details or {})
        self.conn.execute(
            """INSERT INTO phase6_emergency_events
               (event_id, user_id, event_type, trip_id, booking_id, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, user_id, event_type, trip_id, booking_id, details_json, now),
        )
        return {
            "event_id": event_id,
            "user_id": user_id,
            "event_type": event_type,
            "trip_id": trip_id,
            "booking_id": booking_id,
            "details": details or {},
            "created_at": now,
        }

    def get_current_trip_context(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Resolves the most recent or upcoming trip for the user for emergency context."""
        row = self.conn.execute(
            """SELECT t.trip_id, t.title, c.name, t.start_date, t.end_date, t.status
               FROM trips t
               JOIN cities c ON t.destination_city_id = c.city_id
               WHERE t.owner_user_id = ? AND t.status != 'cancelled'
               ORDER BY t.start_date DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        if not row:
            return None

        trip_id = row[0]
        # Check if booking exists
        b_row = self.conn.execute(
            """SELECT booking_id, status FROM bookings
               WHERE user_id = ? AND status = 'confirmed'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()

        booking_ref = None
        hotel_name = None
        if b_row:
            booking_id = b_row[0]
            # Try to get booking reference or hotel from booking items
            item = self.conn.execute(
                """SELECT title FROM booking_items
                   WHERE booking_id = ? AND entity_type IN ('hotel', 'stay', 'room') LIMIT 1""",
                (booking_id,),
            ).fetchone()
            if item:
                hotel_name = item[0]
            # Get demo reference
            pack = self.conn.execute(
                "SELECT pack_json FROM trip_packs WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
            if pack:
                try:
                    booking_ref = json.loads(pack[0]).get("booking_reference")
                except Exception:
                    booking_ref = f"YTR-DEMO-{booking_id[-8:].upper()}"
            else:
                booking_ref = f"YTR-DEMO-{booking_id[-8:].upper()}"

        return {
            "trip_id": row[0],
            "title": row[1],
            "destination_city": row[2],
            "start_date": row[3],
            "end_date": row[4],
            "status": row[5],
            "booking_reference": booking_ref,
            "hotel_name": hotel_name or f"Hotel in {row[2]}",
        }
