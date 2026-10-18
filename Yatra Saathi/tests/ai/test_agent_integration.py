"""The real integration point for Option A: `travel_agent.runner.run_agent`,
driven with a `BackendClient` pointed at our own FastAPI app (via `TestClient`,
no real socket), must reach `awaiting_confirmation` having created a real cart
and confirmation through our backend's own services -- never by trusting its
own local numbers, and never putting an activity/POI line in the cart.
"""
from __future__ import annotations

import os
from decimal import Decimal
import sqlite3
import unittest
from datetime import date, datetime, timezone

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"

from fastapi.testclient import TestClient

from backend_client import BackendClient
from src.core import agent_tokens, human_tokens
from src.core.clock import FixedClock
from src.core.config import Settings
from src.db.repositories import carts as carts_repo
from src.db.repositories import confirmations as confirmations_repo
from src.main import create_app
from tests import support
from travel_agent.runner import run_agent

HUMAN_SECRET = "agent-integration-human-secret"
AGENT_SECRET = "agent-integration-agent-secret"
GOAL = "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹60,000"


class AgentIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        conn = self.wc.raw()
        conn.row_factory = sqlite3.Row
        self.user_id = conn.execute(
            "SELECT user_id FROM users WHERE status='active' AND home_currency='INR' LIMIT 1"
        ).fetchone()[0]
        conn.close()

        self.settings = Settings.from_env({
            "APS_DB_PATH": self.wc.path, "APS_DB_ORIGINAL_PATH": support.original_path(),
            "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
            "HUMAN_TOKEN_SECRET": HUMAN_SECRET, "AGENT_TOKEN_SECRET": AGENT_SECRET,
            "DEMO_LOGIN_USER_IDS": self.user_id,
        })
        self.clock = FixedClock(datetime(2026, 9, 24, tzinfo=timezone.utc))
        self.app = create_app(self.settings, clock=self.clock)
        self.client = TestClient(self.app)
        self.human_token = human_tokens.issue(HUMAN_SECRET, self.user_id, now=self.clock.now())
        self.human_headers = {"Authorization": f"Bearer {self.human_token}"}

    def tearDown(self):
        self.wc.cleanup()
        support.assert_original_untouched()

    def _create_session(self, spend_cap: str) -> str:
        r = self.client.post("/api/v1/sessions", json={
            "trip_id": None, "goal_text": GOAL, "goal_language": "en-IN",
            "spend_cap": spend_cap, "currency": "INR",
        }, headers=self.human_headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["data"]["session_id"]

    def test_agent_reaches_awaiting_confirmation_through_the_real_backend(self):
        session_id = self._create_session(spend_cap="60000.00")
        # Human message dispatches the agent -- transitions the session to 'executing',
        # the same as the real flow (no AGENT_SERVICE_URL configured, so nothing else fires).
        self.client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": GOAL},
                         headers=self.human_headers)

        agent_token = agent_tokens.issue(AGENT_SECRET, session_id=session_id,
                                         run_id="run_" + "a" * 16, now=self.clock.now())
        backend_client = BackendClient(self.client, agent_token)

        result = run_agent(GOAL, session_id=session_id, client=backend_client, today=date(2026, 9, 24))

        self.assertEqual(result.status, "awaiting_confirmation", result.message)
        self.assertIsNotNone(result.cart)
        self.assertTrue(all(line.entity_type != "poi" for line in result.cart.lines),
                        "an activity/POI line reached the agent's cart")

        # The cart and confirmation are real rows created by OUR services, not
        # something the agent invented -- and no POI/activity ever became a cart item.
        conn = self.wc.raw()
        conn.row_factory = sqlite3.Row
        cart = carts_repo.get_active_cart(conn, session_id)
        self.assertIsNotNone(cart)
        self.assertEqual(cart.status, "locked")
        items = carts_repo.list_active_items(conn, cart.cart_id)
        self.assertTrue(items)
        self.assertTrue(all(it.kind in ("flight", "hotel_stay") for it in items))
        confirmation = confirmations_repo.get_current(conn, session_id)
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation.status, "pending")
        conn.close()

    def test_agent_over_cap_is_refused_by_the_backend_and_replans(self):
        # A cap too small for any real itinerary: the backend must refuse (not the
        # agent's own arithmetic), and the agent must replan rather than crash.
        session_id = self._create_session(spend_cap="1.00")
        self.client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": GOAL},
                         headers=self.human_headers)
        agent_token = agent_tokens.issue(AGENT_SECRET, session_id=session_id,
                                         run_id="run_" + "b" * 16, now=self.clock.now())
        backend_client = BackendClient(self.client, agent_token)

        result = run_agent(GOAL, session_id=session_id, client=backend_client, today=date(2026, 9, 24))

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "over_budget")
        conn = self.wc.raw()
        self.assertIsNone(carts_repo.get_active_cart(conn, session_id))
        conn.close()


if __name__ == "__main__":
    unittest.main()


class OptionsReplanIntegrationTests(AgentIntegrationTestCase):
    """Live-app flow (three options) through the real backend: every failure is re-planned
    and shows up in the audit trail as a discrete REPLAN entry."""

    def _turn(self, session_id, message, previous=None):
        self.client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": message}, headers=self.human_headers)
        token = agent_tokens.issue(AGENT_SECRET, session_id=session_id, run_id="run_" + os.urandom(8).hex(), now=self.clock.now())
        extras = {"offer_options": True, "pending_packages": previous.packages if previous else []}
        carry = previous.requirements.model_dump(mode="json") if previous else None
        return run_agent(message, session_id=session_id, client=BackendClient(self.client, token),
                         today=date(2026, 9, 24), carry=carry, extras=extras)

    def _audit(self, session_id):
        return self.client.get(f"/api/v1/sessions/{session_id}/audit", headers=self.human_headers).json()["data"]["events"]

    def test_refused_option_is_replanned_within_the_cap(self):
        session_id = self._create_session(spend_cap="45000.00")
        offered = self._turn(session_id, GOAL.replace("₹60,000", "₹45,000"))
        self.assertEqual(offered.status, "awaiting_input", offered.message)
        self.assertTrue(offered.packages and all(Decimal(p["total"]) <= Decimal("45000") for p in offered.packages))
        events = self._audit(session_id)
        refusals = [e for e in events if e["event_type"] == "BUDGET_CHECK" and e["reason_code"] == "SPEND_CAP_EXCEEDED"]
        replans = [e for e in events if e["event_type"] == "REPLAN"]
        self.assertTrue(refusals, "the over-cap option must be refused by the backend")
        self.assertTrue(replans and replans[0]["seq"] > refusals[0]["seq"], "a refusal must be followed by a re-plan")

    def test_sold_out_choice_is_replanned_with_fresh_options(self):
        session_id = self._create_session(spend_cap="60000.00")
        offered = self._turn(session_id, GOAL)
        pkg = offered.packages[0]
        conn = self.wc.raw()  # someone else books the chosen room in the meantime
        for night in pkg["hotel"]["nightly"]:
            conn.execute("UPDATE inventory_calendar SET booked_units = total_units - held_units WHERE inventory_id = ?",
                         (night["inventory_id"],))
        conn.commit(); conn.close()
        again = self._turn(session_id, "1", previous=offered)
        self.assertEqual(again.status, "awaiting_input", again.message)
        self.assertNotIn(pkg["hotel"]["room_type_id"], {p["hotel"]["room_type_id"] for p in again.packages})
        replans = [e for e in self._audit(session_id) if e["event_type"] == "REPLAN"]
        self.assertTrue(any(e["input"]["reason_code"] == "SOLD_OUT" for e in replans))
