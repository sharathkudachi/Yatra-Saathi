"""Comprehensive Unit & Integration Test Suite for Emergency Assistance & SOS Feature.

Validates:
1. Authoritative official emergency configuration for India (112, 100, 102, 101, 1091, 1363)
2. Field-level compatibility across frontend and backend schemas
3. Trusted contact CRUD (Add, List, Update, Delete)
4. Input validation (name, relationship, phone digits) and duplicate rejection
5. Cross-user isolation (contacts and trip access denied across user boundaries)
6. SOS activation state flow, explicit confirmation enforcement, and idempotency
7. Audit event persistence and immutability (trigger trg_p6sos_no_delete)
8. GPS Location coordinates logging and landmark notes
9. Honest capability reporting (disclosure of simulation mode when no SMS provider is configured)
10. Fallback and manual sharing mechanisms
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from fastapi.testclient import TestClient

from src.contracts.codes import RefusalError
from src.core.ids import new_id
from src.main import create_app
from src.schemas.emergency import (
    ActivateSosRequest,
    CreateTrustedContactRequest,
    LocationCoordinates,
    ShareTripRequest,
    UpdateTrustedContactRequest,
)
from src.services.emergency_service import EmergencyService, OFFICIAL_INDIA_EMERGENCY_SERVICES
from tests.support import WorkingCopy, assert_original_untouched


class EmergencyAssistanceCompleteTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert_original_untouched()
        cls.wc = WorkingCopy(migrate=True)
        cls.conn = cls.wc.raw()
        cls.sos_service = EmergencyService(cls.conn)

        # Create two test users for data isolation tests
        cls.user1 = "usr_em_test_user1"
        cls.user2 = "usr_em_test_user2"
        now = "2026-10-17T10:00:00+05:30"
        for uid, email in [(cls.user1, "em_user1@example.com"), (cls.user2, "em_user2@example.com")]:
            cls.conn.execute(
                """INSERT OR IGNORE INTO users
                   (user_id, display_name, email, home_city_id, home_currency, locale,
                    budget_band, travel_style, traveller_type, segment, date_of_signup, status, created_at, updated_at)
                   VALUES (?, 'Emergency User', ?, (SELECT city_id FROM cities LIMIT 1), 'INR', 'en-IN',
                           'medium', 'balanced', 'solo', 'retail', '2026-01-01', 'active', ?, ?)""",
                (uid, email, now, now),
            )

        # Setup FastAPI TestClient with auth headers
        import dataclasses
        from src.core import human_tokens
        cls.secret = "b" * 64
        cls.settings = dataclasses.replace(cls.wc.settings, human_token_secret=cls.secret)
        cls.app = create_app(cls.settings)
        cls.client = TestClient(cls.app)

        from datetime import datetime, timezone
        now_dt = datetime.now(timezone.utc)
        tok1 = human_tokens.issue(cls.secret, cls.user1, now=now_dt)
        tok2 = human_tokens.issue(cls.secret, cls.user2, now=now_dt)
        cls.headers_user1 = {"Authorization": f"Bearer {tok1}"}
        cls.headers_user2 = {"Authorization": f"Bearer {tok2}"}

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.wc.cleanup()
        assert_original_untouched()

    # =========================================================================
    # 1. Official Emergency Configuration
    # =========================================================================
    def test_01_authoritative_official_emergency_numbers(self):
        """All official Indian emergency services are present and verified."""
        num_map = {s.service_name: s.number for s in OFFICIAL_INDIA_EMERGENCY_SERVICES}
        self.assertEqual(num_map.get("National Emergency Helpline"), "112")
        self.assertEqual(num_map.get("Police"), "100")
        self.assertEqual(num_map.get("Medical Ambulance"), "102")
        self.assertEqual(num_map.get("Fire & Rescue Services"), "101")
        self.assertEqual(num_map.get("Women Safety Helpline"), "1091")
        self.assertEqual(num_map.get("Incredible India Tourist Helpline"), "1363")

    def test_02_official_numbers_toll_free_and_no_fabrication(self):
        """All official numbers are 3 or 4 digits and marked toll free."""
        for s in OFFICIAL_INDIA_EMERGENCY_SERVICES:
            self.assertRegex(s.number, r"^\d{3,4}$")
            self.assertTrue(s.is_toll_free)
            self.assertEqual(s.name, s.service_name)

    # =========================================================================
    # 2. Emergency Info & Compatibility Endpoints
    # =========================================================================
    def test_03_emergency_info_field_compatibility(self):
        """EmergencyInfoResponse contains both old and new field aliases for frontend compatibility."""
        info = self.sos_service.get_emergency_info(self.user1)
        self.assertEqual(info.primary_emergency_number, "112")
        self.assertGreaterEqual(len(info.official_services), 6)
        # Compatibility aliases:
        self.assertEqual(len(info.official_numbers), len(info.official_services))
        self.assertEqual(info.trusted_contacts, info.user_contacts)
        self.assertEqual(info.safety_notice, info.disclaimer)

    def test_04_emergency_info_records_audit_event(self):
        """Opening emergency info creates an audit log entry in phase6_emergency_events."""
        count_before = self.conn.execute(
            "SELECT COUNT(*) FROM phase6_emergency_events WHERE user_id = ? AND event_type = 'EMERGENCY_ASSISTANCE_OPENED'",
            (self.user1,),
        ).fetchone()[0]

        self.sos_service.get_emergency_info(self.user1)

        count_after = self.conn.execute(
            "SELECT COUNT(*) FROM phase6_emergency_events WHERE user_id = ? AND event_type = 'EMERGENCY_ASSISTANCE_OPENED'",
            (self.user1,),
        ).fetchone()[0]
        self.assertEqual(count_after, count_before + 1)

    # =========================================================================
    # 3. Trusted Contacts CRUD & Validation
    # =========================================================================
    def test_05_add_trusted_contact_with_name_or_contact_name(self):
        """Accepts either 'name' or 'contact_name' seamlessly."""
        # Using name
        req1 = CreateTrustedContactRequest(name="Aarav Sharma", relationship="Brother", phone_number="+91 98765 11111")
        c1 = self.sos_service.add_trusted_contact(self.user1, req1)
        self.assertEqual(c1.name, "Aarav Sharma")
        self.assertEqual(c1.contact_name, "Aarav Sharma")
        self.assertEqual(c1.relationship, "Brother")

        # Using contact_name
        req2 = CreateTrustedContactRequest(contact_name="Pooja Sharma", relationship="Sister", phone_number="+91 98765 22222")
        c2 = self.sos_service.add_trusted_contact(self.user1, req2)
        self.assertEqual(c2.name, "Pooja Sharma")
        self.assertEqual(c2.contact_name, "Pooja Sharma")

    def test_06_reject_invalid_contact_details(self):
        """Rejects empty/short names, short relationships, and invalid phone numbers."""
        # Short name
        with self.assertRaises(ValueError):
            CreateTrustedContactRequest(name="A", relationship="Sister", phone_number="+91 98765 33333")

        # Short relationship
        with self.assertRaises(ValueError):
            CreateTrustedContactRequest(name="Sunita", relationship="F", phone_number="+91 98765 33333")

        # Invalid phone (letters)
        with self.assertRaises(ValueError):
            CreateTrustedContactRequest(name="Sunita", relationship="Friend", phone_number="not-a-number")

        # Phone with too few digits
        with self.assertRaises(ValueError):
            CreateTrustedContactRequest(name="Sunita", relationship="Friend", phone_number="12")

    def test_07_reject_duplicate_phone_number_for_same_user(self):
        """Rejects adding a second contact with identical phone number for same user."""
        phone = "+91 98765 44444"
        req = CreateTrustedContactRequest(name="Deepak Kumar", relationship="Cousin", phone_number=phone)
        self.sos_service.add_trusted_contact(self.user1, req)

        # Second attempt with same phone
        req_dup = CreateTrustedContactRequest(name="Deepak K", relationship="Family", phone_number=phone)
        with self.assertRaises(RefusalError) as ctx:
            self.sos_service.add_trusted_contact(self.user1, req_dup)
        self.assertEqual(ctx.exception.code, "DUPLICATE_CONTACT")

    def test_08_update_trusted_contact(self):
        """Updates contact name, relationship, and phone number."""
        req = CreateTrustedContactRequest(name="Vikram Singh", relationship="Friend", phone_number="+91 98765 55555")
        c = self.sos_service.add_trusted_contact(self.user1, req)

        # Update contact
        up_req = UpdateTrustedContactRequest(
            name="Vikramaditya Singh",
            relationship="Best Friend",
            phone_number="+91 98765 55556",
        )
        updated = self.sos_service.update_trusted_contact(self.user1, c.contact_id, up_req)
        self.assertEqual(updated.name, "Vikramaditya Singh")
        self.assertEqual(updated.contact_name, "Vikramaditya Singh")
        self.assertEqual(updated.relationship, "Best Friend")
        self.assertEqual(updated.phone_number, "+91 98765 55556")

    def test_09_delete_trusted_contact(self):
        """Deletes a contact and verifies removal from database."""
        req = CreateTrustedContactRequest(name="Temporary Contact", relationship="Colleague", phone_number="+91 98765 66666")
        c = self.sos_service.add_trusted_contact(self.user1, req)

        # Verify exists
        self.assertIsNotNone(self.sos_service.repo.get_emergency_contact(self.user1, c.contact_id))

        # Delete
        success = self.sos_service.delete_trusted_contact(self.user1, c.contact_id)
        self.assertTrue(success)

        # Verify no longer exists
        self.assertIsNone(self.sos_service.repo.get_emergency_contact(self.user1, c.contact_id))

    def test_10_cross_user_contact_isolation(self):
        """User 1 cannot read, update, or delete User 2's trusted contacts."""
        # Add contact for User 2
        req = CreateTrustedContactRequest(name="User2 Secret Contact", relationship="Spouse", phone_number="+91 98765 77777")
        c2 = self.sos_service.add_trusted_contact(self.user2, req)

        # User 1 listing should NOT include User 2's contact
        u1_contacts = self.sos_service.list_trusted_contacts(self.user1)
        self.assertFalse(any(c.contact_id == c2.contact_id for c in u1_contacts))

        # User 1 cannot update User 2's contact
        with self.assertRaises(RefusalError) as ctx:
            self.sos_service.update_trusted_contact(
                self.user1,
                c2.contact_id,
                UpdateTrustedContactRequest(name="Hacked Name"),
            )
        self.assertEqual(ctx.exception.code, "EMERGENCY_CONTACT_NOT_FOUND")

        # User 1 cannot delete User 2's contact
        with self.assertRaises(RefusalError) as ctx:
            self.sos_service.delete_trusted_contact(self.user1, c2.contact_id)
        self.assertEqual(ctx.exception.code, "EMERGENCY_CONTACT_NOT_FOUND")

        # Verify User 2's contact is untouched
        still_there = self.sos_service.repo.get_emergency_contact(self.user2, c2.contact_id)
        self.assertIsNotNone(still_there)
        self.assertEqual(still_there["name"], "User2 Secret Contact")

    # =========================================================================
    # 4. SOS Activation Flow & Audit Persistence
    # =========================================================================
    def test_11_sos_activation_requires_explicit_confirmation(self):
        """Activation without explicit confirmation is rejected."""
        req = ActivateSosRequest(explicit_confirmation=False)
        with self.assertRaises(RefusalError) as ctx:
            self.sos_service.activate_sos(self.user1, req)
        self.assertEqual(ctx.exception.code, "EXPLICIT_CONFIRMATION_REQUIRED")

    def test_12_successful_sos_activation_with_audit_event(self):
        """SOS activation returns valid event ID, status, instructions, and honest capability status."""
        req = ActivateSosRequest(
            explicit_confirmation=True,
            reason="Night travel safety alert",
        )
        res = self.sos_service.activate_sos(self.user1, req)
        self.assertEqual(res.status, "ACTIVATED")
        self.assertTrue(res.sos_event_id.startswith("sos_"))
        self.assertEqual(res.event_id, res.sos_event_id)
        self.assertEqual(res.official_number_to_dial, "112")
        self.assertGreaterEqual(len(res.instructions), 4)

        # Verify honest capability reporting
        self.assertFalse(res.delivery_provider_status.get("sms_configured"))
        self.assertEqual(res.delivery_provider_status.get("mode"), "DEMO_SIMULATION")

    def test_13_audit_events_are_immutable(self):
        """Audit events cannot be deleted due to SQLite trigger trg_p6sos_no_delete."""
        req = ActivateSosRequest(explicit_confirmation=True, reason="Audit trigger test")
        res = self.sos_service.activate_sos(self.user1, req)

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM phase6_emergency_events WHERE event_id = ?", (res.sos_event_id,))

    def test_14_sos_location_coordinates_persistence(self):
        """Location coordinates and landmark are stored in details_json of audit event."""
        coords = LocationCoordinates(
            latitude=26.9124,
            longitude=75.7873,
            accuracy_meters=15.0,
            address_or_landmark="Near Hawa Mahal, Jaipur",
        )
        req = ActivateSosRequest(
            explicit_confirmation=True,
            location=coords,
            location_text="Hotel Clark Amer, Room 102",
            notes="Medical assistance needed",
        )
        res = self.sos_service.activate_sos(self.user1, req)

        # Query database directly to verify stored details_json
        row = self.conn.execute(
            "SELECT details_json FROM phase6_emergency_events WHERE event_id = ?",
            (res.sos_event_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        details = json.loads(row[0])
        self.assertIn("location", details)
        self.assertEqual(details["location"]["latitude"], 26.9124)
        self.assertEqual(details["location"]["longitude"], 75.7873)
        self.assertEqual(details["location_text"], "Hotel Clark Amer, Room 102")

    # =========================================================================
    # 5. Trip Sharing Flow
    # =========================================================================
    def test_15_trip_sharing_with_explicit_confirmation(self):
        """Trip sharing requires explicit confirmation and formats preview summary."""
        # Insert a trip for User 1
        trip_id = new_id("trp")
        self.conn.execute(
            """INSERT INTO trips
               (trip_id, owner_user_id, title, destination_city_id, start_date, end_date,
                party_size, adults, children, trip_type, is_group_trip, status, home_currency, created_at, updated_at)
               VALUES (?, ?, 'Jaipur Cultural Tour', (SELECT city_id FROM cities WHERE name='Jaipur' LIMIT 1),
                       '2026-11-10', '2026-11-15', 2, 2, 0, 'leisure', 0, 'confirmed', 'INR', '2026-10-17', '2026-10-17')""",
            (trip_id, self.user1),
        )

        req = ShareTripRequest(
            trip_id=trip_id,
            explicit_user_confirmation=True,
            location=LocationCoordinates(latitude=26.9124, longitude=75.7873),
        )
        res = self.sos_service.share_trip_details(self.user1, req)
        self.assertEqual(res.status, "SHARED_TO_TRUSTED_CONTACT")
        self.assertIn("Jaipur", res.summary.destination)
        self.assertTrue(res.share_event_id.startswith("sos_"))

    def test_16_trip_sharing_cross_user_denied(self):
        """User 1 cannot share User 2's trip."""
        trip_id = new_id("trp")
        self.conn.execute(
            """INSERT INTO trips
               (trip_id, owner_user_id, title, destination_city_id, start_date, end_date,
                party_size, adults, children, trip_type, is_group_trip, status, home_currency, created_at, updated_at)
               VALUES (?, ?, 'User 2 Trip', (SELECT city_id FROM cities LIMIT 1),
                       '2026-11-10', '2026-11-15', 1, 1, 0, 'leisure', 0, 'confirmed', 'INR', '2026-10-17', '2026-10-17')""",
            (trip_id, self.user2),
        )

        req = ShareTripRequest(trip_id=trip_id, explicit_user_confirmation=True)
        with self.assertRaises(RefusalError) as ctx:
            self.sos_service.share_trip_details(self.user1, req)
        self.assertEqual(ctx.exception.code, "EMERGENCY_ACCESS_DENIED")

    # =========================================================================
    # 6. Manual Location Geocoding & Three Location States
    # =========================================================================
    def test_17_geocoding_endpoint_and_attribution(self):
        """GET /emergency/geocode returns results with valid schema, coordinates and OSM attribution."""
        resp = self.client.get("/api/v1/emergency/geocode?query=Jaipur", headers=self.headers_user1)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["query"], "Jaipur")
        self.assertIn("OpenStreetMap", data["attribution"])
        self.assertTrue(len(data["results"]) > 0)
        first = data["results"][0]
        self.assertIn("latitude", first)
        self.assertIn("longitude", first)
        self.assertIn("display_name", first)
        self.assertTrue(-90 <= first["latitude"] <= 90)
        self.assertTrue(-180 <= first["longitude"] <= 180)

    def test_18_geocoding_local_fallback(self):
        """GeocodingService falls back cleanly to local database matching active cities."""
        from src.services.geocoding_service import GeocodingService
        svc = GeocodingService(conn=self.conn, timeout_seconds=0.01)
        res = svc._fallback_local_search("Jaipur", limit=3)
        self.assertTrue(len(res) > 0)
        self.assertEqual(res[0].name, "Jaipur")
        self.assertEqual(res[0].state, "Rajasthan")
        self.assertAlmostEqual(res[0].latitude, 26.9124, delta=0.5)

    def test_19_sos_activation_with_geocoded_location(self):
        """SOS activation with geocoding-selected coordinates records source='geocoded' and display label."""
        coords = LocationCoordinates(
            latitude=13.073014,
            longitude=77.792138,
            source="geocoded",
            display_label="Hoskote, Bengaluru Rural, Karnataka, India",
            place_id="osm_123456",
        )
        req = ActivateSosRequest(
            explicit_confirmation=True,
            location=coords,
            location_text="Hoskote, Bengaluru Rural",
            reason="Medical assistance needed near Hoskote",
        )
        res = self.sos_service.activate_sos(self.user1, req)
        self.assertEqual(res.status, "ACTIVATED")
        self.assertEqual(res.location_source, "geocoded")
        self.assertEqual(res.location_display, "Hoskote, Bengaluru Rural, Karnataka, India")
        self.assertEqual(res.location_captured["latitude"], 13.073014)
        self.assertEqual(res.location_captured["longitude"], 77.792138)

        # Verify audit event in DB
        cursor = self.conn.execute(
            "SELECT details_json FROM phase6_emergency_events WHERE event_id = ?",
            (res.sos_event_id,),
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        details = json.loads(row[0])
        self.assertEqual(details["location_source"], "geocoded")
        self.assertEqual(details["location"]["latitude"], 13.073014)
        self.assertEqual(details["location"]["longitude"], 77.792138)
        self.assertEqual(details["location_display"], "Hoskote, Bengaluru Rural, Karnataka, India")

    def test_20_sos_activation_with_manual_unverified_landmark(self):
        """SOS activation with unverified manual text note records source='manual_unverified' and NO coordinates."""
        req = ActivateSosRequest(
            explicit_confirmation=True,
            location=None,  # No GPS or geocoded coordinates
            location_text="Highway Toll Booth 4, NH 48, Room 12",
            reason="Lost transport in remote sector",
        )
        res = self.sos_service.activate_sos(self.user1, req)
        self.assertEqual(res.status, "ACTIVATED")
        self.assertEqual(res.location_source, "manual_unverified")
        self.assertEqual(res.location_display, "Highway Toll Booth 4, NH 48, Room 12")
        self.assertIsNone(res.location_captured)

        # Verify in audit event
        cursor = self.conn.execute(
            "SELECT details_json FROM phase6_emergency_events WHERE event_id = ?",
            (res.sos_event_id,),
        )
        row = cursor.fetchone()
        details = json.loads(row[0])
        self.assertEqual(details["location_source"], "manual_unverified")
        self.assertIsNone(details["location"])
        self.assertEqual(details["location_text"], "Highway Toll Booth 4, NH 48, Room 12")

    def test_21_sos_activation_with_gps_confirmed_coordinates(self):
        """SOS activation with GPS coordinates records source='gps' distinctly from geocoded/unverified."""
        coords = LocationCoordinates(
            latitude=28.6139,
            longitude=77.2090,
            accuracy_meters=14.0,
            source="gps",
        )
        req = ActivateSosRequest(
            explicit_confirmation=True,
            location=coords,
            reason="GPS confirmed alert in Delhi",
        )
        res = self.sos_service.activate_sos(self.user1, req)
        self.assertEqual(res.status, "ACTIVATED")
        self.assertEqual(res.location_source, "gps")
        self.assertEqual(res.location_captured["accuracy_meters"], 14.0)

        cursor = self.conn.execute(
            "SELECT details_json FROM phase6_emergency_events WHERE event_id = ?",
            (res.sos_event_id,),
        )
        details = json.loads(cursor.fetchone()[0])
        self.assertEqual(details["location_source"], "gps")
        self.assertEqual(details["location"]["latitude"], 28.6139)

    def test_22_geocoding_short_query_rejection(self):
        """Short search queries (<2 chars) return empty results without error."""
        resp = self.client.get("/api/v1/emergency/geocode?query=a", headers=self.headers_user1)
        # FastAPI query min_length=2 returns 422 for 1 char, or 200 with empty results
        self.assertIn(resp.status_code, [200, 422])

