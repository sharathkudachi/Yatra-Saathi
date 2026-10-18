import unittest
from decimal import Decimal

from src.core.errors import MoneyError
from src.core.money import (compute_totals, format_amount, format_minor, from_minor,
                            line_total_minor, parse_amount, tax_minor, to_minor)


class ParseAmountTests(unittest.TestCase):
    def test_valid_text(self):
        for text, expected in [("0", "0.00"), ("0.00", "0.00"), ("1764", "1764.00"),
                               ("13907.2", "13907.20"), ("13907.20", "13907.20")]:
            self.assertEqual(format_amount(text), expected)

    def test_rejects_malformed_or_unsafe_input(self):
        bad = ["", " 1.00", "1.00 ", "-1.00", "1.001", "1e3", "NaN", "Infinity", "01.00",
               ".5", "1,000.00", "₹100", "1.", "+1"]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(MoneyError):
                parse_amount(value)

    def test_rejects_non_text_types(self):
        for value in [1.5, 100, True, None, [1]]:
            with self.subTest(value=value), self.assertRaises(MoneyError):
                parse_amount(value)

    def test_decimal_input(self):
        self.assertEqual(parse_amount(Decimal("12.3")), Decimal("12.30"))
        for value in [Decimal("-1"), Decimal("1.234"), Decimal("NaN"), Decimal("Infinity")]:
            with self.subTest(value=value), self.assertRaises(MoneyError):
                parse_amount(value)


class MinorUnitTests(unittest.TestCase):
    def test_round_trip(self):
        for text in ["0.00", "0.01", "1764.00", "13907.20", "99999999.99"]:
            self.assertEqual(format_minor(to_minor(text)), text)
        self.assertEqual(to_minor("13907.20"), 1390720)
        self.assertEqual(from_minor(1390720), Decimal("13907.20"))

    def test_rejects_invalid_minor(self):
        for value in [-1, 1.0, True, "100"]:
            with self.subTest(value=value), self.assertRaises(MoneyError):
                from_minor(value)


class LineAndTaxTests(unittest.TestCase):
    def test_line_total_requires_positive_integer_units(self):
        self.assertEqual(line_total_minor(2, 434665), 869330)
        for units in [0, -1, 1.5, True, "2", None]:
            with self.subTest(units=units), self.assertRaises(MoneyError):
                line_total_minor(units, 100)

    def test_tax_12_percent_golden_booking(self):
        # bkg_8d0849e2: items 11136.44, tax 1336.37, total 12472.81
        totals = compute_totals([to_minor("11136.44")], 1200)
        self.assertEqual(format_minor(totals.tax_minor), "1336.37")
        self.assertEqual(format_minor(totals.total_minor), "12472.81")

    def test_demo_figures(self):
        over = compute_totals([to_minor("36510.52"), to_minor("14749.15")], 1200)
        self.assertEqual((format_minor(over.subtotal_minor), format_minor(over.tax_minor),
                          format_minor(over.total_minor)), ("51259.67", "6151.16", "57410.83"))
        ok = compute_totals([to_minor("8693.30"), to_minor("3723.84")], 1200)
        self.assertEqual((format_minor(ok.subtotal_minor), format_minor(ok.tax_minor),
                          format_minor(ok.total_minor)), ("12417.14", "1490.06", "13907.20"))

    def test_rounding_is_half_up(self):
        # 12% can never produce an exact half paisa; use 12.5% to prove the rounding mode.
        self.assertEqual(tax_minor(4, 1250), 1)    # 0.5 -> 1
        self.assertEqual(tax_minor(12, 1250), 2)   # 1.5 -> 2
        self.assertEqual(tax_minor(3, 1250), 0)    # 0.375 -> 0

    def test_tax_rejects_bad_inputs(self):
        for args in [(-1, 1200), (100, -1), (100, 10001), (100, 12.0), (1.0, 1200)]:
            with self.subTest(args=args), self.assertRaises(MoneyError):
                tax_minor(*args)


if __name__ == "__main__":
    unittest.main()
