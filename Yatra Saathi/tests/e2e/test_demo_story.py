"""End-to-end test of the demo story (section 14): seeded demo trip/budget,
an over-cap proposal that gets refused, a re-plan to an affordable combo,
the confirmation gate, a simulated backend restart, and a successful booking,
finishing with the audit trail replay/verify."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.core import agent_tokens, human_tokens
from src.core.clock import FixedClock
from src.core.config import Settings
from src.main import create_app
from scripts.seed_demo import DEMO_TRIP_ID, DEMO_USER_ID, SESSION_SPEND_CAP, seed
from tests import support
from tests.fixtures.fake_agent_service import FakeAgentClient

HUMAN_SECRET = "demo-human-secret"
AGENT_SECRET = "demo-agent-secret"


class DemoStoryTestCase(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        conn = self.wc.raw()
        conn.row_factory = sqlite3.Row
        seed(conn)

        # A clearly over-cap flight (used first, refused), and a cheap flight + 2-night
        # hotel stay that together comfortably fit the ₹20,000 effective cap.
        self.expensive_flight = conn.execute(
            """SELECT ff.fare_id, ic.inventory_id, ic.for_date, ic.price
               FROM flight_fares ff
               JOIN inventory_calendar ic ON ic.entity_type='flight_fare' AND ic.entity_id=ff.fare_id
               WHERE ic.currency='INR' AND (ic.total_units-ic.booked_units-ic.held_units) >= 2
               ORDER BY CAST(ic.price AS REAL) DESC LIMIT 1"""
        ).fetchone()
        self.cheap_flight = conn.execute(
            """SELECT ff.fare_id, ic.inventory_id, ic.for_date, ic.price
               FROM flight_fares ff
               JOIN inventory_calendar ic ON ic.entity_type='flight_fare' AND ic.entity_id=ff.fare_id
               WHERE ic.currency='INR' AND (ic.total_units-ic.booked_units-ic.held_units) >= 2
               ORDER BY CAST(ic.price AS REAL) ASC LIMIT 1"""
        ).fetchone()
        self.hotel = support.find_hotel_offer(conn, nights=2, min_rooms=1)

        # Widen the seeded trip's dates to cover every date used in this test.
        all_dates = [self.expensive_flight["for_date"], self.cheap_flight["for_date"]] + \
            [n["for_date"] for n in self.hotel["nights"]]
        conn.execute("UPDATE trips SET start_date = ?, end_date = ? WHERE trip_id = ?",
                    (min(all_dates), max(all_dates), DEMO_TRIP_ID))
        conn.close()

        self.settings = Settings.from_env({
            "APS_DB_PATH": self.wc.path, "APS_DB_ORIGINAL_PATH": support.original_path(),
            "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
            "HUMAN_TOKEN_SECRET": HUMAN_SECRET, "AGENT_TOKEN_SECRET": AGENT_SECRET,
            "DEMO_LOGIN_USER_IDS": DEMO_USER_ID,
        })
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.client = TestClient(create_app(self.settings, clock=self.clock))
        self.human_token = human_tokens.issue(HUMAN_SECRET, DEMO_USER_ID, now=self.clock.now())
        self.human_headers = {"Authorization": f"Bearer {self.human_token}"}

    def tearDown(self):
        self.wc.cleanup()
        support.assert_original_untouched()

    def _agent_client(self, session_id: str) -> FakeAgentClient:
        token = agent_tokens.issue(AGENT_SECRET, session_id=session_id, run_id="run_" + "d" * 16,
                                    now=self.clock.now())
        return FakeAgentClient(self.client, token)

    def test_demo_story_end_to_end(self):
        # 1. Session created through the API: spend_cap ₹25,000, effective cap ₹20,000 (from the budget).
        r = self.client.post("/api/v1/sessions", json={
            "trip_id": DEMO_TRIP_ID, "goal_text": "Ahmedabad to Jaipur long weekend",
            "goal_language": "en-IN", "spend_cap": SESSION_SPEND_CAP, "currency": "INR",
        }, headers=self.human_headers)
        self.assertEqual(r.status_code, 200, r.text)
        session_id = r.json()["data"]["session_id"]
        agent = self._agent_client(session_id)

        ctx = agent.get_context(session_id)["data"]
        self.assertEqual(ctx["effective_cap"], "20000.00")
        self.assertEqual(ctx["cap_source"], "budget")

        self.client.post(f"/api/v1/sessions/{session_id}/messages",
                         json={"message": "plan my Ahmedabad to Jaipur trip"},
                         headers=self.human_headers)

        # 2. Plan shown, flight search tool call.
        agent.submit_plan(session_id, steps=[{"id": "s1", "description": "search flights"}])
        tool_call_id = agent.tool_call(session_id, "search_flights", {})
        expensive_offer = {
            "kind": "flight", "entity_type": "flight_fare", "entity_id": self.expensive_flight["fare_id"],
            "items": [{"inventory_id": self.expensive_flight["inventory_id"], "units": 2}],
        }
        result = agent.submit_results(session_id, tool_call_id, [expensive_offer])
        offer_ref = result["data"]["accepted"][0]["offer_ref"]

        # 3. Over-cap: cart_add refuses, cart stays empty, budget check + refusal audited.
        add_result = agent.add_to_cart(session_id, [offer_ref])
        self.assertFalse(add_result["ok"])
        self.assertEqual(add_result["refusal"]["code"], "SPEND_CAP_EXCEEDED")
        cart_after_refusal = self.client.get(f"/api/v1/sessions/{session_id}/cart",
                                             headers=self.human_headers).json()
        self.assertIsNone(cart_after_refusal["data"]["cart"])

        # 4. Re-plan to the affordable combo.
        agent.replan(session_id, "SPEND_CAP_EXCEEDED", "the first option was over budget")
        tool_call_id_2 = agent.tool_call(session_id, "search_flights_and_hotels", {})
        cheap_flight_offer = {
            "kind": "flight", "entity_type": "flight_fare", "entity_id": self.cheap_flight["fare_id"],
            "items": [{"inventory_id": self.cheap_flight["inventory_id"], "units": 2}],
        }
        hotel_offer = {
            "kind": "hotel_stay", "entity_type": "room_type", "entity_id": self.hotel["room_type_id"],
            "items": [{"inventory_id": n["inventory_id"], "units": 1} for n in self.hotel["nights"]],
        }
        result_2 = agent.submit_results(session_id, tool_call_id_2, [cheap_flight_offer, hotel_offer])
        self.assertEqual(len(result_2["data"]["accepted"]), 2)
        offer_refs_2 = [a["offer_ref"] for a in result_2["data"]["accepted"]]

        add_result_2 = agent.add_to_cart(session_id, offer_refs_2)
        self.assertTrue(add_result_2["ok"], add_result_2)

        # 5. Confirmation required; the agent's run stops here.
        booking_request = agent.request_booking(session_id)
        self.assertTrue(booking_request["ok"], booking_request)
        confirmation_id = booking_request["data"]["confirmation_id"]

        # A rogue fake agent tries to book before approval: refused.
        rogue = self.client.post(
            f"/internal/agent/v1/sessions/{session_id}/booking-requests", headers=agent.headers,
        )
        self.assertFalse(rogue.json()["ok"])

        # 6. Simulate a backend restart: a brand-new app/connection against the same DB file.
        restarted_client = TestClient(create_app(self.settings, clock=self.clock))
        current = restarted_client.get(f"/api/v1/sessions/{session_id}/confirmations/current",
                                       headers=self.human_headers).json()
        self.assertEqual(current["data"]["confirmation_id"], confirmation_id)
        snapshot_hash = current["data"]["snapshot_hash"]

        # 7. Human approves -> final check -> booking success.
        approve = restarted_client.post(
            f"/api/v1/sessions/{session_id}/confirmations/{confirmation_id}/approve",
            json={"snapshot_hash": snapshot_hash}, headers=self.human_headers,
        )
        self.assertEqual(approve.status_code, 200, approve.text)

        # 8. Audit timeline + /audit/verify.
        verify = restarted_client.get(f"/api/v1/sessions/{session_id}/audit/verify",
                                      headers=self.human_headers).json()
        self.assertTrue(verify["data"]["ok"], verify["data"])
        audit = restarted_client.get(f"/api/v1/sessions/{session_id}/audit", headers=self.human_headers).json()
        event_types = [e["event_type"] for e in audit["data"]["events"]]
        for required in ("SESSION_CREATED", "PLAN_CREATED", "TOOL_CALL", "TOOL_RESULT", "BUDGET_CHECK",
                         "ACTION_REFUSED", "REPLAN", "CART_CREATED", "CONFIRMATION_REQUIRED",
                         "CONFIRMATION_RECEIVED", "BOOKING_ATTEMPT", "BOOKING_SUCCESS"):
            self.assertIn(required, event_types, f"missing {required} in audit timeline")


if __name__ == "__main__":
    unittest.main()
