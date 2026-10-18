"""Travel tools against the real, read-only APS-01.db."""
import hashlib
import os
import sqlite3
import unittest
from datetime import date
from decimal import Decimal

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"

from travel_agent.extraction import detect_language, parse_goal
from travel_agent.tools.activity_tools import search_activities, select_activities
from travel_agent.tools.city_tools import resolve_city
from travel_agent.tools.db import db_path, query_db
from travel_agent.tools.flight_tools import search_flights, select_flight
from travel_agent.tools.hotel_tools import search_hotels, select_hotel

MUMBAI = resolve_city("Mumbai")["city_id"]
LUCKNOW = resolve_city("Lucknow")["city_id"]


def _sha256() -> str:
    return hashlib.sha256(db_path().read_bytes()).hexdigest()


class DatabaseIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.digest = _sha256()

    def test_writes_are_impossible(self):
        with self.assertRaises(sqlite3.OperationalError):
            query_db("UPDATE cities SET name = name WHERE 0")
        with self.assertRaises(sqlite3.OperationalError):
            query_db("CREATE TABLE should_not_exist (x)")

    @classmethod
    def tearDownClass(cls):
        assert _sha256() == cls.digest, "APS-01.db changed during tests"


class FlightToolTests(unittest.TestCase):
    def test_real_fares_for_demo_route(self):
        search = search_flights(MUMBAI, LUCKNOW, "2026-11-16", 2, "INR")
        self.assertTrue(search["options"])
        for fare in search["options"]:
            self.assertTrue(fare["fare_id"].startswith("far_"))
            self.assertTrue(fare["inventory_id"].startswith("inv_"))
            self.assertEqual(fare["for_date"], "2026-11-16")
            self.assertGreaterEqual(fare["seats_available"], 2)
            self.assertIsInstance(fare["unit_price"], Decimal)
        self.assertEqual(select_flight(search["options"], 0)["cabin_class"], "economy")

    def test_seat_filter(self):
        # AI-8346 economy standard has 4 free seats on 2026-11-19; 5 travellers must exclude it.
        search = search_flights(LUCKNOW, MUMBAI, "2026-11-19", 5, "INR")
        self.assertGreater(search["excluded"]["insufficient_seats"], 0)
        self.assertTrue(all(f["seats_available"] >= 5 for f in search["options"]))

    def test_no_route_returns_empty(self):
        panaji = resolve_city("Goa")["city_id"]  # alias → Panaji, which has no flights in the data
        self.assertEqual(search_flights(MUMBAI, panaji, "2026-11-16", 1, "INR")["found"], 0)


class HotelToolTests(unittest.TestCase):
    def test_every_night_is_priced(self):
        search = search_hotels(LUCKNOW, "2026-11-16", "2026-11-19", 2, "INR")
        self.assertTrue(search["options"])
        for option in search["options"]:
            self.assertEqual([n["for_date"] for n in option["nightly"]],
                             ["2026-11-16", "2026-11-17", "2026-11-18"])
            self.assertEqual(option["total_price"],
                             sum(n["price"] for n in option["nightly"]) * option["rooms"])

    def test_cheaper_strategy_never_costs_more(self):
        options = search_hotels(LUCKNOW, "2026-11-16", "2026-11-19", 2, "INR")["options"]
        self.assertLessEqual(select_hotel(options, 1)["total_price"], select_hotel(options, 0)["total_price"])

    def test_rooms_scale_with_travellers(self):
        options = search_hotels(LUCKNOW, "2026-11-16", "2026-11-19", 5, "INR")["options"]
        self.assertTrue(all(o["rooms"] >= 2 for o in options))


class ActivityToolTests(unittest.TestCase):
    def test_activities_from_itinerary_data(self):
        options = search_activities(LUCKNOW, "INR")["options"]
        self.assertTrue(options)
        titles = [o["title"].lower() for o in options]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertTrue(all(o["poi_id"].startswith("poi_") for o in options))

    def test_replan_levels(self):
        options = search_activities(LUCKNOW, "INR")["options"]
        self.assertTrue(all(a["unit_price"] == 0 for a in select_activities(options, 2, 3)))
        self.assertEqual(select_activities(options, 3, 3), [])


class ExtractionTests(unittest.TestCase):
    TODAY = date(2026, 9, 24)

    def test_full_goal(self):
        fields = parse_goal("Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 "
                            "for 2 people under ₹40,000", self.TODAY)
        self.assertEqual(fields["origin_name"], "Mumbai")
        self.assertEqual(fields["destination_name"], "Lucknow")
        self.assertEqual(fields["start_date"], "2026-11-16")
        self.assertEqual(fields["end_date"], "2026-11-19")
        self.assertEqual(fields["travellers"], 2)
        self.assertEqual(fields["budget_amount"], "40000")

    def test_budget_variants(self):
        self.assertEqual(parse_goal("budget 40k", self.TODAY)["budget_amount"], "40000.00")
        self.assertEqual(parse_goal("max Rs. 1.5 lakh", self.TODAY)["budget_amount"], "150000.00")
        self.assertNotIn("budget_amount", parse_goal("within 3 days", self.TODAY))

    def test_aliases_and_language(self):
        fields = parse_goal("Bangalore to Delhi", self.TODAY)
        self.assertEqual((fields["origin_name"], fields["destination_name"]), ("Bengaluru", "New Delhi"))
        self.assertEqual(detect_language("मुझे यात्रा करनी है"), "hi")


class GroqWiringTests(unittest.TestCase):
    """The Groq client is mocked; no network call is made."""

    def _fake_client(self, content=None, error=None):
        from unittest import mock
        client = mock.MagicMock()
        if error:
            client.chat.completions.create.side_effect = error
        else:
            client.chat.completions.create.return_value.choices = [
                mock.MagicMock(message=mock.MagicMock(content=content))]
        return client

    def test_json_request_and_parse(self):
        from unittest import mock
        from travel_agent import llm
        client = self._fake_client('{"origin_city": "Mumbai", "travellers": 2}')
        env = {"GROQ_API_KEY": "test", "TRAVEL_AGENT_DISABLE_LLM": ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(llm, "_client", return_value=client):
            data = llm.generate_json("intake", goal="x", today="2026-09-24")
        self.assertEqual(data, {"origin_city": "Mumbai", "travellers": 2})
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["temperature"], 0)

    def test_errors_fall_back_to_none(self):
        from unittest import mock
        from travel_agent import llm
        env = {"GROQ_API_KEY": "test", "TRAVEL_AGENT_DISABLE_LLM": ""}
        for client in (self._fake_client(error=RuntimeError("quota")), self._fake_client("not json")):
            with mock.patch.dict(os.environ, env), mock.patch.object(llm, "_client", return_value=client):
                self.assertIsNone(llm.generate_json("intake", goal="x", today="2026-09-24"))

    def test_disabled_without_key(self):
        from unittest import mock
        from travel_agent import llm
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "TRAVEL_AGENT_DISABLE_LLM": ""}):
            self.assertFalse(llm.llm_enabled())


if __name__ == "__main__":
    unittest.main()
