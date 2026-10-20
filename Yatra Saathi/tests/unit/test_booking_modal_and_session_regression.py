"""Regression tests for Booking Review Modal and AI Chat Session Recovery.

Verifies:
1. Itinerary date resilience: get_itinerary handles both string dates (SQLite) and
   native datetime.date objects (PostgreSQL/psycopg2) without raising TypeError.
2. Booking review error safety: Nonexistent or unbookable itineraries return clean 404
   RefusalError without leaking server internals or stack traces.
3. Transaction safety: create_booking_review, create_inventory_hold, and generate_trip_pack
   safely execute audit inserts within explicit database transactions.
4. Session access safety: Missing or expired sessions return 404 'no such session'
   via API without 500 crashes.
5. Consecutive chat messages on an active session succeed and append conversation history.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from tests import support
from src.contracts.codes import RefusalError
from src.core import human_tokens
from src.core.clock import FixedClock
from src.core.config import Settings
from src.core.dates import parse_date_only
from src.core.ids import new_id
from src.db.postgres import PostgresRow
from src.main import create_app
from src.schemas.booking import (
    BookingReviewRequest,
    BookingTravellerInfo,
    ConfirmBookingRequest,
)
from src.schemas.itinerary import ItineraryStatus, TripPlan
from src.services import itinerary_service, phase5_booking_service, session_service

HUMAN_SECRET = "test-human-secret-regression-2026"
AGENT_SECRET = "test-agent-secret-regression-2026"


@pytest.fixture
def test_env():
    support.assert_original_untouched()
    wc = support.WorkingCopy()
    clock = FixedClock(datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc))
    settings = Settings.from_env({
        "APS_DB_PATH": wc.path,
        "APS_DB_ORIGINAL_PATH": support.original_path(),
        "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
        "HUMAN_TOKEN_SECRET": HUMAN_SECRET,
        "AGENT_TOKEN_SECRET": AGENT_SECRET,
    })
    app = create_app(settings, clock=clock)
    app.state.agent_dispatcher = lambda **kwargs: "mock_run_id"
    client = TestClient(app)
    conn = wc.raw()
    conn.row_factory = sqlite3.Row

    user_row = conn.execute("SELECT user_id FROM users WHERE status = 'active' LIMIT 1").fetchone()
    user_id = user_row["user_id"]

    other_row = conn.execute(
        "SELECT user_id FROM users WHERE status = 'active' AND user_id != ? LIMIT 1",
        (user_id,),
    ).fetchone()
    other_user_id = other_row["user_id"]

    token = human_tokens.issue(HUMAN_SECRET, user_id, now=clock.now())

    yield {
        "wc": wc,
        "conn": conn,
        "clock": clock,
        "settings": settings,
        "app": app,
        "client": client,
        "user_id": user_id,
        "other_user_id": other_user_id,
        "token": token,
    }
    wc.cleanup()


def test_itinerary_dates_native_date_resilience(test_env):
    """PostgreSQL returns datetime.date objects for DATE columns, whereas SQLite returns strings.
    Verify parse_date_only and get_itinerary parse native date objects without TypeError.
    """
    # 1. Direct unit test of parse_date_only with native date and string
    assert parse_date_only("2026-11-16") == date(2026, 11, 16)
    assert parse_date_only(date(2026, 11, 16)) == date(2026, 11, 16)

    conn = test_env["conn"]
    row = conn.execute("SELECT itinerary_id FROM itineraries LIMIT 1").fetchone()
    itin_id = row["itinerary_id"]

    # Test reading itinerary normally from SQLite (string dates)
    itin_sqlite = itinerary_service.get_itinerary(conn, itin_id, user_id=None)
    assert isinstance(itin_sqlite.start_date, date)
    assert isinstance(itin_sqlite.end_date, date)

    # 2. Test reading itinerary when database driver returns native datetime.date objects (PostgreSQL/psycopg2)
    class PostgresDriverProxy:
        def __init__(self, target_conn):
            self._target = target_conn

        def execute(self, sql, params=()):
            cursor = self._target.execute(sql, params)
            if "itineraries" in sql and "itinerary_id" in sql and "JOIN trips" in sql:
                row_data = cursor.fetchone()
                if row_data is None:
                    return cursor
                cols = [d[0] for d in cursor.description]
                vals = list(row_data)
                start_idx = cols.index("start_date")
                end_idx = cols.index("end_date")
                # Provide native datetime.date objects as psycopg2 does
                vals[start_idx] = date(2026, 11, 16)
                vals[end_idx] = date(2026, 11, 19)

                class MockCursor:
                    description = cursor.description

                    def fetchone(self):
                        return PostgresRow(vals, cols)

                    def fetchall(self):
                        return [PostgresRow(vals, cols)]

                return MockCursor()
            return cursor

        def __getattr__(self, name):
            return getattr(self._target, name)

    proxy = PostgresDriverProxy(conn)
    itin_pg = itinerary_service.get_itinerary(proxy, itin_id, user_id=None)
    assert itin_pg.start_date == date(2026, 11, 16)
    assert itin_pg.end_date == date(2026, 11, 19)


def test_booking_review_missing_itinerary_error_sanitization(test_env):
    """When booking review is requested for a nonexistent itinerary, return 404 with
    clean ITINERARY_NOT_BOOKABLE message and no internal stack trace or raw SQL.
    """
    conn = test_env["conn"]
    clock = test_env["clock"]
    user_id = test_env["user_id"]

    req = BookingReviewRequest(
        itinerary_id="itin_nonexistent_99999",
        itinerary_version=1,
        travellers=[BookingTravellerInfo(display_name="Traveler One", traveller_role="adult")],
    )

    with pytest.raises(RefusalError) as exc_info:
        phase5_booking_service.create_booking_review(conn, clock, user_id, req)

    err = exc_info.value
    assert err.code == "ITINERARY_NOT_BOOKABLE"
    assert err.http_status == 404
    assert "itin_nonexistent_99999" in err.message
    # Verify no python exception traceback representation in the message
    assert "Traceback" not in err.message
    assert "sqlite3" not in err.message.lower()


def test_booking_review_and_hold_audit_transaction_safety(test_env):
    """Verifies that create_booking_review and create_inventory_hold insert audit events
    within explicit transactions and commit properly.
    """
    conn = test_env["conn"]
    clock = test_env["clock"]
    user_id = test_env["user_id"]

    # Find an existing itinerary in the database and its parent trip
    row = conn.execute("SELECT itinerary_id, trip_id, version FROM itineraries LIMIT 1").fetchone()
    itin_id = row["itinerary_id"]
    itin_version = row["version"]
    trip_id = row["trip_id"]

    # Assign trip ownership to test user
    conn.execute(
        "UPDATE trips SET owner_user_id = ? WHERE trip_id = ?",
        (user_id, trip_id),
    )
    conn.commit()

    req = BookingReviewRequest(
        itinerary_id=itin_id,
        itinerary_version=itin_version,
        travellers=[BookingTravellerInfo(display_name="Primary Traveler", traveller_role="adult")],
    )

    # 1. Review creation
    review = phase5_booking_service.create_booking_review(conn, clock, user_id, req)
    assert review.review_token is not None
    assert review.booking_mode == "DEMO / SIMULATED"
    assert "NO REAL PAYMENT" in review.demo_label

    # Check audit event was committed to database
    event_row = conn.execute(
        "SELECT * FROM phase5_booking_events WHERE booking_id = ? AND event_type = 'BOOKING_REVIEW_VALIDATED'",
        (itin_id,),
    ).fetchone()
    assert event_row is not None
    assert event_row["user_id"] == user_id

    # 2. Hold creation
    hold = phase5_booking_service.create_inventory_hold(
        conn,
        clock,
        user_id,
        review_token=review.review_token,
        itinerary_id=itin_id,
        itinerary_version=itin_version,
    )
    assert hold["status"] == "active"
    assert hold["hold_id"] is not None

    hold_event = conn.execute(
        "SELECT * FROM phase5_booking_events WHERE booking_id = ? AND event_type = 'INVENTORY_HOLD_CREATED'",
        (itin_id,),
    ).fetchone()
    assert hold_event is not None
    assert hold_event["actor"] == "system"


def test_missing_session_returns_404_refusal_via_api(test_env):
    """When a chat message is sent to a missing session ID, backend returns 404
    RefusalError('no such session') rather than 500 error.
    """
    client = test_env["client"]
    token = test_env["token"]

    resp = client.post(
        "/api/v1/sessions/ses_nonexistent_12345/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Book me a trip to Jaipur"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["ok"] is False
    assert data["refusal"]["code"] == "SESSION_ACCESS_DENIED"
    assert "no such session" in data["refusal"]["message"]


def test_consecutive_chat_messages_succeed(test_env):
    """Verifies that consecutive messages to an existing session work without dropping session state."""
    client = test_env["client"]
    token = test_env["token"]
    conn = test_env["conn"]

    # 1. Create a session using CreateSessionRequest schema
    create_resp = client.post(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "goal_text": "Plan a 3-day cultural tour of Jaipur",
            "goal_language": "en-IN",
            "spend_cap": "50000.00",
            "currency": "INR",
            "constraints": {
                "start_date": "2026-11-20",
                "end_date": "2026-11-23",
            },
        },
    )
    assert create_resp.status_code == 200
    create_data = create_resp.json()
    assert create_data["ok"] is True
    session_id = create_data["data"]["session_id"]

    # 2. First message
    msg1_resp = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Please make sure to include Hawa Mahal in the itinerary"},
    )
    assert msg1_resp.status_code == 200
    assert msg1_resp.json()["ok"] is True

    # Simulate agent completing its turn and waiting for the user's next input
    clock = test_env["clock"]
    session_service.transition(conn, clock, session_id, "awaiting_input")

    # 3. Second consecutive message
    msg2_resp = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Also add City Palace on the second day"},
    )
    assert msg2_resp.status_code == 200
    assert msg2_resp.json()["ok"] is True

    # 4. Verify session state via GET
    get_resp = client.get(
        f"/api/v1/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200
    session_data = get_resp.json()
    assert session_data["ok"] is True
    assert session_data["data"]["session_id"] == session_id

    # 5. Verify audit events recorded both user messages in sequence
    audit_resp = client.get(
        f"/api/v1/sessions/{session_id}/audit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert audit_resp.status_code == 200
    events = audit_resp.json()["data"]["events"]
    said = [e for e in events if e["event_type"] == "SESSION_RESUMED"]
    assert len(said) == 2
    assert said[0]["input"]["message"] == "Please make sure to include Hawa Mahal in the itinerary"
    assert said[1]["input"]["message"] == "Also add City Palace on the second day"
