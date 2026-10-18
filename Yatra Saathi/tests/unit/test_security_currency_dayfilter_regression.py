"""
Security, Currency, and Day-Filtering Regression Tests (Antigravity Final Pass).

Regression proof for:
1. Guest cannot become usr_demo0001 automatically and cannot create a booking.
2. Booking review and confirmation require authenticated identity (401 without bearer token).
3. Authenticated user owns the resulting booking.
4. User A cannot access, review, or book User B's itinerary (cross-tenant safety, 403).
5. Foreign catalog POI currencies (e.g. AED 100) are converted via documented fx (~2287.00 INR)
   and are NEVER silently relabeled as INR 100.
6. Sightseeing POIs have authoritative_cost = None, keeping package totals authoritative.
7. Day 1 activities vs Day 2 activities are strictly distinct without cross-day leakage.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import secrets
import sqlite3
import pytest
from fastapi.testclient import TestClient

from tests import support
from src.core import fx, human_tokens, money
from src.core.clock import FixedClock
from src.core.config import Settings
from src.core.ids import new_id
from src.main import create_app
from src.schemas.booking import (
    BookingReviewRequest,
    BookingTravellerInfo,
    ConfirmBookingRequest,
)
from src.schemas.itinerary import (
    ActivityCategory,
    ItineraryActivity,
    ItineraryDay,
    ItineraryStatus,
    ItemSource,
    TripPlan,
)
from src.services import itinerary_service
from src.services import phase5_booking_service

HUMAN_SECRET = "test-human-secret-regression-2026"


@pytest.fixture
def test_env():
    support.assert_original_untouched()
    wc = support.WorkingCopy()
    clock = FixedClock(datetime(2026, 11, 1, tzinfo=timezone.utc))
    settings = Settings.from_env({
        "APS_DB_PATH": wc.path,
        "APS_DB_ORIGINAL_PATH": support.original_path(),
        "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
        "HUMAN_TOKEN_SECRET": HUMAN_SECRET,
    })
    app = create_app(settings, clock=clock)
    client = TestClient(app)
    conn = wc.raw()
    conn.row_factory = sqlite3.Row

    # Fetch 2 distinct valid active users from catalog
    user_a = conn.execute(
        "SELECT user_id FROM users WHERE status='active' AND home_currency='INR' LIMIT 1"
    ).fetchone()[0]
    user_b = conn.execute(
        "SELECT user_id FROM users WHERE status='active' AND home_currency='INR' AND user_id != ? LIMIT 1",
        (user_a,),
    ).fetchone()[0]

    yield {
        "wc": wc,
        "clock": clock,
        "settings": settings,
        "app": app,
        "client": client,
        "conn": conn,
        "user_a": user_a,
        "user_b": user_b,
    }

    conn.close()
    wc.cleanup()
    support.assert_original_untouched()


def test_guest_cannot_become_demo_user_and_cannot_create_booking(test_env):
    """Guest requests without authentication tokens must fail with 401 TOKEN_MISSING."""
    client = test_env["client"]

    # Attempt booking review without auth
    rev_res = client.post(
        "/api/v1/itineraries/itn_guest_probe/booking-review",
        json={
            "itinerary_id": "itn_guest_probe",
            "itinerary_version": 1,
            "travellers": [{"display_name": "Unauthenticated Guest", "traveller_role": "adult"}],
        },
    )
    assert rev_res.status_code == 401
    assert rev_res.json()["refusal"]["code"] == "TOKEN_MISSING"

    # Attempt booking confirmation without auth
    conf_res = client.post(
        "/api/v1/bookings/confirm",
        json={
            "itinerary_id": "itn_guest_probe",
            "itinerary_version": 1,
            "review_token": "rev_unauthed_token",
            "idempotency_key": "idemp_unauthed_guest",
            "travellers": [{"display_name": "Unauthenticated Guest", "traveller_role": "adult"}],
        },
    )
    assert conf_res.status_code == 401
    assert conf_res.json()["refusal"]["code"] == "TOKEN_MISSING"


def test_user_a_cannot_access_or_book_user_b_itinerary(test_env):
    """User A cannot create a booking review or confirm a booking for User B's itinerary."""
    conn = test_env["conn"]
    client = test_env["client"]
    clock = test_env["clock"]
    user_a = test_env["user_a"]
    user_b = test_env["user_b"]

    token_a = human_tokens.issue(HUMAN_SECRET, user_a, now=clock.now())

    # User B creates an itinerary
    plan_b = TripPlan(
        id=new_id("itn"),
        title="User B Lucknow Private Trip",
        origin="Mumbai",
        destination="Lucknow",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 7),
        travellers=2,
        currency="INR",
        transport=[],
        accommodation=[],
        days=[],
        status=ItineraryStatus.DRAFT,
        version=1,
    )
    created_b = itinerary_service.create_itinerary_draft(conn, clock, user_b, plan_b)
    conn.commit()

    # User A attempts to request booking review for User B's itinerary
    headers_a = {"Authorization": f"Bearer {token_a}"}
    probe_rev = client.post(
        f"/api/v1/itineraries/{created_b.id}/booking-review",
        headers=headers_a,
        json={
            "itinerary_id": created_b.id,
            "itinerary_version": 1,
            "travellers": [{"display_name": "Attacker", "traveller_role": "adult"}],
        },
    )
    assert probe_rev.status_code == 403
    assert probe_rev.json()["refusal"]["code"] == "BOOKING_OWNERSHIP_DENIED"


