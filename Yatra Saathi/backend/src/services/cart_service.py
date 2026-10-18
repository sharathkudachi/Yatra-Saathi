"""Cart management: adding validated offers, soft-removing groups (section 12)."""
from __future__ import annotations

import json
from typing import Optional

from src.contracts.codes import RefusalError
from src.core import money
from src.core.clock import Clock
from src.core.ids import new_id
from src.db.repositories import audit as audit_repo
from src.db.repositories import carts as carts_repo
from src.db.repositories import sessions as sessions_repo
from src.db.repositories.carts import Cart, CartItem
from src.db.unit_of_work import transaction
from src.services import audit_service, budget_service, offer_service, pricing_service


def _peek_open_cart(conn, session_id: str) -> Optional[Cart]:
    """Read-only: returns the active cart, or raises if it exists but is locked.
    Never creates anything -- creation is deferred until the budget gate passes."""
    existing = carts_repo.get_active_cart(conn, session_id)
    if existing is not None and existing.status != "open":
        raise RefusalError("CART_LOCKED", "the cart is locked and cannot be modified")
    return existing


def get_or_create_open_cart(conn, clock: Clock, session_id: str) -> tuple[Cart, bool]:
    existing = _peek_open_cart(conn, session_id)
    if existing is not None:
        return existing, False
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    cart_id = new_id("crt")
    carts_repo.insert_cart(conn, cart_id=cart_id, session_id=session_id, currency=session.currency,
                            created_at=clock.utc())
    return carts_repo.get_cart(conn, cart_id), True


def _resolve_offer_ref(conn, session_id: str, offer_ref: str) -> dict:
    try:
        event_id, index = offer_service.parse_offer_ref(offer_ref)
    except ValueError as exc:
        raise RefusalError("UNKNOWN_OFFER_REF", str(exc)) from exc
    event = audit_repo.get(conn, event_id)
    if event is None or event.session_id != session_id or event.event_type != "TOOL_RESULT":
        raise RefusalError("UNKNOWN_OFFER_REF", f"offer_ref does not resolve to this session: {offer_ref}")
    result = json.loads(event.result_json)
    for accepted in result.get("accepted", []):
        if accepted["index"] == index:
            return {**accepted, "source_event_id": event_id}
    raise RefusalError("UNKNOWN_OFFER_REF", f"no accepted offer at index {index} in {event_id}")


class Preview:
    """A read-only preview of adding `offer_refs` to a session's cart: nothing is
    written. Shared by `add_items` (which gates + commits it) and the advisory
    `POST /budget-checks` route (which only ever reports, never commits)."""

    def __init__(self, cart, created: bool, current_version: int, new_rows: list[dict],
                 totals, category_minor: dict[str, int]):
        self.cart = cart
        self.created = created
        self.current_version = current_version
        self.new_rows = new_rows
        self.totals = totals
        self.category_minor = category_minor


def preview_addition(conn, session_id: str, offer_refs: list[str], *, tax_rate_bp: int) -> Preview:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")

    # Read-only: resolve offers and compute totals without writing anything.
    cart = _peek_open_cart(conn, session_id)
    created = cart is None
    existing_items = carts_repo.list_active_items(conn, cart.cart_id) if cart else []
    existing_inventory_ids = {it.inventory_id for it in existing_items}
    current_version = cart.version if cart else 0

    new_rows: list[dict] = []
    for offer_ref in offer_refs:
        resolved = _resolve_offer_ref(conn, session_id, offer_ref)
        group_id = new_id("grp")
        for line in resolved["lines"]:
            if line["inventory_id"] in existing_inventory_ids:
                raise RefusalError("DUPLICATE_ITEM",
                                    f"inventory row already in the cart: {line['inventory_id']}")
            existing_inventory_ids.add(line["inventory_id"])
            new_rows.append({
                "group_id": group_id, "kind": resolved["kind"], "entity_type": resolved["entity_type"],
                "entity_id": resolved["entity_id"], "source_event_id": resolved["source_event_id"],
                "source_offer_index": resolved["index"], "line": line,
            })

    if not new_rows:
        raise RefusalError("CART_EMPTY", "no offer_refs were given")

    all_line_totals = [money.line_total_minor(it.units, it.unit_price_minor) for it in existing_items]
    all_line_totals += [money.line_total_minor(r["line"]["units"], r["line"]["unit_price_minor"])
                         for r in new_rows]
    totals = money.compute_totals(all_line_totals, tax_rate_bp)

    category_minor: dict[str, int] = {"transport": 0, "accommodation": 0}
    for it in existing_items:
        cat = pricing_service.CATEGORY_OF_KIND.get(it.kind)
        if cat:
            category_minor[cat] += money.line_total_minor(it.units, it.unit_price_minor)
    for r in new_rows:
        cat = pricing_service.CATEGORY_OF_KIND.get(r["kind"])
        if cat:
            category_minor[cat] += money.line_total_minor(r["line"]["units"], r["line"]["unit_price_minor"])

    return Preview(cart, created, current_version, new_rows, totals, category_minor)


