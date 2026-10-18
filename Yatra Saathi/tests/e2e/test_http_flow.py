"""HTTP-level tests: the full demo-style flow end to end through FastAPI's
TestClient, plus the security invariants in section 15 that need a real HTTP
boundary (token checks, cross-session isolation, the confirmation gate)."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.core import agent_tokens, human_tokens
from src.core.clock import FixedClock
from src.core.config import Settings
from src.main import create_app
from tests import support
from tests.fixtures.fake_agent_service import FakeAgentClient

HUMAN_SECRET = "test-human-secret"
AGENT_SECRET = "test-agent-secret"


class HttpFlowTestCase(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        conn = self.wc.raw()
        import sqlite3
        conn.row_factory = sqlite3.Row

        self.flight = support.find_flight_offer(conn)
        self.hotel = support.find_hotel_offer(conn)
        self.user_id = conn.execute(
            "SELECT user_id FROM users WHERE status='active' AND home_currency='INR' LIMIT 1"
        ).fetchone()[0]
        self.other_user_id = conn.execute(
            "SELECT user_id FROM users WHERE status='active' AND home_currency='INR' AND user_id != ? LIMIT 1",
            (self.user_id,),
        ).fetchone()[0]
        hotel_dates = [n["for_date"] for n in self.hotel["nights"]]
        start_date = min(self.flight["for_date"], min(hotel_dates))
        end_date = max(self.flight["for_date"], max(hotel_dates))
        self.trip_id, _ = support.insert_trip_and_budget(
            conn, user_id=self.user_id, start_date=start_date, end_date=end_date,
            party_size=2, adults=2, children=0, currency="INR", budget_total="500000.00",
        )
        conn.close()

        self.settings = Settings.from_env({
            "APS_DB_PATH": self.wc.path, "APS_DB_ORIGINAL_PATH": support.original_path(),
            "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256,
            "HUMAN_TOKEN_SECRET": HUMAN_SECRET, "AGENT_TOKEN_SECRET": AGENT_SECRET,
            "DEMO_LOGIN_USER_IDS": f"{self.user_id},{self.other_user_id}",
        })
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.app = create_app(self.settings, clock=self.clock)
        self.client = TestClient(self.app)
        self.human_token = human_tokens.issue(HUMAN_SECRET, self.user_id, now=self.clock.now())
        self.human_headers = {"Authorization": f"Bearer {self.human_token}"}

    def tearDown(self):
        self.wc.cleanup()
        support.assert_original_untouched()

    def _create_session(self, spend_cap="500000.00"):
        r = self.client.post("/api/v1/sessions", json={
            "trip_id": self.trip_id, "goal_text": "test", "goal_language": "en-IN",
            "spend_cap": spend_cap, "currency": "INR",
        }, headers=self.human_headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["data"]["session_id"]

    def _agent_client(self, session_id: str) -> FakeAgentClient:
        token = agent_tokens.issue(AGENT_SECRET, session_id=session_id, run_id="run_" + "a" * 16,
                                    now=self.clock.now())
        return FakeAgentClient(self.client, token)

    def _session_with_dates(self, start, end):
        return self.client.post("/api/v1/sessions", json={
            "goal_text": "Plan a trip", "goal_language": "en-IN", "spend_cap": "50000.00", "currency": "INR",
            "constraints": {"start_date": start, "end_date": end},
        }, headers=self.human_headers)

    def test_session_trip_dates_are_validated(self):
        # Clock: 2026-01-01. Start = outbound flight / check-in, end = return flight / check-out.
        r = self._session_with_dates("2025-12-30", "2026-01-03")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["refusal"]["code"], "DATE_IN_PAST")
        for start, end in (("2026-11-07", "2026-11-04"), ("2026-11-04", "2026-11-04"),
                           ("2026-11-04T00:00:00Z", "2026-11-07")):
            self.assertEqual(self._session_with_dates(start, end).status_code, 422, (start, end))
        r = self._session_with_dates("2026-11-04", "2026-11-07")
        self.assertEqual(r.status_code, 200, r.text)

    def test_user_messages_are_kept_in_the_trip_history(self):
        session_id = self._create_session()
        r = self.client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": "Plan Lucknow for 2"},
                             headers=self.human_headers)
        self.assertEqual(r.status_code, 200, r.text)
        events = self.client.get(f"/api/v1/sessions/{session_id}/audit", headers=self.human_headers).json()["data"]["events"]
        said = [e for e in events if e["event_type"] == "SESSION_RESUMED"]
        self.assertEqual([(e["actor"], e["input"]["message"]) for e in said], [("user", "Plan Lucknow for 2")])
        verify = self.client.get(f"/api/v1/sessions/{session_id}/audit/verify", headers=self.human_headers).json()
        self.assertTrue(verify["data"]["ok"], verify)

    def test_push_subscription_and_test_notification(self):
        sub = {"subscription": {"endpoint": "https://push.example/abc123", "keys": {"p256dh": "k", "auth": "a"}},
               "prefs": {"tripUpdates": True, "bookingUpdates": False}}
        r = self.client.post("/api/v1/notifications/subscriptions", json=sub, headers=self.human_headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.post("/api/v1/notifications/subscriptions", json=sub).status_code, 401)
        t = self.client.post("/api/v1/notifications/test", json={}, headers=self.human_headers).json()["data"]
        self.assertTrue(t["sent"])
        self.assertFalse(t["pushEnabled"], "no VAPID keys in tests: recorded in-app only")
        notes = self.client.get("/api/v1/notifications", headers=self.human_headers).json()["data"]["notifications"]
        self.assertEqual(notes[0]["kind"], "test")
        self.client.request("DELETE", "/api/v1/notifications/subscriptions", json={"endpoint": "https://push.example/abc123"},
                            headers=self.human_headers)

    def test_demo_login_rejects_non_allowlisted_user(self):
        r = self.client.post("/api/v1/auth/demo-login", json={"user_id": "usr_not_allowlisted"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["refusal"]["code"], "USER_NOT_ALLOWED")

    def test_demo_login_issues_a_working_token(self):
        r = self.client.post("/api/v1/auth/demo-login", json={"user_id": self.user_id})
        self.assertEqual(r.status_code, 200)
        token = r.json()["data"]["token"]
        r2 = self.client.get("/api/v1/sessions/" + self._create_session(),
                             headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r2.status_code, 200)

    def _user_row(self):
        import sqlite3
        conn = self.wc.raw()
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT user_id, display_name, email FROM users WHERE user_id = ?",
                                (self.user_id,)).fetchone()
        finally:
            conn.close()

    def test_login_with_matching_id_name_email_issues_a_working_token(self):
        row = self._user_row()
        r = self.client.post("/api/v1/auth/login", json={
            "user_id": row["user_id"], "display_name": f"  {row['display_name'].upper()} ",
            "email": row["email"].upper(),
        })
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()["data"]
        self.assertEqual(data["user"]["user_id"], self.user_id)
        self.assertEqual(data["user"]["email"], row["email"])
        me = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["data"]["user"]["display_name"], row["display_name"])

    def test_login_rejects_any_mismatched_field_with_one_code(self):
        row = self._user_row()
        good = {"user_id": row["user_id"], "display_name": row["display_name"], "email": row["email"]}
        for field, bad in (("user_id", "usr_doesnotexist"), ("display_name", "Someone Else"),
                           ("email", "someone.else@example.invalid")):
            with self.subTest(field=field):
                r = self.client.post("/api/v1/auth/login", json={**good, field: bad})
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json()["refusal"]["code"], "LOGIN_MISMATCH")

    def test_me_requires_a_token(self):
        r = self.client.get("/api/v1/auth/me")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["refusal"]["code"], "TOKEN_MISSING")

    def test_cors_preflight_allows_the_frontend_origin(self):
        r = self.client.options("/api/v1/auth/login", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_create_session_rejects_malformed_money_and_currency_without_500(self):
        base = {"goal_text": "x", "goal_language": "en-IN", "spend_cap": "1000.00", "currency": "INR"}
        for field, bad in (("spend_cap", "25000.555"), ("spend_cap", "25,000"), ("spend_cap", "-5"),
                           ("currency", "inr"), ("goal_text", "")):
            with self.subTest(field=field, value=bad):
                r = self.client.post("/api/v1/sessions", json={**base, field: bad}, headers=self.human_headers)
                self.assertEqual(r.status_code, 422, r.text)
        r = self.client.post("/api/v1/sessions", json={**base, "currency": "ZZZ"}, headers=self.human_headers)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["refusal"]["code"], "MALFORMED_ITEM")

    def test_session_view_shows_enforced_cap_plan_and_titled_cart(self):
        session_id = self._create_session(spend_cap="500000.00")
        view = self.client.get(f"/api/v1/sessions/{session_id}", headers=self.human_headers).json()["data"]
        self.assertEqual(view["effective_cap"], "500000.00")
        self.assertEqual(view["cart_total"], "0.00")
        self.assertEqual(view["remaining"], "500000.00")
        self.assertEqual((view["plan_version"], view["plan_steps"]), (0, []))
        self.assertEqual(view["replan_limit"], self.settings.replan_limit)

        agent = self._agent_client(session_id)
        agent.submit_plan(session_id, steps=[{"id": "s1", "description": "find a stay"}])
        tool_call_id = agent.tool_call(session_id, "search_hotels", {})
        offer = {"kind": "hotel_stay", "entity_type": "room_type", "entity_id": self.hotel["room_type_id"],
                 "items": [{"inventory_id": n["inventory_id"], "units": 1} for n in self.hotel["nights"]]}
        refs = [a["offer_ref"] for a in agent.submit_results(session_id, tool_call_id, [offer])["data"]["accepted"]]
        self.assertTrue(agent.add_to_cart(session_id, refs)["ok"])

        view = self.client.get(f"/api/v1/sessions/{session_id}", headers=self.human_headers).json()["data"]
        cart = self.client.get(f"/api/v1/sessions/{session_id}/cart", headers=self.human_headers).json()["data"]
        self.assertEqual(view["plan_version"], 1)
        self.assertEqual([s["id"] for s in view["plan_steps"]], ["s1"])
        self.assertEqual(view["cart_total"], cart["total"])
        from src.core import money
        self.assertEqual(money.to_minor(view["remaining"]), money.to_minor("500000.00") - money.to_minor(cart["total"]))
        self.assertTrue(cart["items"])
        for item in cart["items"]:
            self.assertIsInstance(item["title"], str)
            self.assertIn("·", item["title"])

    def test_agent_token_rejected_on_human_route(self):
        session_id = self._create_session()
        agent = self._agent_client(session_id)
        r = self.client.get(f"/api/v1/sessions/{session_id}", headers=agent.headers)
        self.assertIn(r.status_code, (401, 403))

    def test_human_token_rejected_on_agent_route(self):
        session_id = self._create_session()
        r = self.client.get(f"/internal/agent/v1/sessions/{session_id}/context", headers=self.human_headers)
        self.assertIn(r.status_code, (401, 403))

    def test_agent_token_scoped_to_wrong_session_is_403(self):
        session_a = self._create_session()
        session_b = self._create_session()
        agent_for_a = self._agent_client(session_a)
        r = self.client.get(f"/internal/agent/v1/sessions/{session_b}/context", headers=agent_for_a.headers)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["refusal"]["code"], "SESSION_ACCESS_DENIED")

    def test_non_owner_human_cannot_read_session(self):
        session_id = self._create_session()
        other_token = human_tokens.issue(HUMAN_SECRET, self.other_user_id, now=self.clock.now())
        r = self.client.get(f"/api/v1/sessions/{session_id}",
                            headers={"Authorization": f"Bearer {other_token}"})
        self.assertEqual(r.status_code, 403)

    def test_forged_token_is_rejected(self):
        r = self.client.get("/api/v1/sessions/agt_deadbeefdead",
                            headers={"Authorization": "Bearer not.a.real.token"})
        self.assertEqual(r.status_code, 401)

    def test_rogue_agent_cannot_approve_confirmation(self):
        session_id = self._create_session()
        agent = self._agent_client(session_id)
        r = agent.rogue_try_approve_confirmation(session_id, "cnf_0000000000000000")
        self.assertEqual(r["status_code"], 401)

    def test_advisory_budget_check_never_mutates_the_cart(self):
        session_id = self._create_session()
        agent = self._agent_client(session_id)
        tool_call_id = agent.tool_call(session_id, "search_flights", {})
        flight_offer = {
            "kind": "flight", "entity_type": "flight_fare", "entity_id": self.flight["fare_id"],
            "items": [{"inventory_id": self.flight["inventory_id"], "units": 2}],
        }
        result = agent.submit_results(session_id, tool_call_id, [flight_offer])
        offer_ref = result["data"]["accepted"][0]["offer_ref"]

        advisory = agent.budget_check(session_id, [offer_ref])
        self.assertTrue(advisory["ok"], advisory)

        cart = self.client.get(f"/api/v1/sessions/{session_id}/cart", headers=self.human_headers).json()
        self.assertIsNone(cart["data"]["cart"])

    def test_replying_while_an_approval_waits_withdraws_it_and_reopens_the_cart(self):
        session_id = self._create_session()
        agent = self._agent_client(session_id)
        self.client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": "plan my trip"},
                         headers=self.human_headers)
        agent.submit_plan(session_id, steps=[{"id": "s1", "description": "search"}])
        tool_call_id = agent.tool_call(session_id, "search_flights", {})
        offer = {"kind": "flight", "entity_type": "flight_fare", "entity_id": self.flight["fare_id"],
                 "items": [{"inventory_id": self.flight["inventory_id"], "units": 2}]}
        refs = [a["offer_ref"] for a in agent.submit_results(session_id, tool_call_id, [offer])["data"]["accepted"]]
        self.assertTrue(agent.add_to_cart(session_id, refs)["ok"])
        confirmation_id = agent.request_booking(session_id)["data"]["confirmation_id"]
        snapshot = self.client.get(f"/api/v1/sessions/{session_id}/confirmations/current",
                                   headers=self.human_headers).json()["data"]["snapshot_hash"]

        r = self.client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": "something cheaper please"},
                             headers=self.human_headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["status"], "executing")
        approve = self.client.post(f"/api/v1/sessions/{session_id}/confirmations/{confirmation_id}/approve",
                                   json={"snapshot_hash": snapshot}, headers=self.human_headers).json()
        self.assertFalse(approve["ok"], "a withdrawn approval must not book")
        cart = self.client.get(f"/api/v1/sessions/{session_id}/cart", headers=self.human_headers).json()["data"]
        self.assertEqual(cart["status"], "open")
        ctx = agent.get_context(session_id)["data"]
        self.assertTrue(ctx["cart"]["item_group_ids"])
        events = [e["event_type"] for e in self.client.get(f"/api/v1/sessions/{session_id}/audit",
                                                            headers=self.human_headers).json()["data"]["events"]]
        self.assertIn("CONFIRMATION_INVALIDATED", events)
        self.assertTrue(self.client.get(f"/api/v1/sessions/{session_id}/audit/verify",
                                        headers=self.human_headers).json()["data"]["ok"])

    def test_full_demo_flow_over_http(self):
        session_id = self._create_session()
        agent = self._agent_client(session_id)

        ctx = agent.get_context(session_id)
        self.assertTrue(ctx["ok"])
        self.assertEqual(ctx["data"]["status"], "planning")

        self.client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": "plan my trip"},
                         headers=self.human_headers)

        agent.submit_plan(session_id, steps=[{"id": "s1", "description": "search flights"}])
        tool_call_id = agent.tool_call(session_id, "search_flights", {})
        flight_offer = {
            "kind": "flight", "entity_type": "flight_fare", "entity_id": self.flight["fare_id"],
            "items": [{"inventory_id": self.flight["inventory_id"], "units": 2}],
        }
        hotel_offer = {
            "kind": "hotel_stay", "entity_type": "room_type", "entity_id": self.hotel["room_type_id"],
            "items": [{"inventory_id": n["inventory_id"], "units": 1} for n in self.hotel["nights"]],
        }
        result = agent.submit_results(session_id, tool_call_id, [flight_offer, hotel_offer])
        self.assertEqual(len(result["data"]["accepted"]), 2)
        offer_refs = [a["offer_ref"] for a in result["data"]["accepted"]]

        advisory = agent.budget_check(session_id, offer_refs)
        self.assertTrue(advisory["ok"], advisory)
        self.assertTrue(advisory["data"]["passed"])
        self.assertEqual(advisory["data"]["checkpoint"], "advisory")

        cart_result = agent.add_to_cart(session_id, offer_refs)
        self.assertTrue(cart_result["ok"], cart_result)

        booking_request = agent.request_booking(session_id)
        self.assertTrue(booking_request["ok"], booking_request)
        confirmation_id = booking_request["data"]["confirmation_id"]

        current = self.client.get(f"/api/v1/sessions/{session_id}/confirmations/current",
                                  headers=self.human_headers).json()
        self.assertEqual(current["data"]["confirmation_id"], confirmation_id)
        snapshot_hash = current["data"]["snapshot_hash"]

        approve = self.client.post(
            f"/api/v1/sessions/{session_id}/confirmations/{confirmation_id}/approve",
            json={"snapshot_hash": snapshot_hash}, headers=self.human_headers,
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        self.assertTrue(approve.json()["data"]["booking_id"].startswith("bkg_"))

        booking = self.client.get(f"/api/v1/sessions/{session_id}/booking", headers=self.human_headers).json()
        self.assertIsNotNone(booking["data"]["booking"])

        # My trips lists the booked trip for its owner only, with the booking reference.
        mine = self.client.get("/api/v1/trips", headers=self.human_headers).json()["data"]["trips"]
        booked = [t for t in mine if t["sessionId"] == session_id]
        self.assertEqual(len(booked), 1)
        self.assertEqual(booked[0]["status"], "confirmed")
        self.assertEqual(booked[0]["bookingReference"], booking["data"]["booking"]["booking_reference"])
        other = human_tokens.issue(HUMAN_SECRET, self.other_user_id, now=self.clock.now())
        theirs = self.client.get("/api/v1/trips", headers={"Authorization": f"Bearer {other}"}).json()["data"]["trips"]
        self.assertFalse([t for t in theirs if t["sessionId"] == session_id])
        self.assertEqual(self.client.get("/api/v1/trips").status_code, 401)

        # Notifications: approval ready and booking confirmed, recorded once each.
        notes = self.client.get("/api/v1/notifications", headers=self.human_headers).json()["data"]["notifications"]
        kinds = [n["kind"] for n in notes]
        self.assertIn("approval_ready", kinds)
        self.assertIn("booking_confirmed", kinds)
        self.assertEqual(self.client.get("/api/v1/notifications").status_code, 401)

        # The scheduler announces the landing once the booked flight has arrived -- and only once.
        import sqlite3 as _sqlite3
        from datetime import datetime as _dt, timedelta as _td
        from src.core.clock import FixedClock as _Fixed
        from src.services import notify_scheduler
        conn = self.wc.raw(); conn.row_factory = _sqlite3.Row
        arrives = conn.execute("SELECT arrives_at FROM flights WHERE flight_id = ?", (self.flight["flight_id"],)).fetchone()[0]
        later = _Fixed(_dt.fromisoformat(arrives) + _td(hours=1))
        first = notify_scheduler.run_once(conn, later, self.settings)
        second = notify_scheduler.run_once(conn, later, self.settings)
        conn.close()
        self.assertEqual(first["notifications"], 1)
        self.assertEqual(second["notifications"], 0)
        landed = [n for n in self.client.get("/api/v1/notifications", headers=self.human_headers).json()["data"]["notifications"]
                  if n["kind"] == "flight_landed"]
        self.assertEqual(len(landed), 1)
        self.assertTrue(landed[0]["title"].startswith("Welcome to"))

        # After booking, the cart route still returns the (booked) cart with itinerary details.
        booked_cart = self.client.get(f"/api/v1/sessions/{session_id}/cart", headers=self.human_headers).json()["data"]
        self.assertEqual(booked_cart["status"], "booked")
        self.assertTrue(booked_cart["items"])
        for item in booked_cart["items"]:
            self.assertIn(item["details"]["type"], ("flight", "stay"))
            if item["details"]["type"] == "flight":
                self.assertTrue(item["details"]["departs_at"] and item["details"]["origin_code"])
            else:
                self.assertTrue(item["details"]["hotel"])

        verify = self.client.get(f"/api/v1/sessions/{session_id}/audit/verify", headers=self.human_headers).json()
        self.assertTrue(verify["data"]["ok"], verify["data"])

        # Duplicate confirmation click: the exact same approve request, repeated.
        # It must be refused, and it must not create a second booking.
        replay = self.client.post(
            f"/api/v1/sessions/{session_id}/confirmations/{confirmation_id}/approve",
            json={"snapshot_hash": snapshot_hash}, headers=self.human_headers,
        )
        self.assertFalse(replay.json()["ok"])
        self.assertIn(replay.json()["refusal"]["code"],
                      ("CONFIRMATION_ALREADY_USED", "SESSION_ALREADY_BOOKED", "INVALID_STATE"))
        booking_after = self.client.get(f"/api/v1/sessions/{session_id}/booking",
                                        headers=self.human_headers).json()["data"]["booking"]
        self.assertEqual(booking_after["booking_id"], booking["data"]["booking"]["booking_id"],
                         "a duplicate approve must not create a second booking")


if __name__ == "__main__":
    unittest.main()


class RequestConnectionThreadingTestCase(unittest.TestCase):
    """Under uvicorn, get_conn's setup and the endpoint run on different worker threads."""

    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        self.settings = Settings.from_env({"APS_DB_PATH": self.wc.path, "APS_DB_ORIGINAL_PATH": support.original_path(),
                                           "APS_DB_ORIGINAL_SHA256": support.RECORDED_ORIGINAL_SHA256})

    def tearDown(self):
        self.wc.cleanup()
        support.assert_original_untouched()

    def test_request_connection_is_usable_from_another_thread(self):
        import threading
        from src.api.deps import get_conn
        dependency = get_conn(self.settings)
        conn = next(dependency)
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.update(n=conn.execute("SELECT count(*) FROM users").fetchone()[0]))
        worker.start(); worker.join()
        dependency.close()
        self.assertGreater(outcome.get("n", 0), 0)
