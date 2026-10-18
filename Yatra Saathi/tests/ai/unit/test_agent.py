"""End-to-end agent runs through the compiled workflow."""
import os
import unittest
from datetime import date
from decimal import Decimal

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"

from travel_agent.runner import run_agent

TODAY = date(2026, 9, 24)
DEMO = "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹60,000"


def types(result):
    return [e.type for e in result.events]


class NormalTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_agent(DEMO, session_id="agt_test", today=TODAY)

    def test_ends_ready_for_confirmation(self):
        r = self.result
        self.assertEqual(r.status, "awaiting_confirmation")
        self.assertTrue(r.confirmation_required)
        self.assertEqual(r.replan_count, 0)
        self.assertEqual(types(r)[-2:], ["CART_CREATED", "CONFIRMATION_REQUIRED"])

    def test_plan_is_visible_before_any_tool_call(self):
        t = types(self.result)
        self.assertLess(t.index("PLAN_CREATED"), t.index("TOOL_CALL"))
        self.assertEqual([s.key for s in self.result.plan][-1], "booking")

    def test_at_least_two_tools_called(self):
        steps = {e.step for e in self.result.events if e.type == "TOOL_CALL"}
        self.assertTrue({"flight_search", "hotel_search", "activity_search"} <= steps)

    def test_cart_totals_are_exact(self):
        cart = self.result.cart
        self.assertEqual(cart.total, sum(line.line_total for line in cart.lines))
        self.assertLessEqual(cart.total, cart.budget_cap)
        self.assertEqual(cart.remaining, cart.budget_cap - cart.total)
        self.assertEqual({line.entity_type for line in cart.lines}, {"flight_fare", "room_type", "poi"})

    def test_confirmation_required_before_booking(self):
        r = self.result
        self.assertNotIn(r.status, ("executing", "completed"))
        self.assertEqual(next(s for s in r.plan if s.key == "booking").status, "pending")
        self.assertFalse(any("BOOK" in t or "PAY" in t for t in types(r)))

    def test_events_are_serialisable_and_carry_session(self):
        payload = self.result.model_dump(mode="json")
        self.assertIsInstance(payload["cart"]["total"], str)
        self.assertTrue(all(e["session_id"] == "agt_test" for e in payload["events"]))
        self.assertEqual([e["seq"] for e in payload["events"]], list(range(1, len(payload["events"]) + 1)))


class ClarificationTests(unittest.TestCase):
    def test_missing_information(self):
        r = run_agent("Plan a trip to Lucknow under ₹40,000", today=TODAY)
        self.assertEqual(r.status, "awaiting_input")
        self.assertTrue(r.clarification_required)
        self.assertEqual(r.missing_fields, ["origin", "start_date", "end_date", "travellers"])
        self.assertIn("CLARIFICATION_REQUIRED", types(r))
        self.assertNotIn("TOOL_CALL", types(r))

    def test_resume_after_clarification(self):
        first = run_agent("Plan a trip to Lucknow under ₹60,000", today=TODAY)
        second = run_agent("From Mumbai, 16 Nov 2026 for 3 nights, 2 people", previous=first, today=TODAY)
        self.assertEqual(second.status, "awaiting_confirmation")
        self.assertEqual(second.requirements.budget_cap, Decimal("60000.00"))

    def test_past_date_is_rejected(self):
        r = run_agent("Mumbai to Lucknow on 1 Sep 2026 for 3 nights, 2 people under ₹40,000", today=TODAY)
        self.assertEqual(r.status, "awaiting_input")
        self.assertIn("start_date", r.missing_fields)

    def test_return_on_or_before_departure_is_rejected(self):
        for back in ("14/11/2026", "16/11/2026"):
            r = run_agent(f"Mumbai to Lucknow departing 16/11/2026 returning {back}, 2 people under ₹40,000",
                          today=TODAY)
            self.assertEqual(r.status, "awaiting_input")
            self.assertIn("end_date", r.missing_fields)
            self.assertIn("must be after the departure date 16 Nov 2026", r.clarification_question)

    def test_unknown_city_asks_again(self):
        r = run_agent("from Atlantis to Lucknow 16 Nov 2026 for 3 nights, 2 people under ₹40,000", today=TODAY)
        self.assertEqual(r.status, "awaiting_input")
        self.assertIn("origin", r.missing_fields)

    def test_hindi_clarification(self):
        r = run_agent("लखनऊ", language="hi", today=TODAY)
        self.assertEqual(r.status, "awaiting_input")
        self.assertIn("खोज से पहले", r.clarification_question)


class NoAvailabilityTests(unittest.TestCase):
    def test_no_flights_fails_cleanly(self):
        r = run_agent("Mumbai to Goa on 16 Nov 2026 for 3 nights, 2 people under ₹60,000", today=TODAY)
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error_code, "constraint_infeasible")
        self.assertIsNone(r.cart)
        self.assertFalse(r.confirmation_required)
        self.assertEqual(types(r)[-1], "AGENT_FAILED")

    def test_large_party_only_gets_fares_with_enough_seats(self):
        r = run_agent("Mumbai to Lucknow on 16 Nov 2026 for 3 nights, 9 people under ₹900,000", today=TODAY)
        self.assertEqual(r.status, "awaiting_confirmation")
        flight_results = [e.result for e in r.events if e.type == "TOOL_RESULT" and e.step == "flight_search"]
        self.assertTrue(any(res["excluded"]["insufficient_seats"] > 0 for res in flight_results))
        self.assertTrue(all(line.units == 9 for line in r.cart.lines if line.entity_type == "flight_fare"))


if __name__ == "__main__":
    unittest.main()
