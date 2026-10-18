"""Refusal → replan → recovery, replan termination, and cap-bypass attempts."""
import os
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"

from travel_agent import graph
from travel_agent.nodes import cart as cart_module
from travel_agent.nodes.replan import replan_node
from travel_agent.runner import run_agent
from travel_agent.state import MAX_REPLANS

TODAY = date(2026, 9, 24)
TRIP = "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹{cap}"


def types(result):
    return [e.type for e in result.events]


class RecoveryTests(unittest.TestCase):
    def test_over_budget_refused_then_replanned_into_cap(self):
        r = run_agent(TRIP.format(cap="40,000"), today=TODAY)
        t = types(r)
        self.assertEqual(r.status, "awaiting_confirmation")
        self.assertGreaterEqual(r.replan_count, 1)
        refused, replan, cart = t.index("ACTION_REFUSED"), t.index("REPLAN"), t.index("CART_CREATED")
        self.assertLess(refused, replan)
        self.assertLess(replan, cart)
        refusal = r.events[refused]
        self.assertEqual(refusal.error_code, "over_budget")
        self.assertIn("exceeds budget cap", refusal.reason)
        self.assertLessEqual(r.cart.total, Decimal("40000"))
        self.assertGreater(r.plan_version, 1)


class TerminationTests(unittest.TestCase):
    def test_max_replans_then_safe_failure(self):
        r = run_agent(TRIP.format(cap="20,000"), today=TODAY)
        t = types(r)
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error_code, "over_budget")
        self.assertEqual(r.replan_count, MAX_REPLANS)
        self.assertEqual(t.count("REPLAN"), MAX_REPLANS)
        self.assertEqual(t.count("BUDGET_CHECK"), MAX_REPLANS + 1)
        self.assertEqual(t.count("ACTION_REFUSED"), MAX_REPLANS + 1)
        self.assertIsNone(r.cart)
        self.assertNotIn("CONFIRMATION_REQUIRED", t)

    def test_replan_node_guard(self):
        update = replan_node({"replan_count": MAX_REPLANS, "events": []})
        self.assertEqual(update["error_code"], "over_budget")

    def test_fallback_executor_has_step_limit(self):
        with mock.patch.dict(graph.EDGES, {"planner": "planner"}):
            state = {"goal": TRIP.format(cap="40,000"), "today": TODAY.isoformat(), "events": [],
                     "language": "en-IN"}
            with self.assertRaises(RecursionError):
                graph.FallbackWorkflow().invoke(state, {"recursion_limit": 10})


class CapBypassTests(unittest.TestCase):
    def test_llm_cannot_set_or_raise_the_budget(self):
        hostile = {"origin_city": "Mumbai", "destination_city": "Lucknow", "budget": 10_000_000,
                   "budget_cap": 10_000_000}
        with mock.patch("travel_agent.nodes.intake.generate_json", return_value=hostile):
            r = run_agent(TRIP.format(cap="20,000"), today=TODAY)
        self.assertEqual(r.requirements.budget_cap, Decimal("20000.00"))
        self.assertEqual(r.status, "failed")

    def test_caller_cap_can_only_lower(self):
        lower = run_agent(TRIP.format(cap="60,000"), budget_cap="20000", today=TODAY)
        self.assertEqual(lower.requirements.budget_cap, Decimal("20000.00"))
        self.assertEqual(lower.status, "failed")
        higher = run_agent(TRIP.format(cap="20,000"), budget_cap="900000", today=TODAY)
        self.assertEqual(higher.requirements.budget_cap, Decimal("20000.00"))

    def test_cart_refuses_over_cap_even_if_budget_check_is_bypassed(self):
        with mock.patch.object(cart_module, "build_cart_lines",
                               return_value=[{"line_total": Decimal("99999.00")}]):
            update = cart_module.cart_node({"currency": "INR", "budget_cap": Decimal("40000"),
                                            "events": [], "plan": []})
        self.assertIsNone(update["cart"])
        self.assertEqual(update["error_code"], "over_budget")
        self.assertEqual(update["events"][-1]["type"], "ACTION_REFUSED")
        self.assertNotIn("confirmation_required", update)


@unittest.skipUnless(__import__("importlib").util.find_spec("langgraph"), "langgraph not installed")
class LangGraphEngineTests(unittest.TestCase):
    def test_real_langgraph_matches(self):
        r = run_agent(TRIP.format(cap="40,000"), today=TODAY)
        self.assertEqual(r.engine, "langgraph")
        self.assertEqual(r.status, "awaiting_confirmation")


if __name__ == "__main__":
    unittest.main()
