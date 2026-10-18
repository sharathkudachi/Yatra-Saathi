"""Trip dates and flight timing in the agent: chat dates are checked the same way the backend
checks the brief, and flights are compared as instants (overnight arrivals are fine)."""
import os
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"

from travel_agent.extraction import parse_goal
from travel_agent.runner import run_agent
from travel_agent.tools.db import query_db
from travel_agent.tools.flight_tools import search_flights, time_problem
from travel_agent.tools.package_tools import build_packages

TODAY = date(2026, 9, 24)


class ChatDateTests(unittest.TestCase):
    def test_past_departure_is_rejected(self):
        r = run_agent("Mumbai to Lucknow departing 20/09/2026 returning 23/09/2026, 2 people under ₹60,000",
                      today=TODAY)
        self.assertEqual(r.status, "awaiting_input")
        self.assertIn("start_date", r.missing_fields)
        self.assertIn("is in the past", r.clarification_question)

    def test_return_before_departure_is_rejected_not_swapped(self):
        r = run_agent("Mumbai to Lucknow departing 07/11/2026 returning 04/11/2026, 2 people under ₹60,000",
                      today=TODAY)
        self.assertEqual(r.status, "awaiting_input")
        self.assertIn("end_date", r.missing_fields)
        self.assertEqual(r.requirements.start_date, date(2026, 11, 7))  # kept as typed
        self.assertIsNone(r.requirements.end_date)

    def test_valid_multi_night_trip_is_accepted(self):
        r = run_agent("Mumbai to Lucknow departing 04/11/2026 returning 07/11/2026, 2 people under ₹60,000",
                      today=TODAY)
        self.assertEqual((r.requirements.start_date, r.requirements.end_date), (date(2026, 11, 4), date(2026, 11, 7)))
        self.assertNotIn("start_date", r.missing_fields)
        self.assertNotIn("end_date", r.missing_fields)

    def test_day_first_dates_do_not_shift(self):
        fields = parse_goal("departing 04/11/2026 returning 07/11/2026", TODAY)
        self.assertEqual((fields["start_date"], fields["end_date"]), ("2026-11-04", "2026-11-07"))

    def test_today_is_allowed(self):
        r = run_agent("Mumbai to Lucknow departing 24/09/2026 returning 26/09/2026, 2 people under ₹60,000",
                      today=TODAY)
        self.assertNotIn("start_date", r.missing_fields)


def _overnight_flight():
    rows = query_db(
        """SELECT fl.departs_at, fl.arrives_at, oa.city_id AS origin, da.city_id AS dest, i.currency
           FROM flights fl
           JOIN airports oa ON oa.airport_id = fl.origin_airport_id
           JOIN airports da ON da.airport_id = fl.dest_airport_id
           JOIN flight_fares f ON f.flight_id = fl.flight_id AND f.status = 'active'
           JOIN inventory_calendar i ON i.entity_type = 'flight_fare' AND i.entity_id = f.fare_id
                                    AND i.for_date = substr(fl.departs_at, 1, 10)
           WHERE fl.status = 'active' AND substr(fl.arrives_at, 1, 10) > substr(fl.departs_at, 1, 10)
             AND (i.total_units - i.booked_units - i.held_units) >= 1
           ORDER BY fl.departs_at LIMIT 1""", ())
    return rows[0]


class FlightTimingTests(unittest.TestCase):
    def test_time_problem(self):
        self.assertIsNone(time_problem("2026-11-09T22:40:00+05:30", "2026-11-10T00:55:00+05:30", None))
        self.assertEqual(time_problem("2026-11-09T22:40:00+05:30", "2026-11-09T22:40:00+05:30", None), "bad_times")
        self.assertEqual(time_problem("2026-11-09T22:40:00+05:30", "2026-11-10T00:55:00+05:30",
                                      "2026-11-09T17:10:00+00:00"), "departed")  # 22:40 IST exactly
        self.assertIsNone(time_problem("2026-11-09T22:40:00+05:30", "2026-11-10T00:55:00+05:30",
                                       "2026-11-09T17:09:00+00:00"))

    def test_flight_landing_after_midnight_is_offered(self):
        f = _overnight_flight()
        found = search_flights(f["origin"], f["dest"], f["departs_at"][:10], 1, f["currency"])
        self.assertTrue(any(o["arrives_at"] == f["arrives_at"] for o in found["options"]))
        self.assertEqual(found["excluded"]["bad_times"], 0)

    def test_flight_that_already_left_is_not_offered(self):
        f = _overnight_flight()
        after = (datetime.fromisoformat(f["departs_at"]) + timedelta(minutes=1)).isoformat()
        found = search_flights(f["origin"], f["dest"], f["departs_at"][:10], 1, f["currency"], now=after)
        self.assertFalse(any(o["departs_at"] == f["departs_at"] for o in found["options"]))
        self.assertGreaterEqual(found["excluded"]["departed"], 1)

    def test_return_must_leave_after_the_outbound_lands(self):
        # Outbound lands 00:55 on the 10th; a 00:30 return that day is impossible, 09:00 is fine.
        out = {"fare_id": "o", "unit_price": Decimal("100"), "departs_at": "2026-11-09T22:40:00+05:30",
               "arrives_at": "2026-11-10T00:55:00+05:30", "duration_minutes": 135, "stops": 0}
        early = {**out, "fare_id": "r1", "departs_at": "2026-11-10T00:30:00+05:30",
                 "arrives_at": "2026-11-10T02:45:00+05:30"}
        later = {**out, "fare_id": "r2", "unit_price": Decimal("500"), "departs_at": "2026-11-10T09:00:00+05:30",
                 "arrives_at": "2026-11-10T11:15:00+05:30"}
        hotel = {"hotel_id": "h", "room_type_id": "rt", "total_price": Decimal("1000"), "guest_score": 8,
                 "rooms": 1, "nightly": [{"date": "2026-11-10", "price": "1000.00"}]}
        packages = build_packages([out], [early, later], [hotel], travellers=1, cap=None, styles=("value",))
        self.assertEqual([p["return"]["fare_id"] for p in packages], ["r2"])


if __name__ == "__main__":
    unittest.main()
