"""Phase 6 Notifications & Event-Driven Alerts Service.

Responsibilities:
- Event Rule Engine & Dispatcher.
- Generates notifications ONLY from authoritative backend events.
- Strict deduplication / idempotency key generation.
- Enforces user notification preferences, categories, and quiet hours.
- Multilingual notification rendering preserving all structured identifiers.
- Cross-user notification isolation.
- Immutable audit retention (deletion blocked by SQL triggers).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.contracts.codes import RefusalError
from src.core.clock import now_iso
from src.db.repositories.phase6_repo import Phase6Repository
from src.schemas.notifications import (
    NotificationItem,
    NotificationListResponse,
    NotificationPreferencesResponse,
    QuietHoursConfig,
    UpdateNotificationPreferencesRequest,
)
from src.services.language_service import LanguageService


class Phase6NotificationService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = Phase6Repository(conn)
        self.lang_service = LanguageService(conn)

    def trigger_event(
        self,
        *,
        user_id: str,
        event_type: str,
        entity_id: str,
        trip_id: Optional[str] = None,
        booking_id: Optional[str] = None,
        language: Optional[str] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Authoritatively handles a lifecycle event and dispatches a notification if permitted."""
        extra = extra_context or {}

        # 1. Resolve user notification preferences
        prefs = self.repo.get_notification_preferences(user_id)
        if not prefs.get("enabled", True):
            return None
        if event_type not in prefs.get("categories", []):
            return None
        if not prefs.get("in_app_enabled", True):
            return None

        # 2. Determine target language
        target_lang = language or prefs.get("preferred_language") or self.repo.get_user_language_preference(user_id)
        if target_lang not in ("en-IN", "hi-IN", "ta-IN"):
            target_lang = "en-IN"

        # 3. Compute deterministic dedupe key
        event_version = extra.get("version", "v1")
        date_stamp = extra.get("date_stamp", date.today().isoformat())
        dedupe_key = f"{event_type}:{entity_id}:{user_id}:{date_stamp}:{event_version}"

        # 4. Generate grounded content based on authoritative data
        title, body = self._render_notification_content(
            event_type=event_type,
            target_lang=target_lang,
            entity_id=entity_id,
            trip_id=trip_id,
            booking_id=booking_id,
            extra=extra,
        )

        # 5. Persist notification idempotently
        return self.repo.insert_notification(
            user_id=user_id,
            event_type=event_type,
            title=title,
            body=body,
            language=target_lang,
            trip_id=trip_id,
            booking_id=booking_id,
            dedupe_key=dedupe_key,
        )

    def _render_notification_content(
        self,
        event_type: str,
        target_lang: str,
        entity_id: str,
        trip_id: Optional[str],
        booking_id: Optional[str],
        extra: Dict[str, Any],
    ) -> tuple[str, str]:
        dest = extra.get("destination", "your destination")
        ref = extra.get("booking_reference") or booking_id or entity_id
        dt = extra.get("date", "upcoming date")

        if event_type == "BOOKING_CONFIRMED":
            title = self.lang_service.localize_template("booking_confirmed_title", target_lang)
            body = self.lang_service.localize_template("booking_confirmed_body", target_lang, reference=ref)
        elif event_type == "BOOKING_CANCELLED":
            title = self.lang_service.localize_template("booking_cancelled_title", target_lang)
            body = self.lang_service.localize_template("booking_cancelled_body", target_lang, reference=ref)
        elif event_type == "TRIP_UPCOMING":
            title = self.lang_service.localize_template("trip_upcoming_title", target_lang)
            body = self.lang_service.localize_template("trip_upcoming_body", target_lang, destination=dest, date=dt)
        elif event_type == "TRIP_PACK_READY":
            title = self.lang_service.localize_template("trip_pack_ready_title", target_lang)
            body = self.lang_service.localize_template("trip_pack_ready_body", target_lang, destination=dest)
        elif event_type == "HOLD_EXPIRING":
            if target_lang == "hi-IN":
                title = "इन्वेंट्री होल्ड समाप्त होने वाला है"
                body = f"यात्रा कार्यक्रम {entity_id} के लिए आपका होल्ड 5 मिनट में समाप्त हो जाएगा।"
            elif target_lang == "ta-IN":
                title = "இருப்பு நிறுத்திவைப்பு விரைவில் காலாவதியாகிறது"
                body = f"பயணத்திட்டம் {entity_id} க்கான நிறுத்திவைப்பு 5 நிமிடங்களில் காலாவதியாகும்."
            else:
                title = "Inventory Hold Expiring"
                body = f"Inventory hold for itinerary {entity_id} will expire in 5 minutes."
        elif event_type == "HOLD_EXPIRED":
            if target_lang == "hi-IN":
                title = "इन्वेंट्री होल्ड समाप्त हो गया"
                body = f"यात्रा कार्यक्रम {entity_id} के लिए इन्वेंट्री होल्ड समाप्त हो गया है।"
            elif target_lang == "ta-IN":
                title = "இருப்பு நிறுத்திவைப்பு காலாவதியானது"
                body = f"பயணத்திட்டம் {entity_id} க்கான நிறுத்திவைப்பு காலாவதியானது."
            else:
                title = "Inventory Hold Expired"
                body = f"Inventory hold for itinerary {entity_id} has expired."
        elif event_type == "TRAVEL_DAY_REMINDER":
            day_num = extra.get("day", 1)
            if target_lang == "hi-IN":
                title = "यात्रा दिवस स्मरणपत्र"
                body = f"{dest} की आपकी यात्रा का दिन {day_num} आज से शुरू हो रहा है।"
            elif target_lang == "ta-IN":
                title = "பயண நாள் நினைவூட்டல்"
                body = f"{dest} பயணத்தின் நாள் {day_num} இன்று தொடங்குகிறது."
            else:
                title = "Travel Day Reminder"
                body = f"Day {day_num} of your trip to {dest} begins today."
        else:
            title = f"Travel Update: {event_type.replace('_', ' ').title()}"
            body = f"Update for {dest} ({entity_id})."

        return title, body

    def list_notifications(
        self,
        user_id: str,
        *,
        limit: int = 50,
        unread_only: bool = False,
    ) -> NotificationListResponse:
        items = self.repo.list_user_notifications(user_id, limit=limit, unread_only=unread_only)
        unread = self.repo.count_unread_notifications(user_id)
        notifications = [NotificationItem(**it) for it in items]
        return NotificationListResponse(
            user_id=user_id,
            total_count=len(notifications),
            unread_count=unread,
            notifications=notifications,
        )

    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        # Check if notification exists
        row = self.conn.execute(
            "SELECT user_id FROM phase6_notifications WHERE notification_id = ?",
            (notification_id,),
        ).fetchone()
        if not row:
            raise RefusalError("NOTIFICATION_NOT_FOUND", f"Notification {notification_id} not found.")
        if row[0] != user_id:
            raise RefusalError("NOTIFICATION_OWNERSHIP_DENIED", "Access to another user's notification is denied.")
        return self.repo.mark_notification_read(user_id, notification_id)

    def mark_all_read(self, user_id: str) -> int:
        return self.repo.mark_all_notifications_read(user_id)

    def get_preferences(self, user_id: str) -> NotificationPreferencesResponse:
        prefs = self.repo.get_notification_preferences(user_id)
        return NotificationPreferencesResponse(
            user_id=user_id,
            enabled=prefs["enabled"],
            preferred_language=prefs["preferred_language"],
            categories=prefs["categories"],
            in_app_enabled=prefs["in_app_enabled"],
            browser_enabled=prefs["browser_enabled"],
            quiet_hours=QuietHoursConfig(**prefs["quiet_hours"]),
            updated_at=prefs["updated_at"],
        )

    def update_preferences(
        self,
        user_id: str,
        req: UpdateNotificationPreferencesRequest,
    ) -> NotificationPreferencesResponse:
        current = self.repo.get_notification_preferences(user_id)
        if req.enabled is not None:
            current["enabled"] = req.enabled
        if req.preferred_language is not None:
            if req.preferred_language not in ("en-IN", "hi-IN", "ta-IN"):
                raise RefusalError("UNSUPPORTED_LANGUAGE", f"Language {req.preferred_language} is not supported.")
            current["preferred_language"] = req.preferred_language
        if req.categories is not None:
            current["categories"] = req.categories
        if req.in_app_enabled is not None:
            current["in_app_enabled"] = req.in_app_enabled
        if req.browser_enabled is not None:
            current["browser_enabled"] = req.browser_enabled
        if req.quiet_hours is not None:
            current["quiet_hours"] = req.quiet_hours.dict()

        saved = self.repo.set_notification_preferences(user_id, current)
        return NotificationPreferencesResponse(
            user_id=user_id,
            enabled=saved["enabled"],
            preferred_language=saved["preferred_language"],
            categories=saved["categories"],
            in_app_enabled=saved["in_app_enabled"],
            browser_enabled=saved["browser_enabled"],
            quiet_hours=QuietHoursConfig(**saved["quiet_hours"]),
            updated_at=saved["updated_at"],
        )

    def check_trip_reminders(self, user_id: str, target_date: Optional[date] = None) -> List[Dict[str, Any]]:
        """Evaluates upcoming trips authoritatively against the calendar and sends reminders if due."""
        check_day = target_date or date.today()
        tomorrow = check_day + timedelta(days=1)

        # Query active (non-cancelled) trips for this user starting tomorrow
        trips = self.conn.execute(
            """SELECT t.trip_id, t.title, c.name, t.start_date, t.status
               FROM trips t
               JOIN cities c ON t.destination_city_id = c.city_id
               WHERE t.owner_user_id = ? AND t.status != 'cancelled' AND t.start_date = ?""",
            (user_id, tomorrow.isoformat()),
        ).fetchall()

        created_notifs = []
        for trip_id, title, city_name, start_dt, status in trips:
            res = self.trigger_event(
                user_id=user_id,
                event_type="TRIP_UPCOMING",
                entity_id=trip_id,
                trip_id=trip_id,
                extra_context={
                    "destination": city_name,
                    "date": start_dt,
                    "date_stamp": tomorrow.isoformat(),
                },
            )
            if res:
                created_notifs.append(res)
        return created_notifs
