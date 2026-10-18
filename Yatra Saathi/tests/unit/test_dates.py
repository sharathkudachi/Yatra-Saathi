"""Trip-date and flight-time rules (src/core/dates.py): date-only parsing, IST "today",
and flights compared as instants but shown in each airport's own timezone."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from src.core import dates
from src.core.clock import FixedClock


class DateOnlyTests(unittest.TestCase):
    def test_date_only_strings_keep_their_calendar_day(self):
        self.assertEqual(dates.parse_date_only("2026-11-04"), date(2026, 11, 4))
        self.assertEqual(dates.parse_date_only("2026-12-31"), date(2026, 12, 31))

    def test_timestamps_and_other_formats_are_refused(self):
        for bad in ("2026-11-04T00:00:00Z", "2026-11-04T23:30:00+05:30", "04/11/2026", "2026-02-30", 20261104):
            with self.assertRaises(ValueError, msg=bad):
                dates.parse_date_only(bad)

    def test_today_is_the_ist_calendar_day(self):
        # 20:00 UTC on 3 Nov is already 01:30 on 4 Nov in IST.
        self.assertEqual(dates.local_today(FixedClock(datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc))),
                         date(2026, 11, 4))
        self.assertEqual(dates.local_today(FixedClock(datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc))),
                         date(2026, 11, 3))

    def test_order_and_past_rules(self):
        kw = {"start_label": "start", "end_label": "end"}
        self.assertIsNone(dates.date_order_error(date(2026, 11, 4), date(2026, 11, 7), **kw))
        self.assertIsNotNone(dates.date_order_error(date(2026, 11, 4), date(2026, 11, 4), **kw))
        self.assertIsNotNone(dates.date_order_error(date(2026, 11, 4), date(2026, 11, 3), **kw))
        today = date(2026, 9, 25)
        self.assertIsNotNone(dates.past_date_error(date(2026, 9, 24), today, label="start"))
        self.assertIsNone(dates.past_date_error(today, today, label="start"))


class FlightTimeTests(unittest.TestCase):
    def test_landing_after_local_midnight_is_valid_and_next_day(self):
        t = dates.flight_times("2026-11-09T22:40:00+05:30", "2026-11-10T00:55:00+05:30",
                               "Asia/Kolkata", "Asia/Kolkata")
        self.assertTrue(t["arrivesAfterDeparture"])
        self.assertEqual(t["arrivalDayOffset"], 1)
        self.assertEqual(t["arrivesAtLocal"], "2026-11-10T00:55:00+05:30")

    def test_local_day_is_judged_in_the_destination_timezone(self):
        # 00:21 IST is 22:51 the previous evening in Dubai: same local day as departure.
        t = dates.flight_times("2026-11-09T21:40:00+05:30", "2026-11-10T00:21:00+05:30",
                               "Asia/Kolkata", "Asia/Dubai")
        self.assertEqual(t["arrivesAtLocal"], "2026-11-09T22:51:00+04:00")
        self.assertEqual(t["arrivalDayOffset"], 0)
        # 23:50 IST is 01:20 the next morning in Bangkok.
        t = dates.flight_times("2026-11-09T19:00:00+05:30", "2026-11-09T23:50:00+05:30",
                               "Asia/Kolkata", "Asia/Bangkok")
        self.assertEqual(t["arrivesAtLocal"], "2026-11-10T01:20:00+07:00")
        self.assertEqual(t["arrivalDayOffset"], 1)
        self.assertTrue(t["arrivesAfterDeparture"])

    def test_arrival_at_or_before_departure_is_invalid(self):
        for arrives in ("2026-11-09T10:00:00+05:30", "2026-11-09T09:00:00+05:30"):
            self.assertFalse(dates.flight_times("2026-11-09T10:00:00+05:30", arrives, None, None)
                             ["arrivesAfterDeparture"])

    def test_departed_compares_instants(self):
        now = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)  # 21:30 IST
        self.assertTrue(dates.has_departed("2026-11-09T21:30:00+05:30", now))
        self.assertFalse(dates.has_departed("2026-11-09T21:31:00+05:30", now))


if __name__ == "__main__":
    unittest.main()
