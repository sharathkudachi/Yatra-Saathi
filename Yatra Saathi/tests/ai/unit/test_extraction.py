"""Free-text extraction of the phrasings real users type, and remembering answers
across clarification turns (`carry`)."""
import os
import unittest
from datetime import date

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"

from travel_agent.extraction import parse_goal
from travel_agent.runner import run_agent

TODAY = date(2026, 9, 24)


def parse(text):
    return parse_goal(text, TODAY, {"INR"})


class ExtractionTests(unittest.TestCase):
    def test_departure_city_phrasing_is_the_origin(self):
        self.assertEqual(parse("my depurture city is bengaluru").get("origin_name"), "Bengaluru")
        self.assertEqual(parse("leaving from Mumbai").get("origin_name"), "Mumbai")

    def test_destination_phrasing_is_the_destination(self):
        self.assertEqual(parse("my destination is delhi"), {"destination_name": "New Delhi"})

    def test_both_roles_in_one_sentence(self):
        got = parse("departure city is bengaluru and destination city is delhi")
        self.assertEqual((got["origin_name"], got["destination_name"]), ("Bengaluru", "New Delhi"))

    def test_nearest_cue_wins(self):
        self.assertEqual(parse("from Atlantis to Lucknow"), {"destination_name": "Lucknow"})

    def test_day_first_numeric_dates(self):
        got = parse("travel date from 16/11/2026 and return date is 21/11/2026")
        self.assertEqual((got["start_date"], got["end_date"]), ("2026-11-16", "2026-11-21"))

    def test_date_range_formats_and_five_adults(self):
        for date_range in (
            "12 to 16 October 2026", "12th to 16th October 2026",
            "12 Oct to 16 Oct 2026", "12 October 2026 to 16 October 2026",
        ):
            with self.subTest(date_range=date_range):
                got = parse(
                    f"Plan a trip from Mumbai to Kolkata for 5 adults from {date_range}, budget ₹50000"
                )
                self.assertEqual((got["origin_name"], got["destination_name"]), ("Mumbai", "Kolkata"))
                self.assertEqual((got["start_date"], got["end_date"]), ("2026-10-12", "2026-10-16"))
                self.assertEqual(got["travellers"], 5)
                self.assertEqual((got["budget_amount"], got["budget_currency"]), ("50000", "INR"))

    def test_budget_is_amount(self):
        self.assertEqual(parse("maximum budget is 100000")["budget_amount"], "100000")
        self.assertEqual(parse("budget is 1,00,000")["budget_amount"], "100000")

    def test_misspelt_travellers(self):
        self.assertEqual(parse("a total of 2 traverllalers")["travellers"], 2)


class CarryOverTests(unittest.TestCase):
    def test_a_reply_only_fills_the_gaps(self):
        first = run_agent("from Mumbai to Lucknow on 16 Nov 2026 for 3 nights, 2 people", today=TODAY)
        self.assertEqual(first.status, "awaiting_input")
        self.assertEqual(first.missing_fields, ["budget_cap"])
        carry = first.requirements.model_dump(mode="json")
        second = run_agent("inr 60000", today=TODAY, carry=carry)
        self.assertEqual(second.status, "awaiting_confirmation")
        self.assertEqual(second.requirements.destination_name, "Lucknow")


class SingleDateTests(unittest.TestCase):
    def test_a_lone_return_date_is_the_end_date(self):
        self.assertEqual(parse("return on 19/11/2026"), {"end_date": "2026-11-19"})

    def test_a_lone_date_is_otherwise_the_start_date(self):
        self.assertEqual(parse("ok leave on 11/11/2026"), {"start_date": "2026-11-11"})


class BudgetCurrencyTests(unittest.TestCase):
    def test_symbols_set_the_budget_currency(self):
        self.assertEqual(parse("under $1,200")["budget_currency"], "USD")
        self.assertEqual(parse("budget is €900")["budget_currency"], "EUR")
        self.assertEqual(parse("under ₹60,000")["budget_currency"], "INR")

    def test_a_bare_number_is_in_the_trip_currency(self):
        self.assertIsNone(parse("maximum budget is 100000")["budget_currency"])


class BudgetWordBoundaryTests(unittest.TestCase):
    def test_words_starting_with_star_do_not_hide_the_budget(self):
        self.assertEqual(parse("maximum budget of 100000 starting from bengaluru")["budget_amount"], "100000")

    def test_hotel_stars_are_not_a_budget(self):
        self.assertNotIn("budget_amount", parse("a hotel under 5 stars"))
