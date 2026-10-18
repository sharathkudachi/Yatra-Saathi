"""End-to-end service-level test of the agent flow: session -> offers -> cart ->
booking request -> human approval -> booking. Exercises the invariants in
section 15 that don't need HTTP (milestone 2)."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone

from src.contracts.codes import RefusalError
from src.core.clock import FixedClock
from src.db.repositories import bookings as bookings_repo
from src.db.repositories import carts as carts_repo
from src.db.repositories import confirmations as confirmations_repo
from src.db.repositories import sessions as sessions_repo
from src.services import (
    booking_service, cart_service, confirmation_service, offer_service,
    replay_service, session_service,
)
from src.services.mock_booking_provider import MockBookingProvider
from tests import support


class AgentFlowTestCase(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        self.conn = self.wc.raw()
        self.conn.row_factory = sqlite3.Row
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))

        self.flight = support.find_flight_offer(self.conn)
        self.hotel = support.find_hotel_offer(self.conn)
        self.user_id = self.conn.execute(
            "SELECT user_id FROM users WHERE status='active' AND home_currency='INR' LIMIT 1"
        ).fetchone()[0]

        hotel_dates = [n["for_date"] for n in self.hotel["nights"]]
        start_date = min(self.flight["for_date"], min(hotel_dates))
        end_date = max(self.flight["for_date"], max(hotel_dates))
        self.trip_id, self.budget_id = support.insert_trip_and_budget(
            self.conn, user_id=self.user_id, start_date=start_date, end_date=end_date,
            party_size=2, adults=2, children=0, currency="INR", budget_total="500000.00",
        )

    def tearDown(self):
        self.conn.close()
        self.wc.cleanup()
        support.assert_original_untouched()

    def _create_session(self, spend_cap="500000.00"):
        return session_service.create_session(
            self.conn, self.clock, user_id=self.user_id, trip_id=self.trip_id,
            goal_text="test goal", goal_language="en-IN", constraints={}, spend_cap=spend_cap,
            currency="INR", tax_rate_bp=1200, replan_limit=3,
        )

    def _submit_tool_result_and_add_to_cart(self, session_id, agent_run_id="run_" + "a" * 16):
        from src.db.repositories.trips import get_trip
        trip = get_trip(self.conn, self.trip_id)
        tool_call_event = self._append_tool_call(session_id, agent_run_id)

        flight_offer = {
            "kind": "flight", "entity_type": "flight_fare", "entity_id": self.flight["fare_id"],
            "items": [{"inventory_id": self.flight["inventory_id"], "units": 2}],
        }
        hotel_offer = {
            "kind": "hotel_stay", "entity_type": "room_type", "entity_id": self.hotel["room_type_id"],
            "items": [{"inventory_id": n["inventory_id"], "units": 1} for n in self.hotel["nights"]],
        }
        result = offer_service.process_tool_result(
            self.conn, self.clock, session_id, tool_call_id=tool_call_event.event_id,
            agent_run_id=agent_run_id, offers=[flight_offer, hotel_offer],
            trip=trip, session_currency="INR",
        )
        self.assertEqual(len(result["accepted"]), 2)
        offer_refs = [a["offer_ref"] for a in result["accepted"]]
        cart_service.add_items(self.conn, self.clock, session_id, offer_refs=offer_refs,
                                agent_run_id=agent_run_id, tax_rate_bp=1200)
        return offer_refs

    def _append_tool_call(self, session_id, agent_run_id):
        from src.services import audit_service
        return audit_service.append(
            self.conn, session_id=session_id, event_type="TOOL_CALL", actor="agent",
            agent_run_id=agent_run_id, occurred_at=self.clock.utc(), outcome="success",
            input_data={"tool": "search"}, result_data={},
        )

    def test_full_happy_path_books_successfully(self):
        session = self._create_session()
        session_service.transition(self.conn, self.clock, session.session_id, "executing")
        agent_run_id = "run_" + "a" * 16
        self._submit_tool_result_and_add_to_cart(session.session_id, agent_run_id)

        confirmation = confirmation_service.request_booking(
            self.conn, self.clock, session.session_id, agent_run_id=agent_run_id,
            tax_rate_bp=1200, ttl_seconds=900,
        )
        session_after_lock = sessions_repo.get(self.conn, session.session_id)
        self.assertEqual(session_after_lock.status, "awaiting_confirmation")

        approved = confirmation_service.approve(
            self.conn, self.clock, session.session_id, confirmation.confirmation_id,
            user_id=self.user_id, submitted_snapshot_hash=confirmation.snapshot_hash,
        )
        self.assertEqual(approved.status, "approved")

        outcome = booking_service.attempt_booking(
            self.conn, self.clock, session.session_id, confirmation.confirmation_id,
            tax_rate_bp=1200, provider=MockBookingProvider(),
        )
        self.assertTrue(outcome.booking_id.startswith("bkg_"))

        final_session = sessions_repo.get(self.conn, session.session_id)
        self.assertEqual(final_session.status, "completed")
        self.assertEqual(final_session.spend_committed, outcome.total_amount)

        cart = carts_repo.get_cart(self.conn, confirmation.cart_id)
        self.assertEqual(cart.status, "booked")

        verify = replay_service.replay_and_verify(self.conn, session.session_id)
        self.assertTrue(verify.chain_ok, verify.issues)
        self.assertTrue(verify.seq_gapless, verify.issues)

        # A second attempt is refused: one booking per session.
        with self.assertRaises(RefusalError) as ctx:
            booking_service.attempt_booking(
                self.conn, self.clock, session.session_id, confirmation.confirmation_id,
                tax_rate_bp=1200, provider=MockBookingProvider(),
            )
        self.assertEqual(ctx.exception.code, "SESSION_ALREADY_BOOKED")

    def test_spend_cap_refuses_over_budget_and_does_not_touch_cart(self):
        session = self._create_session(spend_cap="500000.00")
        session_service.transition(self.conn, self.clock, session.session_id, "executing")
        agent_run_id = "run_" + "b" * 16
        # Force a tiny effective cap by giving the trip's budget a tiny total instead.
        self.conn.execute("UPDATE budgets SET total_amount = '1.00' WHERE trip_id = ?", (self.trip_id,))

        tool_call_event = self._append_tool_call(session.session_id, agent_run_id)
        from src.db.repositories.trips import get_trip
        trip = get_trip(self.conn, self.trip_id)
        flight_offer = {
            "kind": "flight", "entity_type": "flight_fare", "entity_id": self.flight["fare_id"],
            "items": [{"inventory_id": self.flight["inventory_id"], "units": 2}],
        }
        result = offer_service.process_tool_result(
            self.conn, self.clock, session.session_id, tool_call_id=tool_call_event.event_id,
            agent_run_id=agent_run_id, offers=[flight_offer], trip=trip, session_currency="INR",
        )
        offer_ref = result["accepted"][0]["offer_ref"]

        with self.assertRaises(RefusalError) as ctx:
            cart_service.add_items(self.conn, self.clock, session.session_id, offer_refs=[offer_ref],
                                    agent_run_id=agent_run_id, tax_rate_bp=1200)
        self.assertEqual(ctx.exception.code, "SPEND_CAP_EXCEEDED")
        self.assertIsNone(carts_repo.get_active_cart(self.conn, session.session_id))

    def test_wrong_flight_units_is_rejected(self):
        session = self._create_session()
        agent_run_id = "run_" + "c" * 16
        tool_call_event = self._append_tool_call(session.session_id, agent_run_id)
        from src.db.repositories.trips import get_trip
        trip = get_trip(self.conn, self.trip_id)
        bad_flight_offer = {
            "kind": "flight", "entity_type": "flight_fare", "entity_id": self.flight["fare_id"],
            "items": [{"inventory_id": self.flight["inventory_id"], "units": 1}],  # trip party_size is 2
        }
        result = offer_service.process_tool_result(
            self.conn, self.clock, session.session_id, tool_call_id=tool_call_event.event_id,
            agent_run_id=agent_run_id, offers=[bad_flight_offer], trip=trip, session_currency="INR",
        )
        self.assertEqual(len(result["accepted"]), 0)
        self.assertEqual(result["rejected"][0]["code"], "INVALID_QUANTITY")

    def test_duplicate_inventory_row_in_cart_is_rejected(self):
        session = self._create_session()
        agent_run_id = "run_" + "d" * 16
        offer_refs = self._submit_tool_result_and_add_to_cart(session.session_id, agent_run_id)
        # Try adding the flight offer again (same inventory row already active in the cart).
        with self.assertRaises(RefusalError) as ctx:
            cart_service.add_items(self.conn, self.clock, session.session_id,
                                    offer_refs=[offer_refs[0]], agent_run_id=agent_run_id, tax_rate_bp=1200)
        self.assertEqual(ctx.exception.code, "DUPLICATE_ITEM")

    def test_confirmation_bypass_without_confirmation_is_refused(self):
        session = self._create_session()
        session_service.transition(self.conn, self.clock, session.session_id, "executing")
        agent_run_id = "run_" + "e" * 16
        self._submit_tool_result_and_add_to_cart(session.session_id, agent_run_id)
        confirmation = confirmation_service.request_booking(
            self.conn, self.clock, session.session_id, agent_run_id=agent_run_id,
            tax_rate_bp=1200, ttl_seconds=900,
        )
        # Never approved -- a rogue agent tries to book directly.
        with self.assertRaises(RefusalError) as ctx:
            booking_service.attempt_booking(
                self.conn, self.clock, session.session_id, confirmation.confirmation_id,
                tax_rate_bp=1200, provider=MockBookingProvider(),
            )
        self.assertEqual(ctx.exception.code, "CONFIRMATION_MISSING")

    def test_decline_releases_holds_and_reopens_cart(self):
        session = self._create_session()
        session_service.transition(self.conn, self.clock, session.session_id, "executing")
        agent_run_id = "run_" + "f" * 16
        self._submit_tool_result_and_add_to_cart(session.session_id, agent_run_id)
        confirmation = confirmation_service.request_booking(
            self.conn, self.clock, session.session_id, agent_run_id=agent_run_id,
            tax_rate_bp=1200, ttl_seconds=900,
        )
        declined = confirmation_service.decline(
            self.conn, self.clock, session.session_id, confirmation.confirmation_id,
            user_id=self.user_id, note="changed my mind",
        )
        self.assertEqual(declined.status, "declined")
        cart = carts_repo.get_cart(self.conn, confirmation.cart_id)
        self.assertEqual(cart.status, "open")
        final_session = sessions_repo.get(self.conn, session.session_id)
        self.assertEqual(final_session.status, "awaiting_input")


if __name__ == "__main__":
    unittest.main()