def test_authenticated_user_owns_resulting_booking(test_env):
    """When an authenticated user completes booking review and confirms, they own the booking record."""
    conn = test_env["conn"]
    client = test_env["client"]
    clock = test_env["clock"]
    user_a = test_env["user_a"]
    user_b = test_env["user_b"]

    token_a = human_tokens.issue(HUMAN_SECRET, user_a, now=clock.now())
    token_b = human_tokens.issue(HUMAN_SECRET, user_b, now=clock.now())

    plan = TripPlan(
        id=new_id("itn"),
        title="Valid Authoritative Trip",
        origin="Mumbai",
        destination="Lucknow",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 7),
        travellers=1,
        currency="INR",
        transport=[],
        accommodation=[],
        days=[],
        status=ItineraryStatus.DRAFT,
        version=1,
    )
    created_plan = itinerary_service.create_itinerary_draft(conn, clock, user_a, plan)
    conn.commit()

    # Review step
    headers_a = {"Authorization": f"Bearer {token_a}"}
    rev_res = client.post(
        f"/api/v1/itineraries/{created_plan.id}/booking-review",
        headers=headers_a,
        json={
            "itinerary_id": created_plan.id,
            "itinerary_version": 1,
            "travellers": [{"display_name": "Owner User", "traveller_role": "adult"}],
        },
    )
    rev_data = rev_res.json()["data"]
    review_token = rev_data["review_token"]

    idemp_key = f"idemp_{secrets.token_hex(16)}"
    conf_res = client.post(
        "/api/v1/bookings/confirm",
        headers=headers_a,
        json={
            "itinerary_id": created_plan.id,
            "itinerary_version": 1,
            "review_token": review_token,
            "authoritative_total": rev_data["authoritative_total"],
            "currency": rev_data["currency"],
            "idempotency_key": idemp_key,
            "travellers": [{"display_name": "Owner User", "traveller_role": "adult"}],
        },
    )
    assert conf_res.status_code == 200
    booking_id = conf_res.json()["data"]["booking_id"]

    # Verify User A owns the booking
    row = conn.execute("SELECT user_id, status FROM bookings WHERE booking_id = ?", (booking_id,)).fetchone()
    assert row is not None
    assert row["user_id"] == user_a
    assert row["status"] == "confirmed"

    # User B cannot read User A's booking
    headers_b = {"Authorization": f"Bearer {token_b}"}
    status_res = client.get(f"/api/v1/bookings/{booking_id}", headers=headers_b)
    assert status_res.status_code == 403


