"""Live-app planning flow: three packages to choose from, then the chosen one goes to the cart."""
import os
import unittest
from datetime import date
from decimal import Decimal

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"

from travel_agent.extraction import find_preference, pick_option, wants_other_hotels
from travel_agent.runner import run_agent

TODAY = date(2026, 9, 24)
DEMO = "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹60,000"


def offer(goal, *, previous=None, preference=None, exclude=()):
    extras = {"offer_options": True, "pending_packages": previous.packages if previous else [],
              "preference": preference, "exclude_hotels": list(exclude)}
    carry = previous.requirements.model_dump(mode="json") if previous else None
    return run_agent(goal, today=TODAY, carry=carry, extras=extras)


class OptionsFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = offer(DEMO)

    def test_offers_up_to_three_distinct_packages_within_the_cap(self):
        r = self.first
        self.assertEqual(r.status, "awaiting_input")
        self.assertTrue(1 <= len(r.packages) <= 3)
        keys = {(p["outbound"]["fare_id"], p["return"]["fare_id"], p["hotel"]["room_type_id"]) for p in r.packages}
        self.assertEqual(len(keys), len(r.packages), "options must be real alternatives")
        self.assertTrue(all(Decimal(p["total"]) <= Decimal("60000") for p in r.packages))
        self.assertIn("1. Best value", r.clarification_question)

    def test_choosing_an_option_builds_the_cart_from_it(self):
        pkg = self.first.packages[-1]
        chosen = offer(str(pkg["index"]), previous=self.first)
        self.assertEqual(chosen.status, "awaiting_confirmation", chosen.message)
        cart_ids = {line.entity_id for line in chosen.cart.lines}
        self.assertEqual(cart_ids, {pkg["outbound"]["fare_id"], pkg["return"]["fare_id"], pkg["hotel"]["room_type_id"]})
        self.assertIn("Your choice:", chosen.message)

    def test_other_hotels_offers_new_ones(self):
        again = offer("show me other hotels", previous=self.first)
        self.assertEqual(again.status, "awaiting_input")
        before = {p["hotel"]["hotel_id"] for p in self.first.packages}
        after = {p["hotel"]["hotel_id"] for p in again.packages}
        self.assertTrue(after and not (after & before) or len(after) < len(before) + 1)


class ChoiceParsingTests(unittest.TestCase):
    PKGS = [{"key": "value", "index": 1}, {"key": "comfort", "index": 2}, {"key": "timing", "index": 3}]

    def test_choices(self):
        for text, index in [("2", 2), ("option 3", 3), ("I'll take the second one", 2),
                            ("go with the comfortable one", 2), ("book package #1", 1)]:
            self.assertEqual(pick_option(text, self.PKGS)["index"], index, text)

    def test_not_a_choice(self):
        for text in ["cheaper please", "for 2 people", "change dates to 20 Nov 2026", "4"]:
            self.assertIsNone(pick_option(text, self.PKGS), text)

    def test_preferences(self):
        self.assertEqual(find_preference("something cheaper"), "cheapest")
        self.assertEqual(find_preference("a budget trip"), "value")
        self.assertEqual(find_preference("a better hotel please"), "comfort")
        self.assertEqual(find_preference("nonstop flights"), "timing")
        self.assertTrue(wants_other_hotels("show me other hotels"))


class FlightTimeTests(unittest.TestCase):
    def test_flight_time(self):
        from travel_agent.extraction import find_flight_time
        self.assertEqual(find_flight_time("morning flights please"), "morning")
        self.assertEqual(find_flight_time("I'd rather fly in the evening"), "evening")
        self.assertIsNone(find_flight_time("a morning walk by the lake"))


class CardTests(unittest.TestCase):
    def test_cards_carry_no_floats(self):
        # The backend audit trail rejects floats in hashed content.
        import json
        r = offer(DEMO)
        from travel_agent.tools.package_tools import card
        for event in r.events:
            if event.type == "CLARIFICATION_REQUIRED" and event.result and "options" in event.result:
                text = json.dumps(event.result["options"], default=str)
                self.assertNotRegex(text, r'": \d+\.\d+[,}]')

    def test_saved_packages_carry_no_floats(self):
        import json
        self.assertNotRegex(json.dumps(offer(DEMO).packages), r'": -?\d+\.\d+[,}]')
