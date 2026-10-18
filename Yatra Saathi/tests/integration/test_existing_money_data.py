"""The 2-decimal money rules and the 12% tax rule hold for every row of existing data."""
import unittest

from src.core.money import compute_totals, format_minor, parse_amount, to_minor
from tests.support import WorkingCopy, assert_original_untouched

MONEY_COLUMNS = {
    "inventory_calendar": ["price"],
    "bookings": ["total_amount", "tax_amount"],
    "booking_items": ["unit_price", "line_total"],
    "payments": ["authorised_amount", "captured_amount", "refunded_amount"],
    "budgets": ["total_amount", "accommodation_cap", "transport_cap", "food_cap", "activities_cap", "misc_cap"],
    "agent_sessions": ["spend_cap", "spend_committed"],
    "flight_fares": ["base_fare", "taxes", "change_fee"],
    "hotel_room_types": ["base_rate"],
}


def setUpModule():
    assert_original_untouched()
    global WC
    WC = WorkingCopy(migrate=False)


def tearDownModule():
    WC.cleanup()
    assert_original_untouched()


class ExistingMoneyTests(unittest.TestCase):
    def setUp(self):
        self.conn = WC.raw(readonly=True)

    def tearDown(self):
        self.conn.close()

    def test_every_stored_amount_parses_with_two_decimals(self):
        for table, cols in MONEY_COLUMNS.items():
            for col in cols:
                with self.subTest(column=f"{table}.{col}"):
                    for (value,) in self.conn.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL"):
                        if table == "agent_sessions" and col == "spend_cap":
                            self.assertEqual(to_minor(format_minor(to_minor(value))), to_minor(value))
                        else:
                            self.assertEqual(format_minor(to_minor(value)), value)

    def test_all_2008_bookings_follow_the_12_percent_rule(self):
        items = {}
        for booking_id, line_total in self.conn.execute("SELECT booking_id, line_total FROM booking_items"):
            items.setdefault(booking_id, []).append(to_minor(line_total))
        rows = self.conn.execute("SELECT booking_id, tax_amount, total_amount, channel FROM bookings").fetchall()
        self.assertEqual(len(rows), 2008)
        for booking_id, tax, total, channel in rows:
            booking_items = items.get(booking_id, [])
            if channel == "agent" and tax == "0.00":
                expected_total = format_minor(sum(booking_items))
                self.assertEqual(total, expected_total, booking_id)
            else:
                t = compute_totals(booking_items, 1200)
                self.assertEqual((format_minor(t.tax_minor), format_minor(t.total_minor)), (tax, total), booking_id)

    def test_line_totals_equal_units_times_unit_price(self):
        for units, unit_price, line_total in self.conn.execute(
                "SELECT units, unit_price, line_total FROM booking_items"):
            self.assertEqual(units * to_minor(unit_price), to_minor(line_total))

    def test_golden_booking(self):
        tax, total = self.conn.execute(
            "SELECT tax_amount, total_amount FROM bookings WHERE booking_id='bkg_8d0849e2'").fetchone()
        self.assertEqual((tax, total), ("1336.37", "12472.81"))
        self.assertEqual(parse_amount(total) - parse_amount(tax), parse_amount("11136.44"))


if __name__ == "__main__":
    unittest.main()
