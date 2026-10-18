"""Multi-currency trips: local prices convert into the session currency at the demo rates,
identically in the backend (src/core/fx.py) and the agent (travel_agent/tools/fx_tools.py)."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import date
from decimal import Decimal

from src.core import fx, money
from src.db.repositories import catalog as catalog_repo
from src.services import offer_service, pricing_service
from src.db.repositories.carts import CartItem
from tests import support
from travel_agent.tools import fx_tools


class FxRuleTests(unittest.TestCase):
    def test_same_currency_is_unchanged(self):
        self.assertEqual(fx.convert("1234.56", "INR", "INR"), "1234.56")

    def test_unit_price_converts_half_up_to_paise(self):
        # 100.00 AED * 22.87 = 2287.00 INR; 1.00 INR / 84 = 0.0119 -> 0.01 USD
        self.assertEqual(fx.convert("100.00", "AED", "INR"), "2287.00")
        self.assertEqual(fx.convert("1.00", "INR", "USD"), "0.01")
        self.assertEqual(fx.convert("0.50", "INR", "USD"), "0.01")  # 0.00595 -> 0.01 half-up

    def test_unknown_currency_is_refused(self):
        with self.assertRaises(money.MoneyError):
            fx.convert("1.00", "XYZ", "INR")

    def test_agent_converts_exactly_like_the_backend(self):
        rates = {r["iso4217"]: r["inr_per_unit"] for r in fx.rate_rows()}
        for amount in ("1.00", "999.99", "10083.02", "17892.77"):
            for src in ("AED", "THB", "IDR", "JPY", "CHF", "INR"):
                for dst in ("INR", "USD", "EUR", "AED"):
                    backend = fx.convert(amount, src, dst)
                    agent = fx_tools.convert(Decimal(amount), src, dst, rates)
                    self.assertEqual(Decimal(backend), agent, (amount, src, dst))


class ConvertedOfferTests(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        self.conn = self.wc.raw()
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.wc.cleanup()
        support.assert_original_untouched()

    def test_foreign_currency_stay_is_accepted_at_converted_prices(self):
        offer = support.find_hotel_offer(self.conn, currency="AED", nights=2)
        result = offer_service.validate_offer(self.conn, {
            "kind": "hotel_stay", "entity_type": "room_type", "entity_id": offer["room_type_id"],
            "items": [{"inventory_id": n["inventory_id"], "units": 1} for n in offer["nights"]],
        }, trip=None, session_currency="INR", today=date(2026, 1, 1))
        self.assertTrue(result.accepted, result.message)
        self.assertEqual(result.currency, "INR")
        expected = [fx.convert_to_minor(n["price"], "AED", "INR") for n in offer["nights"]]
        self.assertEqual([l["unit_price_minor"] for l in result.lines], expected)

    def test_repricing_a_converted_line_is_not_a_price_change(self):
        offer = support.find_hotel_offer(self.conn, currency="AED", nights=1)
        night = offer["nights"][0]
        unit = fx.convert_to_minor(night["price"], "AED", "INR")
        item = CartItem(cart_item_id="cit_x", cart_id="crt_x", session_id="agt_x", item_group_id="grp_x",
                        kind="hotel_stay", entity_type="room_type", entity_id=offer["room_type_id"],
                        inventory_id=night["inventory_id"], for_date=night["for_date"], units=1,
                        unit_price_minor=unit, line_total_minor=unit, source_event_id="evt_x",
                        source_offer_index=0, hold_id=None, status="active", added_in_version=1,
                        removed_in_version=None, added_at="2026-01-01T00:00:00Z", removed_at=None)
        self.assertFalse(pricing_service.reprice_item(self.conn, item, "INR").price_changed)
        self.assertEqual(catalog_repo.get_inventory_row(self.conn, night["inventory_id"])["currency"], "AED")


class UnsupportedCurrencyTests(unittest.TestCase):
    def test_a_currency_without_a_rate_is_refused_before_the_cart(self):
        self.assertFalse(fx.supported("XYZ"))
        self.assertTrue(all(fx.supported(c) for c in ("INR", "USD", "EUR", "AED", "THB", "JPY", "IDR", "CHF")))
