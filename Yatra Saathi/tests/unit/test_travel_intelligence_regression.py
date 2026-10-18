"""
Regression test suite for Travel Intelligence & Experience corrections:
- Real geographic coordinates & airport routing
- Distinct flight offers, deduplication, and single-offer catalog notice
- Day-by-day dynamic itinerary generation with flight arrival buffers and meal slots
- Booking review token generation, session plan resolution, and authentication integrity
"""
from datetime import date
import sqlite3
import pytest

from tests import support
from src.core.clock import SystemClock
from src.services.itinerary_service import build_daily_schedule, save_itinerary
from src.services.comparison_service import compare_travel_options
from src.schemas.comparison import CompareTravelOptionsRequest
from src.schemas.itinerary import (
    TripPlan,
    ItineraryDay,
    ItineraryActivity,
    ActivityCategory,
    ItemSource,
    TransportSegment,
    AccommodationStay,
)
from src.services.phase5_booking_service import create_booking_review
from src.schemas.booking import BookingReviewRequest, BookingTravellerInfo


@pytest.fixture
def conn():
    support.assert_original_untouched()
    wc = support.WorkingCopy()
    c = wc.raw()
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_flight_comparison_distinct_offers_and_catalog_notice(conn):
    """Verifies that flight options are deduplicated and catalog notices are generated when only 1 flight exists."""
    clock = SystemClock()
    user_row = conn.execute("SELECT user_id FROM users WHERE status = 'active' LIMIT 1").fetchone()
    user_id = user_row["user_id"]

    req = CompareTravelOptionsRequest(
        origin="Mumbai",
        destination="Lucknow",
        start_date="2026-11-16",
        end_date="2026-11-19",
        travellers=2,
        budget="45000",
        currency="INR",
    )
    resp = compare_travel_options(conn, clock, user_id, req)

    # Must return options
    assert len(resp.options) > 0

    # Flight options must be distinct
    flight_ids = [f.get("outbound", {}).get("flight_number") for f in resp.flight_options if f.get("outbound")]
    assert len(flight_ids) == len(set(flight_ids)), "Duplicate flight options found!"

    # Distinct flight count must match
    assert resp.distinct_flight_count == len(resp.flight_options)

    # For Mumbai -> Lucknow in APS-01 catalog, only 1 outbound flight (AC-5550) exists
    if resp.distinct_flight_count == 1:
        assert resp.flight_catalog_notice is not None
        assert "Only one suitable flight is currently available" in resp.flight_catalog_notice


def test_itinerary_arrival_buffers_and_meal_slots():
    """Verifies arrival timing awareness, airport transit buffers, luggage drop, and meal planning."""
    # Outbound flight arriving at 11:09
    transport = [
        TransportSegment(
            type="flight",
            origin="Mumbai",
            origin_code="BOM",
            destination="Lucknow",
            dest_code="LKO",
            carrier="Air Canada",
            reference="AC-5550",
            departs_at="2026-11-16T08:50:00",
            arrives_at="2026-11-16T11:09:00",
            currency="INR",
        ),
        TransportSegment(
            type="flight",
            origin="Lucknow",
            origin_code="LKO",
            destination="Mumbai",
            dest_code="BOM",
            carrier="Air India",
            reference="AI-8346",
            departs_at="2026-11-19T09:40:00",
            arrives_at="2026-11-19T12:16:00",
            currency="INR",
        )
    ]

    accommodation = AccommodationStay(
        hotel_id="htl_001",
        hotel_name="Clarks Avadh Lucknow",
        address="8 Mahatma Gandhi Marg",
        check_in_date="2026-11-16",
        check_out_date="2026-11-19",
        currency="INR",
    )

    candidate_pois = [
        {"activity_id": "poi_1", "name": "Bara Imambara", "category": "culture", "latitude": 26.8689, "longitude": 80.9128},
        {"activity_id": "poi_2", "name": "Rumi Darwaza", "category": "culture", "latitude": 26.8710, "longitude": 80.9117},
        {"activity_id": "poi_3", "name": "Hazratganj Market", "category": "shopping", "latitude": 26.8520, "longitude": 80.9470},
    ]

    days = build_daily_schedule(
        candidate_pois=candidate_pois,
        start_date=date(2026, 11, 16),
        end_date=date(2026, 11, 19),
        destination="Lucknow",
        currency="INR",
        transport_info=transport,
        hotel_info=accommodation,
    )

    # 4 days total for 16-19 Nov
    assert len(days) == 4

    day1 = days[0]
    titles = [a.title for a in day1.activities]

    # Day 1 must have arrival at Lucknow Airport
    assert any("Arrival" in t for t in titles)
    # Day 1 must have transit from airport to hotel
    assert any("airport exit" in t.lower() or "transfer" in t.lower() for t in titles)
    # Day 1 must have hotel check-in / luggage drop
    assert any("check-in" in t.lower() or "luggage" in t.lower() for t in titles)
    # Day 1 must have lunch
    assert any("lunch" in t.lower() for t in titles)
    # Day 1 must have dinner
    assert any("dinner" in t.lower() for t in titles)

    # Verify no overlapping start/end times in Day 1
    for act in day1.activities:
        if act.start_time and act.end_time:
            start_parts = [int(p) for p in act.start_time.split(":")]
            end_parts = [int(p) for p in act.end_time.split(":")]
            start_m = start_parts[0] * 60 + start_parts[1]
            end_m = end_parts[0] * 60 + end_parts[1]
            assert end_m > start_m, f"Activity {act.title} has invalid duration: {act.start_time} -> {act.end_time}"