def add_items(
    conn, clock: Clock, session_id: str, *, offer_refs: list[str], agent_run_id: str,
    tax_rate_bp: int,
) -> dict:
    # Read-only phase: resolve offers and compute totals without writing anything,
    # so a refusal (budget or otherwise) leaves the database completely untouched.
    preview = preview_addition(conn, session_id, offer_refs, tax_rate_bp=tax_rate_bp)
    cart, created, current_version = preview.cart, preview.created, preview.current_version
    new_rows, totals, category_minor = preview.new_rows, preview.totals, preview.category_minor

    # Gate: on failure this writes the refusal in its own transaction and raises;
    # nothing has been written yet at this point, so there is nothing to roll back.
    result = budget_service.run_gate(
        conn, clock, session_id, checkpoint="cart_add", subtotal_minor=totals.subtotal_minor,
        tax_minor=totals.tax_minor, total_minor=totals.total_minor, category_minor=category_minor,
        actor="agent", agent_run_id=agent_run_id,
    )

    with transaction(conn):
        if cart is None:
            cart, _ = get_or_create_open_cart(conn, clock, session_id)
        now = clock.utc()
        new_version = current_version + 1
        for r in new_rows:
            item = CartItem(
                cart_item_id=new_id("cit"), cart_id=cart.cart_id, session_id=session_id,
                item_group_id=r["group_id"], kind=r["kind"], entity_type=r["entity_type"],
                entity_id=r["entity_id"], inventory_id=r["line"]["inventory_id"],
                for_date=r["line"]["for_date"], units=r["line"]["units"],
                unit_price_minor=r["line"]["unit_price_minor"],
                line_total_minor=money.line_total_minor(r["line"]["units"], r["line"]["unit_price_minor"]),
                source_event_id=r["source_event_id"], source_offer_index=r["source_offer_index"],
                hold_id=None, status="active", added_in_version=new_version, removed_in_version=None,
                added_at=now, removed_at=None,
            )
            carts_repo.insert_item(conn, item)

        carts_repo.update_totals(conn, cart.cart_id, version=new_version, subtotal_minor=totals.subtotal_minor,
                                  tax_minor=totals.tax_minor, total_minor=totals.total_minor, updated_at=now)

        budget_service.record(conn, clock, session_id, result, actor="agent", agent_run_id=agent_run_id,
                              cart_id=cart.cart_id)
        audit_service.append(
            conn, session_id=session_id, event_type="CART_CREATED" if created else "CART_UPDATED",
            actor="agent", agent_run_id=agent_run_id, occurred_at=now, outcome="success",
            input_data={"offer_refs": offer_refs},
            result_data={"cart_id": cart.cart_id, "version": new_version, "status": "open",
                          "subtotal_minor": totals.subtotal_minor, "tax_minor": totals.tax_minor,
                          "total_minor": totals.total_minor},
            cart_id=cart.cart_id, cart_version=new_version,
        )
    return {"cart_id": cart.cart_id, "version": new_version, "subtotal_minor": totals.subtotal_minor,
            "tax_minor": totals.tax_minor, "total_minor": totals.total_minor}


def remove_item_group(conn, clock: Clock, session_id: str, item_group_id: str, *,
                       agent_run_id: str, tax_rate_bp: int) -> dict:
    cart = carts_repo.get_active_cart(conn, session_id)
    if cart is None:
        raise RefusalError("CART_EMPTY", "there is no active cart for this session")
    if cart.status != "open":
        raise RefusalError("CART_LOCKED", "the cart is locked and cannot be modified")

    group_items = carts_repo.list_items_by_group(conn, cart.cart_id, item_group_id)
    if not group_items:
        raise RefusalError("UNKNOWN_OFFER_REF", f"unknown item group: {item_group_id}")

    with transaction(conn):
        now = clock.utc()
        new_version = cart.version + 1
        for item in group_items:
            carts_repo.remove_item(conn, item.cart_item_id, removed_in_version=new_version, removed_at=now)

        remaining = [it for it in carts_repo.list_active_items(conn, cart.cart_id)]
        totals = money.compute_totals(
            [money.line_total_minor(it.units, it.unit_price_minor) for it in remaining], tax_rate_bp
        )
        carts_repo.update_totals(conn, cart.cart_id, version=new_version, subtotal_minor=totals.subtotal_minor,
                                  tax_minor=totals.tax_minor, total_minor=totals.total_minor, updated_at=now)

        audit_service.append(
            conn, session_id=session_id, event_type="CART_UPDATED", actor="agent",
            agent_run_id=agent_run_id, occurred_at=now, outcome="success",
            input_data={"item_group_id": item_group_id},
            result_data={"cart_id": cart.cart_id, "version": new_version, "status": "open",
                          "subtotal_minor": totals.subtotal_minor, "tax_minor": totals.tax_minor,
                          "total_minor": totals.total_minor},
            cart_id=cart.cart_id, cart_version=new_version,
        )
    return {"cart_id": cart.cart_id, "version": new_version, "subtotal_minor": totals.subtotal_minor,
            "tax_minor": totals.tax_minor, "total_minor": totals.total_minor}
