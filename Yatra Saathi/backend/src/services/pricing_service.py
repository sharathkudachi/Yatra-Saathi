"""Price re-derivation from live inventory (section 8). Never trust agent totals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.contracts.codes import RefusalError
from src.core import fx, money
from src.db.repositories import catalog as catalog_repo
from src.db.repositories.carts import CartItem

# kind -> budget category, per the approved mapping (section 8: transport = flights,
# accommodation = rooms; activities/food/misc have no bookable items).
CATEGORY_OF_KIND = {"flight": "transport", "hotel_stay": "accommodation"}


@dataclass(frozen=True)
class RepricedLine:
    cart_item: CartItem
    live_unit_price_minor: int
    price_changed: bool


def reprice_item(conn, item: CartItem, currency: str) -> RepricedLine:
    row = catalog_repo.get_inventory_row(conn, item.inventory_id)
    if row is None:
        raise RefusalError("UNKNOWN_INVENTORY", f"inventory row no longer exists: {item.inventory_id}")
    # Same conversion as when the offer was accepted, so only a real inventory price change shows.
    live_price_minor = fx.convert_to_minor(row["price"], row["currency"], currency)
    return RepricedLine(cart_item=item, live_unit_price_minor=live_price_minor,
                        price_changed=live_price_minor != item.unit_price_minor)


def reprice_all(conn, items: Iterable[CartItem], currency: str) -> list[RepricedLine]:
    return [reprice_item(conn, it, currency) for it in items]


def totals_for_lines(repriced: Iterable[RepricedLine], tax_rate_bp: int) -> money.Totals:
    line_totals = [money.line_total_minor(r.cart_item.units, r.live_unit_price_minor) for r in repriced]
    return money.compute_totals(line_totals, tax_rate_bp)


def category_subtotals_minor(repriced: Iterable[RepricedLine]) -> dict[str, int]:
    totals: dict[str, int] = {"transport": 0, "accommodation": 0}
    for r in repriced:
        category = CATEGORY_OF_KIND.get(r.cart_item.kind)
        if category:
            totals[category] += money.line_total_minor(r.cart_item.units, r.live_unit_price_minor)
    return totals