def test_itinerary_departure_day_schedule():
    """Verifies that departure day accounts for checkout, farewell lunch/buffer, and airport transfer."""
    transport = [
        TransportSegment(
            type="flight",
            origin="Lucknow",
            origin_code="LKO",
            destination="Mumbai",
            dest_code="BOM",
            carrier="Air India",
            reference="AI-8346",
            departs_at="2026-11-19T18:00:00",
            arrives_at="2026-11-19T20:30:00",
            currency="INR",
        )
    ]
    accommodation = AccommodationStay(
        hotel_id="htl_001",
        hotel_name="Clarks Avadh Lucknow",
        address="8 Mahatma Gandhi Marg",
        check_in_date="2026-11-16",
        check_out_date="2026-11-19",
        currency="INR",
    )

    days = build_daily_schedule(
        candidate_pois=[],
        start_date=date(2026, 11, 16),
        end_date=date(2026, 11, 19),
        destination="Lucknow",
        currency="INR",
        transport_info=transport,
        hotel_info=accommodation,
    )

    dep_day = days[-1]
    titles = [a.title for a in dep_day.activities]

    # Checkout must happen
    assert any("check-out" in t.lower() for t in titles)
    # Transfer to airport must happen
    assert any("Transfer to" in t and "Airport" in t for t in titles)
    # Flight boarding must happen
    assert any("Flight" in t or "Airport" in t for t in titles)


def test_booking_review_token_generation_and_integrity(conn):
    """Verifies authoritative booking review generation with recalculated totals."""
    clock = SystemClock()
    user_row = conn.execute("SELECT user_id FROM users WHERE status = 'active' LIMIT 1").fetchone()
    user_id = user_row["user_id"]

    # Retrieve an authoritative hotel from catalog
    htl = conn.execute("SELECT hotel_id, name, city_id FROM hotels LIMIT 1").fetchone()
    hotel_id = htl["hotel_id"]
    hotel_name = htl["name"]
    city_row = conn.execute("SELECT name FROM cities WHERE city_id = ?", (htl["city_id"],)).fetchone()
    dest_name = city_row["name"] if city_row else "Lucknow"

    # Create a real test itinerary first to test booking review
    plan = TripPlan(
        id="itn_reg_test_01",
        title=f"Trip to {dest_name}",
        destination=dest_name,
        origin="Mumbai",
        start_date=date(2026, 11, 16),
        end_date=date(2026, 11, 19),
        travellers=2,
        currency="INR",
        total_authoritative_cost="42000.00",
        days=[
            ItineraryDay(
                date=date(2026, 11, 16),
                day_number=1,
                title=f"Arrival in {dest_name}",
                activities=[
                    ItineraryActivity(
                        id="act_01",
                        title="Airport Arrival",
                        start_time="11:00",
                        end_time="11:30",
                        currency="INR",
                        category=ActivityCategory.FLIGHT,
                        source=ItemSource.USER,
                    )
                ]
            )
        ],
        transport=[],
        accommodation=[
            AccommodationStay(
                hotel_id=hotel_id,
                hotel_name=hotel_name,
                check_in_date="2026-11-16",
                check_out_date="2026-11-19",
                known_price="18000.00",
                currency="INR",
            )
        ],
    )
    persisted = save_itinerary(conn, user_id, plan)

    body = BookingReviewRequest(
        itinerary_id=persisted.id,
        itinerary_version=persisted.version,
        travellers=[
            BookingTravellerInfo(display_name="Primary Guest", traveller_role="adult"),
            BookingTravellerInfo(display_name="Second Guest", traveller_role="adult"),
        ]
    )

    review = create_booking_review(conn, clock, user_id, body)

    assert review.review_token.startswith("rev_")
    assert review.authoritative_total != ""
    assert review.traveller_count == 2
    assert len(review.travellers) == 2
    assert "DEMO" in review.demo_label
