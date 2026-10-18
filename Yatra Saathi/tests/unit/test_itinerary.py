"""Comprehensive unit and API tests for Yatra Phase 2A: Itinerary Foundation / Structured Trip Plan."""
from __future__ import annotations

import math
import sqlite3
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.core import human_tokens
from src.core.clock import FixedClock
from src.core.config import Settings
from src.contracts.codes import RefusalError
from src.main import create_app
from src.schemas.itinerary import (
    AccommodationStay,
    ActivityCategory,
    GenerateItineraryRequest,
    ItemSource,
    ItineraryActivity,
    ItineraryDay,
    ItineraryStatus,
    TransportSegment,
    TransportType,
    TripPlan,
    VALID_LIFECYCLE_TRANSITIONS,
)
from src.services import itinerary_service
from tests import support

HUMAN_SECRET = "a" * 64


class TestItineraryFoundation(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        self.conn = self.wc.raw()
        self.conn.row_factory = sqlite3.Row
        user_row = self.conn.execute("SELECT user_id FROM users WHERE status = 'active' LIMIT 1").fetchone()
        self.user_id = user_row["user_id"]
        other_row = self.conn.execute("SELECT user_id FROM users WHERE status = 'active' AND user_id != ? LIMIT 1", (self.user_id,)).fetchone()
        self.other_user_id = other_row["user_id"]

        self.settings = Settings.from_env({
            "APS_DB_PATH": self.wc.path,
            "APS_DB_ORIGINAL_PATH": support.original_path(),
            "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
            "HUMAN_TOKEN_SECRET": HUMAN_SECRET,
            "DEMO_LOGIN_USER_IDS": f"{self.user_id},{self.other_user_id}",
        })
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.client = TestClient(create_app(self.settings, clock=self.clock))
        self.token = human_tokens.issue(HUMAN_SECRET, self.user_id, now=self.clock.now())
        self.auth_headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.conn.close()
        self.wc.cleanup()
        support.assert_original_untouched()

    def _sample_valid_plan(self) -> TripPlan:
        return TripPlan(
            id="itn_test0001",
            title="Mumbai to Kolkata Discovery",
            origin="Mumbai",
            destination="Kolkata",
            start_date=date(2026, 10, 12),
            end_date=date(2026, 10, 16),
            travellers=5,
            currency="INR",
            budget="50000.00",
            total_estimated_cost="48000.00",
            total_authoritative_cost="45500.00",
            transport=[
                TransportSegment(
                    id="seg_01",
                    type=TransportType.FLIGHT,
                    origin="Mumbai",
                    origin_code="BOM",
                    destination="Kolkata",
                    dest_code="CCU",
                    carrier="IndiGo",
                    reference="6E-205",
                    departs_at="2026-10-12T08:00:00+05:30",
                    arrives_at="2026-10-12T10:45:00+05:30",
                    known_price="18500.00",
                    currency="INR",
                    origin_latitude=19.0886,
                    origin_longitude=72.8679,
                    dest_latitude=22.6547,
                    dest_longitude=88.4467,
                )
            ],
            accommodation=[
                AccommodationStay(
                    id="acc_01",
                    hotel_id=None,
                    hotel_name="The Oberoi Grand Kolkata",
                    room_name="Deluxe Room",
                    address="15 Jawaharlal Nehru Rd, Kolkata",
                    check_in_date=date(2026, 10, 12),
                    check_out_date=date(2026, 10, 16),
                    known_price="27000.00",
                    currency="INR",
                    latitude=22.5604,
                    longitude=88.3512,
                )
            ],
            days=[
                ItineraryDay(
                    date=date(2026, 10, 12),
                    day_number=1,
                    title="Arrival & Check-in",
                    activities=[
                        ItineraryActivity(
                            id="act_01",
                            title="Flight to Kolkata",
                            description="Direct morning flight from BOM to CCU",
                            start_time="08:00",
                            end_time="10:45",
                            location="Mumbai Airport",
                            latitude=19.0886,
                            longitude=72.8679,
                            authoritative_cost="18500.00",
                            currency="INR",
                            category=ActivityCategory.FLIGHT,
                            source=ItemSource.USER,
                        ),
                        ItineraryActivity(
                            id="act_02",
                            title="Check-in at Hotel",
                            description="Check in and unpack",
                            start_time="14:00",
                            end_time="15:00",
                            location="The Oberoi Grand",
                            latitude=22.5604,
                            longitude=88.3512,
                            authoritative_cost="27000.00",
                            currency="INR",
                            category=ActivityCategory.STAY,
                            source=ItemSource.USER,
                        ),
                    ],
                    locations=["Kolkata"],
                    notes="Rest after check-in",
                    estimated_cost="45500.00",
                ),
                ItineraryDay(
                    date=date(2026, 10, 13),
                    day_number=2,
                    title="Cultural Heritage Walk",
                    activities=[
                        ItineraryActivity(
                            id="act_03",
                            title="Victoria Memorial Visit",
                            description="Guided walk through Victoria Memorial gardens",
                            start_time="10:00",
                            end_time="12:30",
                            location="Victoria Memorial",
                            latitude=22.5448,
                            longitude=88.3426,
                            estimated_cost="500.00",
                            currency="INR",
                            category=ActivityCategory.CULTURE,
                            source=ItemSource.USER,
                        )
                    ],
                    locations=["Kolkata"],
                    estimated_cost="500.00",
                ),
            ],
            constraints={"destination_name": "Kolkata"},
            status=ItineraryStatus.DRAFT,
            version=1,
        )

    # 1. Valid TripPlan
    def test_valid_trip_plan_creation_and_validation(self):
        plan = self._sample_valid_plan()
        res = itinerary_service.validate_itinerary(plan, conn=self.conn)
        self.assertTrue(res.valid, res.errors)
        self.assertEqual(len(res.errors), 0)

    # 2. Invalid trip date range (end before start)
    def test_invalid_trip_date_range_rejected(self):
        with self.assertRaises(ValueError):
            TripPlan(
                id="itn_inv_dates",
                title="Invalid Dates",
                origin="Mumbai",
                destination="Kolkata",
                start_date=date(2026, 10, 16),
                end_date=date(2026, 10, 12),
                travellers=2,
                currency="INR",
            )

    # 3. Invalid itinerary day date (day outside trip dates)
    def test_invalid_itinerary_day_date_rejected(self):
        with self.assertRaises(ValueError):
            TripPlan(
                id="itn_inv_day",
                title="Invalid Day",
                origin="Mumbai",
                destination="Kolkata",
                start_date=date(2026, 10, 12),
                end_date=date(2026, 10, 16),
                travellers=2,
                currency="INR",
                days=[
                    ItineraryDay(
                        date=date(2026, 10, 20),  # Outside trip range
                        day_number=1,
                        title="Out of bounds day",
                    )
                ],
            )

    # 4. Invalid activity times (end before start)
    def test_invalid_activity_times_rejected(self):
        with self.assertRaises(ValueError):
            ItineraryActivity(
                id="act_bad_times",
                title="Time Warp",
                start_time="14:00",
                end_time="11:00",  # Before start_time
                currency="INR",
                category=ActivityCategory.ACTIVITY,
            )

    # 5. Invalid coordinates rejected
    def test_invalid_coordinates_rejected(self):
        for bad_lat in [91.0, -91.0, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                ItineraryActivity(
                    id="act_bad_lat",
                    title="Bad Lat",
                    latitude=bad_lat,
                    longitude=88.36,
                    currency="INR",
                )

        for bad_lng in [181.0, -181.0, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                ItineraryActivity(
                    id="act_bad_lng",
                    title="Bad Lng",
                    latitude=22.57,
                    longitude=bad_lng,
                    currency="INR",
                )

    # 6. Valid coordinates accepted
    def test_valid_coordinates_accepted(self):
        act = ItineraryActivity(
            id="act_coords",
            title="Valid Coordinates",
            latitude=22.572646,
            longitude=88.363895,
            currency="INR",
        )
        self.assertAlmostEqual(act.latitude, 22.572646)
        self.assertAlmostEqual(act.longitude, 88.363895)

    # 7. Valid money values
    def test_valid_money_values(self):
        plan = self._sample_valid_plan()
        self.assertEqual(plan.budget, "50000.00")
        self.assertEqual(plan.total_estimated_cost, "48000.00")
        self.assertEqual(plan.total_authoritative_cost, "45500.00")
        res = itinerary_service.validate_itinerary(plan, conn=self.conn)
        self.assertTrue(res.valid)

    # 8. Invalid money values rejected
    def test_invalid_money_values_rejected(self):
        for bad_money in ["50000.000", "-100", "50,000", "free", "abc"]:
            with self.assertRaises(ValidationError):
                TripPlan(
                    id="itn_bad_money",
                    title="Bad Money",
                    origin="Mumbai",
                    destination="Kolkata",
                    start_date=date(2026, 10, 12),
                    end_date=date(2026, 10, 16),
                    travellers=2,
                    currency="INR",
                    budget=bad_money,
                )

    # 9. Traveller validation
    def test_traveller_count_validation(self):
        with self.assertRaises(ValidationError):
            TripPlan(
                id="itn_bad_travellers",
                title="Bad Travellers",
                origin="Mumbai",
                destination="Kolkata",
                start_date=date(2026, 10, 12),
                end_date=date(2026, 10, 16),
                travellers=0,  # Invalid: ge=1 required
                currency="INR",
            )

    # 10. Itinerary lifecycle validation
    def test_itinerary_lifecycle_transition_validation(self):
        # draft -> planned: OK
        itinerary_service.validate_lifecycle_transition(ItineraryStatus.DRAFT, ItineraryStatus.PLANNED)
        # planned -> confirmed: OK
        itinerary_service.validate_lifecycle_transition(ItineraryStatus.PLANNED, ItineraryStatus.CONFIRMED)
        # confirmed -> cancelled: OK
        itinerary_service.validate_lifecycle_transition(ItineraryStatus.CONFIRMED, ItineraryStatus.CANCELLED)

        # cancelled -> confirmed: Refused
        with self.assertRaises(RefusalError) as ctx:
            itinerary_service.validate_lifecycle_transition(ItineraryStatus.CANCELLED, ItineraryStatus.CONFIRMED)
        self.assertEqual(ctx.exception.code, "INVALID_STATE")

    # 11. Transport reference validation
    def test_transport_reference_validation(self):
        plan = self._sample_valid_plan()
        plan.transport[0].reference = "far_nonexistent999"
        res = itinerary_service.validate_itinerary(plan, conn=self.conn)
        self.assertFalse(res.valid)
        self.assertTrue(any("not found in catalog" in e for e in res.errors))

    # 12. Accommodation reference validation
    def test_accommodation_reference_validation(self):
        plan = self._sample_valid_plan()
        plan.accommodation[0].hotel_id = "htl_nonexistent999"
        res = itinerary_service.validate_itinerary(plan, conn=self.conn)
        self.assertFalse(res.valid)
        self.assertTrue(any("not found in catalog" in e for e in res.errors))

    # 13. Ownership and API authorization
    def test_ownership_and_api_authorization(self):
        plan = self._sample_valid_plan()
        # Create draft via API
        r = self.client.post("/api/v1/itineraries", json=plan.model_dump(mode="json"), headers=self.auth_headers)
        self.assertEqual(r.status_code, 200, r.text)
        created = r.json()["data"]["itinerary"]
        itin_id = created["id"]

        # Fetch draft as owner
        r_get = self.client.get(f"/api/v1/itineraries/{itin_id}", headers=self.auth_headers)
        self.assertEqual(r_get.status_code, 200)

        # Login as another user and verify access is refused
        # Create temporary token for non-owner
        alien_token = human_tokens.issue(HUMAN_SECRET, self.other_user_id, now=self.clock.now())
        alien_headers = {"Authorization": f"Bearer {alien_token}"}
        r_alien = self.client.get(f"/api/v1/itineraries/{itin_id}", headers=alien_headers)
        self.assertEqual(r_alien.status_code, 403)
        self.assertEqual(r_alien.json()["refusal"]["code"], "SESSION_ACCESS_DENIED")

    # 14. Empty itinerary
    def test_empty_itinerary_handling(self):
        empty_plan = TripPlan(
            id="itn_empty",
            title="Empty Plan",
            origin="Mumbai",
            destination="Kolkata",
            start_date=date(2026, 10, 12),
            end_date=date(2026, 10, 16),
            travellers=2,
            currency="INR",
            days=[],
            transport=[],
            accommodation=[],
        )
        res = itinerary_service.validate_itinerary(empty_plan, conn=self.conn)
        self.assertTrue(res.valid)
        self.assertEqual(len(empty_plan.days), 0)

    # 15. Multiple itinerary days
    def test_multiple_itinerary_days(self):
        plan = self._sample_valid_plan()
        self.assertEqual(len(plan.days), 2)
        self.assertEqual(plan.days[0].day_number, 1)
        self.assertEqual(plan.days[1].day_number, 2)

    # 16. Multiple activities per day
    def test_multiple_activities_per_day(self):
        plan = self._sample_valid_plan()
        day1 = plan.days[0]
        self.assertEqual(len(day1.activities), 2)
        self.assertEqual(day1.activities[0].category, ActivityCategory.FLIGHT)
        self.assertEqual(day1.activities[1].category, ActivityCategory.STAY)

    # 17. Serialization and deserialization roundtrip
    def test_serialization_and_deserialization_roundtrip(self):
        plan = self._sample_valid_plan()
        data = plan.model_dump(mode="json")
        restored = TripPlan.model_validate(data)
        self.assertEqual(plan.id, restored.id)
        self.assertEqual(plan.start_date, restored.start_date)
        self.assertEqual(plan.end_date, restored.end_date)
        self.assertEqual(len(plan.days), len(restored.days))
        self.assertEqual(len(plan.transport), len(restored.transport))
        self.assertEqual(len(plan.accommodation), len(restored.accommodation))

    # 18. AI contract schema validation
    def test_ai_contract_schema_validation(self):
        gen_req = GenerateItineraryRequest(
            session_id="agt_demo123",
            origin="Mumbai",
            destination="Kolkata",
            start_date=date(2026, 10, 12),
            end_date=date(2026, 10, 16),
            travellers=5,
            currency="INR",
            budget="50000.00",
            preferences="cultural heritage, central stay",
        )
        self.assertEqual(gen_req.travellers, 5)
        self.assertEqual(gen_req.currency, "INR")

        # Invalid date order rejected by AI contract
        with self.assertRaises(ValueError):
            GenerateItineraryRequest(
                origin="Mumbai",
                destination="Kolkata",
                start_date=date(2026, 10, 16),
                end_date=date(2026, 10, 12),
                travellers=2,
                currency="INR",
            )

    # 19. Existing map behavior remains functional
    def test_existing_map_cities_endpoint_remains_functional(self):
        resp = self.client.get("/api/v1/search/cities")
        self.assertEqual(resp.status_code, 200)
        cities = resp.json()["data"]["cities"]
        self.assertEqual(len(cities), 60)

    # 20. Existing travel search remains functional
    def test_existing_travel_search_remains_functional(self):
        resp = self.client.get("/api/v1/currencies")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(c["code"] == "INR" for c in resp.json()["data"]["currencies"]))
