# travel_agent/tools/budget_tools.py
"""Deterministic money arithmetic and the hard spend cap.

Money is ``Decimal`` end to end (data rule R3: never float). Nothing in this module
consults an LLM; the cap passed in is the cap enforced.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Dict, Mapping

CENT = Decimal("0.01")


class HardCapViolation(Exception):
    """Raised when something tries to finalise a cart whose total exceeds the cap."""


def to_money(value) -> Decimal:
    """Parse an exact 2-dp amount. Floats are rejected so precision can't be lost silently."""
    if isinstance(value, float):
        raise TypeError("money must not be a float; pass a str, int or Decimal")
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"invalid money amount: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"invalid money amount: {value!r}")
    if amount < 0:
        raise ValueError(f"money amount cannot be negative: {value!r}")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(unit_price: Decimal, units: int) -> Decimal:
    """units × unit_price, half-up to 2 dp (same rule as booking_items.line_total)."""
    if units < 1:
        raise ValueError("units must be at least 1")
    return (to_money(unit_price) * units).quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal, currency: str) -> str:
    symbol = {"INR": "₹"}.get(currency, f"{currency} ")
    return f"{symbol}{amount:,.2f}"


@dataclass(frozen=True)
class BudgetResult:
    total_cost: Decimal
    budget_cap: Decimal
    remaining_budget: Decimal
    within_budget: bool
    currency: str
    breakdown: Dict[str, Decimal]

    @property
    def over_by(self) -> Decimal:
        return max(self.total_cost - self.budget_cap, Decimal("0.00"))


def check_budget(breakdown: Mapping[str, Decimal], budget_cap: Decimal, currency: str) -> BudgetResult:
    """Sum the category costs and compare against the hard cap (total <= cap passes)."""
    cap = to_money(budget_cap)
    if cap <= 0:
        raise ValueError("budget cap must be positive")
    parts = {name: to_money(cost) for name, cost in breakdown.items()}
    total = sum(parts.values(), Decimal("0.00"))
    return BudgetResult(
        total_cost=total,
        budget_cap=cap,
        remaining_budget=cap - total,
        within_budget=total <= cap,
        currency=currency,
        breakdown=parts,
    )


def assert_within_cap(total: Decimal, budget_cap: Decimal) -> None:
    """Final guard used by the cart step: refuses any total above the cap."""
    if to_money(total) > to_money(budget_cap):
        raise HardCapViolation(f"total {total} exceeds hard cap {budget_cap}")
