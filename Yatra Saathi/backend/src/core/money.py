"""Money handling.

Conversion rules (documented, approved):
* Existing tables store 2-decimal text, e.g. '13907.20'. Kept as-is.
* New tables store integer minor units (paise for INR), e.g. 1390720.
* Conversion: text -> Decimal (max 2 decimals, non-negative) -> x100 -> int,
  and back: int -> Decimal / 100 -> 2-decimal text.
* Floats are never accepted. 2 decimal places for every currency (matches stored data).
* Tax: subtotal x rate, rounded half-up to 0.01 (i.e. to whole minor units).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Iterable

from .errors import MoneyError

TWO_PLACES = Decimal("0.01")
_AMOUNT_RE = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$")


def parse_amount(value: object) -> Decimal:
    """Parse a non-negative amount with at most 2 decimals. Accepts str or Decimal only."""
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise MoneyError(f"amount must be text or Decimal, got {type(value).__name__}")
    if isinstance(value, Decimal):
        if not value.is_finite() or value < 0:
            raise MoneyError("amount must be a finite, non-negative number")
        if value != value.quantize(TWO_PLACES):
            raise MoneyError("amount has more than 2 decimal places")
        return value.quantize(TWO_PLACES)
    if not _AMOUNT_RE.match(value):
        raise MoneyError(f"malformed amount: {value!r}")
    return Decimal(value).quantize(TWO_PLACES)


def to_minor(value: object) -> int:
    amount = parse_amount(value)
    return int(amount * 100)


def _check_minor(minor: object) -> int:
    if isinstance(minor, bool) or not isinstance(minor, int) or minor < 0:
        raise MoneyError("minor units must be a non-negative integer")
    return minor


def from_minor(minor: object) -> Decimal:
    return (Decimal(_check_minor(minor)) / 100).quantize(TWO_PLACES)


def format_minor(minor: object) -> str:
    return f"{from_minor(minor):.2f}"


def format_amount(value: object) -> str:
    return f"{parse_amount(value):.2f}"


def line_total_minor(units: object, unit_price_minor: object) -> int:
    if isinstance(units, bool) or not isinstance(units, int) or units < 1:
        raise MoneyError("units must be an integer >= 1")
    return units * _check_minor(unit_price_minor)


def tax_minor(subtotal_minor: object, rate_bp: object) -> int:
    subtotal = _check_minor(subtotal_minor)
    if isinstance(rate_bp, bool) or not isinstance(rate_bp, int) or not 0 <= rate_bp <= 10000:
        raise MoneyError("tax rate must be an integer between 0 and 10000 basis points")
    with localcontext() as ctx:
        ctx.prec = 50
        exact = Decimal(subtotal) * Decimal(rate_bp) / Decimal(10000)
        return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Totals:
    subtotal_minor: int
    tax_minor: int
    total_minor: int


def compute_totals(line_totals_minor: Iterable[int], rate_bp: int) -> Totals:
    subtotal = sum(_check_minor(x) for x in line_totals_minor)
    tax = tax_minor(subtotal, rate_bp)
    return Totals(subtotal, tax, subtotal + tax)
