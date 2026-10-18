"""Hard spend cap and money arithmetic (pure Python, no DB)."""
import unittest
from decimal import Decimal

from travel_agent.nodes.budget_check import route_after_budget
from travel_agent.state import MAX_REPLANS
from travel_agent.tools.budget_tools import (HardCapViolation, assert_within_cap, check_budget,
                                             line_total, to_money)


class MoneyTests(unittest.TestCase):
    def test_float_is_rejected(self):
        with self.assertRaises(TypeError):
            to_money(0.1)

    def test_half_up_rounding(self):
        self.assertEqual(to_money("10.005"), Decimal("10.01"))
        self.assertEqual(line_total(Decimal("3333.335"), 3), Decimal("10000.02"))

    def test_invalid_amounts(self):
        for bad in ("abc", "-5", "NaN", "Infinity"):
            with self.assertRaises(ValueError):
                to_money(bad)


class HardCapTests(unittest.TestCase):
    def test_within_budget(self):
        r = check_budget({"flights": Decimal("10000"), "hotel": Decimal("12500")}, Decimal("25000"), "INR")
        self.assertTrue(r.within_budget)
        self.assertEqual(r.total_cost, Decimal("22500.00"))
        self.assertEqual(r.remaining_budget, Decimal("2500.00"))

    def test_exactly_at_cap_passes(self):
        self.assertTrue(check_budget({"a": Decimal("25000.00")}, Decimal("25000"), "INR").within_budget)

    def test_one_paisa_over_is_refused(self):
        r = check_budget({"a": Decimal("25000.01")}, Decimal("25000"), "INR")
        self.assertFalse(r.within_budget)
        self.assertEqual(r.over_by, Decimal("0.01"))
        with self.assertRaises(HardCapViolation):
            assert_within_cap(r.total_cost, r.budget_cap)

    def test_spec_example_is_refused(self):
        r = check_budget({"flights": Decimal("10000"), "hotel": Decimal("14000"),
                          "activities": Decimal("5000")}, Decimal("25000"), "INR")
        self.assertFalse(r.within_budget)
        self.assertEqual(r.total_cost, Decimal("29000.00"))

    def test_non_positive_cap_rejected(self):
        with self.assertRaises(ValueError):
            check_budget({"a": Decimal("1")}, Decimal("0"), "INR")

    def test_over_budget_never_routes_to_cart(self):
        for replans in range(MAX_REPLANS + 2):
            route = route_after_budget({"within_budget": False, "replan_count": replans})
            self.assertNotEqual(route, "cart")
        self.assertEqual(route_after_budget({"within_budget": False, "replan_count": MAX_REPLANS}), "fail")


if __name__ == "__main__":
    unittest.main()
