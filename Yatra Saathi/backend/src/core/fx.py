"""Indicative (demo) exchange rates, and the one conversion rule every price follows.

The dataset prices each hotel and fare in its local currency (AED in Abu Dhabi, THB in
Bangkok...) and has no exchange-rate table, so these fixed rates make a trip priceable,
cap-checkable and bookable in whichever supported currency the user picks. They are
approximate mid-market values for the demo -- NOT live rates -- and are shown as such.

Rule (the agent uses the same one via `GET /catalog/currencies`, so both sides agree to the
paisa): a *unit* price (one night, one seat) is converted as
    amount * inr_per_unit[src] / inr_per_unit[dst], rounded half-up to 2 decimals,
and line totals are then units x converted unit price, exactly as for same-currency prices.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.core import money

RATES_AS_OF = "2026-09-01"

# Indian rupees per one unit of each currency. NPR and BTN follow their fixed INR pegs.
INR_PER_UNIT: dict[str, Decimal] = {k: Decimal(v) for k, v in {
    "INR": "1", "USD": "84.00", "EUR": "91.00", "GBP": "107.00", "AED": "22.87", "SGD": "62.50",
    "THB": "2.35", "LKR": "0.28", "NPR": "0.625", "BTN": "1", "MVR": "5.45", "JPY": "0.56",
    "KRW": "0.062", "KWD": "273.00", "BHD": "223.00", "AUD": "55.50", "CAD": "61.50", "CHF": "95.00",
    "MYR": "18.00", "IDR": "0.0052", "VND": "0.0033", "CNY": "11.60", "QAR": "23.05", "SAR": "22.40",
    "NZD": "50.50",
}.items()}


def supported(currency: str) -> bool:
    return currency in INR_PER_UNIT


def convert(amount, src: str, dst: str) -> str:
    """Convert a 2-dp amount (text or Decimal) from `src` to `dst`; returns 2-dp text."""
    value = money.parse_amount(amount)
    if src != dst:
        if not (supported(src) and supported(dst)):
            raise money.MoneyError(f"no exchange rate for {src} -> {dst}")
        value = (value * INR_PER_UNIT[src] / INR_PER_UNIT[dst]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{value:.2f}"


def convert_to_minor(amount, src: str, dst: str) -> int:
    return money.to_minor(convert(amount, src, dst))


def rate_rows() -> list[dict]:
    return [{"iso4217": code, "inr_per_unit": str(rate), "as_of": RATES_AS_OF}
            for code, rate in sorted(INR_PER_UNIT.items())]