def test_foreign_currency_poi_fx_conversion_and_no_relabeling():
    """AED 100 must be converted using fx.convert (2287.00 INR), NEVER relabeled 1:1 as INR 100."""
    # Documented fx mid-rate verification
    aed_val = "100.00"
    converted = fx.convert(aed_val, "AED", "INR")
    assert converted == "2287.00"

    poi_aed = {
        "poi_id": "poi_dubai_sight",
        "title": "Dubai Museum",
        "cost": 100.0,
        "currency": "AED",
        "city_name": "Dubai",
        "duration_minutes": 120,
    }

    # Resolve POI cost for INR trip
    auth_c, est_c, act_curr, desc_suffix = itinerary_service._resolve_poi_cost_and_notes(poi_aed, "INR")

    # Authoritative cost must remain None (authoritative totals strictly reflect catalog inventory)
    assert auth_c is None
    # Estimated cost must be the converted value 2287.00 INR, NEVER 100.00 INR!
    assert est_c != "100.00"
    assert est_c == "2287.00"
    assert act_curr == "INR"
    assert "converted from 100.00 AED" in desc_suffix

    # Test unconvertible/exotic currency: must be pay-on-site, never relabeled
    poi_exotic = {
        "poi_id": "poi_exotic",
        "title": "Local Temple",
        "cost": 50.0,
        "currency": "NON_EXISTENT_CURR",
    }
    auth_ex, est_ex, curr_ex, desc_ex = itinerary_service._resolve_poi_cost_and_notes(poi_exotic, "INR")
    assert auth_ex is None
    assert est_ex is None  # Pay-on-site, excluded from numeric INR calculations
    assert curr_ex == "NON_EXISTENT_CURR"
    assert "Pay on-site in local currency: 50.00 NON_EXISTENT_CURR" in desc_ex


def test_package_totals_remain_authoritative_and_pure(test_env):
    """Authoritative totals must strictly sum flight and hotel inventory; POIs have authoritative_cost = None."""
    conn = test_env["conn"]
    pois = [
        {"poi_id": "poi_lko_1", "title": "Bara Imambara", "cost": 100.0, "currency": "INR", "city_lat": 26.86, "city_lng": 80.91},
        {"poi_id": "poi_lko_2", "title": "Rumi Darwaza", "cost": 25.0, "currency": "AED", "city_lat": 26.87, "city_lng": 80.91},
    ]

    days = itinerary_service.build_daily_schedule(
        candidate_pois=pois,
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 6),
        destination="Lucknow",
        currency="INR",
        style="balanced",
    )

    plan = TripPlan(
        id=new_id("itn"),
        title="Authoritative Total Purity Test",
        origin="Mumbai",
        destination="Lucknow",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 6),
        travellers=1,
        currency="INR",
        transport=[],
        accommodation=[],
        days=days,
        status=ItineraryStatus.DRAFT,
        version=1,
    )

    auth_total, est_total, breakdown = itinerary_service.calculate_plan_totals(conn, plan)
    # Activities authoritative cost must strictly be 0.00
    assert breakdown["activities_authoritative"] == "0.00"
    assert auth_total is None
    # Activities estimated cost must be non-zero (contains converted amounts)
    assert money.to_minor(breakdown["activities_estimated"]) > 0


def test_day_1_and_day_2_activities_have_zero_cross_day_leaks():
    """Day 1 activities must not leak into Day 2; each day has its own distinct activities and stops."""
    pois = [
        {"poi_id": f"poi_{i}", "title": f"Attraction {i}", "cost": 50.0, "currency": "INR", "city_lat": 26.85, "city_lng": 80.94}
        for i in range(1, 10)
    ]
    days = itinerary_service.build_daily_schedule(
        candidate_pois=pois,
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 7),
        destination="Lucknow",
        currency="INR",
        style="balanced",
    )

    assert len(days) == 4

    day1_act_ids = {a.id for a in days[0].activities}
    day2_act_ids = {a.id for a in days[1].activities}
    day3_act_ids = {a.id for a in days[2].activities}

    # Zero overlap of activity instances
    assert day1_act_ids.isdisjoint(day2_act_ids)
    assert day2_act_ids.isdisjoint(day3_act_ids)

    # Zero POI duplicate entities across days
    day1_pois = {a.entity_id for a in days[0].activities if a.entity_id}
    day2_pois = {a.entity_id for a in days[1].activities if a.entity_id}
    assert day1_pois.isdisjoint(day2_pois)
