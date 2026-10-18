"""GET /api/v1/sessions/{sid}/cart

The active cart, or once the trip is booked, the booked cart (so the itinerary stays visible)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_conn, get_current_user, require_session_owner
from src.contracts.envelope import ok
from src.core import money
from src.db.repositories import carts as carts_repo
from src.db.repositories import catalog as catalog_repo

router = APIRouter()


@router.get("/sessions/{session_id}/cart")
def get_cart(session_id: str, user: CurrentUser = Depends(get_current_user),
             conn: sqlite3.Connection = Depends(get_conn)):
    require_session_owner(conn, session_id, user)
    cart = carts_repo.get_active_cart(conn, session_id) or carts_repo.get_booked_cart(conn, session_id)
    if cart is None:
        return ok({"cart": None, "items": []})
    items = carts_repo.list_active_items(conn, cart.cart_id)
    titles = {(it.entity_type, it.entity_id): catalog_repo.display_title(conn, it.entity_type, it.entity_id)
              for it in items}
    details = {(it.entity_type, it.entity_id): catalog_repo.item_details(conn, it.entity_type, it.entity_id)
               for it in items}
    return ok({
        "cart_id": cart.cart_id, "status": cart.status, "version": cart.version,
        "currency": cart.currency, "subtotal": money.format_minor(cart.subtotal_minor),
        "tax": money.format_minor(cart.tax_minor), "total": money.format_minor(cart.total_minor),
        "items": [
            {"cart_item_id": it.cart_item_id, "item_group_id": it.item_group_id, "kind": it.kind,
             "entity_type": it.entity_type, "entity_id": it.entity_id,
             "title": titles[(it.entity_type, it.entity_id)],
             "details": details[(it.entity_type, it.entity_id)], "for_date": it.for_date,
             "units": it.units, "unit_price": money.format_minor(it.unit_price_minor),
             "line_total": money.format_minor(it.line_total_minor)}
            for it in items
        ],
    })
