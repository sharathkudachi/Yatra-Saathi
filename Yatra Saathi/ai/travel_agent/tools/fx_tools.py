# travel_agent/tools/fx_tools.py
"""Currency conversion with the backend's demo rates (`GET /catalog/currencies`).

Mirrors backend/src/core/fx.py exactly -- a unit price (one night, one seat) becomes
amount * inr_per_unit[src] / inr_per_unit[dst], rounded half-up to 2 decimals -- so the
agent's budget arithmetic matches what the backend will charge. Rates are kept as strings
in the graph state (JSON-friendly). Without rates (standalone/local runs) nothing converts
and only prices already in the trip currency are usable, as before.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Optional

Rates = Optional[Dict[str, str]]


def load_rates_via_backend(client, session_id: str) -> Dict[str, str]:
    return {r["iso4217"]: r["inr_per_unit"] for r in client.catalog_currencies(session_id)}


def can_convert(rates: Rates, src: str, dst: str) -> bool:
    return src == dst or bool(rates and src in rates and dst in rates)


def convert(amount: Decimal, src: str, dst: str, rates: Rates) -> Decimal:
    if src == dst:
        return amount
    if not can_convert(rates, src, dst):
        raise ValueError(f"no exchange rate for {src} -> {dst}")
    value = amount * Decimal(rates[src]) / Decimal(rates[dst])
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
