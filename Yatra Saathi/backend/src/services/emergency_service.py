"""Phase 6 Emergency Assistance & SOS Service.

Responsibilities:
- Authoritative configured emergency contacts (India official services).
- Explicit SOS activation requirement (never triggered automatically by text/speech).
- Current trip context resolution for emergency situations without location tracking.
- Trip details share confirmation with user preview and optional location coordinates.
- Audit event recording for emergency operations.
- Cross-user security and data isolation.
- Honest reporting of notification capabilities and demo simulation modes.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from src.contracts.codes import RefusalError
from src.core.clock import now_iso
from src.db.repositories.phase6_repo import Phase6Repository
from src.schemas.emergency import (
    ActivateSosRequest,
    ActivateSosResponse,
    CreateTrustedContactRequest,
    EmergencyInfoResponse,
    EmergencyTripContext,
    OfficialEmergencyContact,
    ShareTripRequest,
    ShareTripResponse,
    ShareTripSummary,
    UpdateTrustedContactRequest,
    UserTrustedContact,
)

OFFICIAL_INDIA_EMERGENCY_SERVICES: List[OfficialEmergencyContact] = [
    OfficialEmergencyContact(
        service_name="National Emergency Helpline",
        number="112",
        description="Unified emergency helpline for Police, Fire, Ambulance, and Disaster Management across India.",
        is_toll_free=True,
    ),
    OfficialEmergencyContact(
        service_name="Police",
        number="100",
        description="Immediate law enforcement and safety assistance.",
        is_toll_free=True,
    ),
    OfficialEmergencyContact(
        service_name="Medical Ambulance",
        number="102",
        description="Emergency ambulance and medical response service.",
        is_toll_free=True,
    ),
    OfficialEmergencyContact(
        service_name="Fire & Rescue Services",
        number="101",
        description="Fire emergency and immediate hazard response.",
        is_toll_free=True,
    ),
    OfficialEmergencyContact(
        service_name="Women Safety Helpline",
        number="1091",
        description="Dedicated safety helpline for women travellers.",
        is_toll_free=True,
    ),
    OfficialEmergencyContact(
        service_name="Incredible India Tourist Helpline",
        number="1363",
        description="24x7 multi-lingual tourist helpline by Ministry of Tourism, India.",
        is_toll_free=True,
    ),
]


class EmergencyService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = Phase6Repository(conn)

    def get_emergency_info(self, user_id: str) -> EmergencyInfoResponse:
        """Retrieves authoritative emergency assistance information for the user."""
        # Record audit event
        self.repo.record_emergency_event(
            user_id=user_id,
            event_type="EMERGENCY_ASSISTANCE_OPENED",
        )

        contacts = self.repo.list_emergency_contacts(user_id)
        trip_ctx = self.repo.get_current_trip_context(user_id)

        current_trip = EmergencyTripContext(**trip_ctx) if trip_ctx else None

        return EmergencyInfoResponse(
            safety_notice="If you are in immediate danger, contact local emergency services immediately (Dial 112).",
            primary_emergency_number="112",
            official_services=OFFICIAL_INDIA_EMERGENCY_SERVICES,
            trusted_contacts=[UserTrustedContact(**c) for c in contacts],
            current_trip_context=current_trip,
            location_tracking_status="Location tracking is disabled. Location is never collected without explicit consent.",
        )

    def activate_sos(self, user_id: str, request: ActivateSosRequest) -> ActivateSosResponse:
        """Explicit SOS activation. AI/speech cannot trigger this without user confirmation."""
        if not request.explicit_confirmation:
            raise RefusalError(
                "EXPLICIT_CONFIRMATION_REQUIRED",
                "SOS activation requires explicit user confirmation via the Emergency Assistance interface.",
            )

        now = now_iso()
        loc_dict = request.location.model_dump() if request.location else None

        # Determine location source: gps, geocoded, manual_unverified, or none
        if request.location:
            loc_source = request.location.source or request.location_source or "gps"
            loc_display = (
                request.location.display_label
                or f"Coordinates ({request.location.latitude:.4f}, {request.location.longitude:.4f})"
            )
        elif request.location_text:
            loc_source = "manual_unverified"
            loc_display = request.location_text
        else:
            loc_source = "none"
            loc_display = None

        details: Dict[str, Any] = {
            "reason": request.reason or request.notes or "Explicit SOS trigger in emergency assistance modal",
            "location": loc_dict,
            "location_text": request.location_text,
            "location_source": loc_source,
            "location_display": loc_display,
            "notes": request.notes,
            "delivery_provider": {
                "sms_provider": "NOT_CONFIGURED",
                "push_provider": "NOT_CONFIGURED",
                "mode": "DEMO_SIMULATION",
            },
        }

        # Record audit event
        event = self.repo.record_emergency_event(
            user_id=user_id,
            event_type="SOS_ACTIVATED",
            trip_id=request.trip_id,
            booking_id=request.booking_id,
            details=details,
        )

        instructions = [
            "Dial 112 immediately on your device if in immediate danger (unified police, fire, ambulance).",
            "Stay calm and move to a visible, well-lit, secure public area if safe to do so.",
            "Share your live location coordinates or trip reference with your trusted contacts.",
            "Conserve device battery and keep this emergency assistance screen open.",
            "Audit Note: An immutable emergency event has been logged with your trip reference. Automated external dispatch is in simulation mode.",
        ]

        delivery_provider_status = {
            "sms_configured": False,
            "push_configured": False,
            "mode": "DEMO_SIMULATION",
            "message": "External automated dispatch/SMS gateway is not configured in this environment. Please dial 112 directly or use manual sharing.",
        }

        return ActivateSosResponse(
            sos_event_id=event["event_id"],
            event_id=event["event_id"],
            status="ACTIVATED",
            emergency_notice=(
                "SOS audit event recorded. If you are in immediate danger, please dial 112 immediately. "
                "Automated external dispatch is in simulation mode."
            ),
            disclaimer="Yatra Saathi assistance is a companion tool and does not replace official emergency dispatch (Dial 112).",
            official_number_to_dial="112",
            trusted_contacts_notified_mode="DEMO_SIMULATION",
            instructions=instructions,
            delivery_provider_status=delivery_provider_status,
            location_captured=loc_dict,
            location_source=loc_source,
            location_display=loc_display,
            timestamp=now,
        )

    def add_trusted_contact(
        self,
        user_id: str,
        req: CreateTrustedContactRequest,
    ) -> UserTrustedContact:
        try:
            c = self.repo.add_emergency_contact(
                user_id=user_id,
                name=req.name or req.contact_name or "",
                relationship=req.relationship,
                phone_number=req.phone_number,
                is_primary=req.is_primary,
            )
            return UserTrustedContact(**c)
        except ValueError as err:
            raise RefusalError("DUPLICATE_CONTACT", str(err))

    def update_trusted_contact(
        self,
        user_id: str,
        contact_id: str,
        req: UpdateTrustedContactRequest,
    ) -> UserTrustedContact:
        existing = self.repo.get_emergency_contact(user_id, contact_id)
        if not existing:
            raise RefusalError("EMERGENCY_CONTACT_NOT_FOUND", "Emergency contact not found or access denied.")
        try:
            updated = self.repo.update_emergency_contact(
                user_id=user_id,
                contact_id=contact_id,
                name=req.name or req.contact_name,
                relationship=req.relationship,
                phone_number=req.phone_number,
                is_primary=req.is_primary,
            )
            if not updated:
                raise RefusalError("EMERGENCY_CONTACT_NOT_FOUND", "Emergency contact not found or access denied.")
            return UserTrustedContact(**updated)
        except ValueError as err:
            raise RefusalError("DUPLICATE_CONTACT", str(err))

    def delete_trusted_contact(self, user_id: str, contact_id: str) -> bool:
        existing = self.repo.get_emergency_contact(user_id, contact_id)
        if not existing:
            raise RefusalError("EMERGENCY_CONTACT_NOT_FOUND", "Emergency contact not found or access denied.")
        return self.repo.delete_emergency_contact(user_id=user_id, contact_id=contact_id)

    def list_trusted_contacts(self, user_id: str) -> List[UserTrustedContact]:
        return [UserTrustedContact(**c) for c in self.repo.list_emergency_contacts(user_id)]

    def share_trip_details(self, user_id: str, request: ShareTripRequest) -> ShareTripResponse:
        """Shares trip details to trusted contacts only with explicit user confirmation."""
        if not request.explicit_user_confirmation and not request.explicit_share_consent:
            raise RefusalError(
                "EXPLICIT_CONFIRMATION_REQUIRED",
                "Sharing trip details requires explicit confirmation of the preview summary.",
            )

        # Validate trip ownership
        trip_row = self.conn.execute(
            """SELECT t.trip_id, t.title, c.name, t.start_date, t.end_date, t.owner_user_id
               FROM trips t
               JOIN cities c ON t.destination_city_id = c.city_id
               WHERE t.trip_id = ?""",
            (request.trip_id,),
        ).fetchone()

        if not trip_row:
            raise RefusalError("TRIP_NOT_FOUND", f"Trip {request.trip_id} not found.")
        if trip_row[5] != user_id:
            raise RefusalError("EMERGENCY_ACCESS_DENIED", "Access to another user's trip is denied.")

        dest = trip_row[2]
        dates = f"{trip_row[3]} to {trip_row[4]}"

        # Look for hotel and booking reference
        pack_row = self.conn.execute(
            """SELECT pack_json FROM trip_packs
               WHERE user_id = ? ORDER BY generated_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()

        booking_ref = None
        if pack_row:
            try:
                pj = json.loads(pack_row[0])
                booking_ref = pj.get("booking_reference")
            except Exception:
                booking_ref = None
        hotel_name = f"Accommodation in {dest}"

        loc_text = ""
        if request.location:
            loc_text = f" Current GPS: {request.location.latitude:.4f}, {request.location.longitude:.4f}."
        elif request.location_text:
            loc_text = f" Reported Location: {request.location_text}."

        summary = ShareTripSummary(
            destination=dest,
            hotel=hotel_name,
            booking_reference=booking_ref,
            trip_dates=dates,
            share_preview_text=(
                f"Emergency Trip Details: Travelling to {dest} from {dates}. "
                f"Reference: {booking_ref or 'Demo Booking'}.{loc_text} In case of emergency, contact local authorities (112)."
            ),
            location_summary=loc_text.strip() or None,
        )

        now = now_iso()
        loc_dict = request.location.model_dump() if request.location else None

        # Record audit event
        event = self.repo.record_emergency_event(
            user_id=user_id,
            event_type="TRIP_DETAILS_SHARE_REQUESTED",
            trip_id=request.trip_id,
            details={
                "contact_id": request.trusted_contact_id,
                "summary": summary.model_dump(),
                "location": loc_dict,
                "location_text": request.location_text,
            },
        )

        return ShareTripResponse(
            share_event_id=event["event_id"],
            trip_id=request.trip_id,
            status="SHARED_TO_TRUSTED_CONTACT",
            summary=summary,
            timestamp=now,
        )
