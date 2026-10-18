"""The human confirmation gate (section 9). The agent's run stops once a
confirmation is required; only a human token can approve or decline it."""
from __future__ import annotations

from typing import Optional

from src.contracts.codes import RefusalError
from src.core.clock import Clock
from src.core.hashing import canonical_json, sha256_hex
from src.core.ids import new_id
from src.db.repositories import carts as carts_repo
from src.db.repositories import confirmations as confirmations_repo
from src.db.repositories import sessions as sessions_repo
from src.db.repositories.confirmations import Confirmation
from src.db.unit_of_work import transaction
from src.services import audit_service, budget_service, inventory_service, pricing_service, session_service


def compute_snapshot_hash(*, session_id: str, cart_id: str, version: int, currency: str,
                           lines: list[dict], subtotal_minor: int, tax_minor: int,
                           total_minor: int) -> str:
    sorted_lines = sorted(
        ({"inventory_id": l["inventory_id"], "for_date": l["for_date"], "units": l["units"],
          "unit_price_minor": l["unit_price_minor"]} for l in lines),
        key=lambda l: (l["inventory_id"], l["for_date"]),
    )
    payload = {
        "session_id": session_id, "cart_id": cart_id, "version": version, "currency": currency,
        "lines": sorted_lines, "subtotal_minor": subtotal_minor, "tax_minor": tax_minor,
        "total_minor": total_minor,
    }
    return sha256_hex(canonical_json(payload))


def _cart_lines(items) -> list[dict]:
    return [{"inventory_id": it.inventory_id, "for_date": it.for_date, "units": it.units,
              "unit_price_minor": it.unit_price_minor} for it in items]


def request_booking(
    conn, clock: Clock, session_id: str, *, agent_run_id: str, tax_rate_bp: int, ttl_seconds: int,
) -> Confirmation:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    session_service.assert_transition_allowed(session.status, "awaiting_confirmation")

    cart = carts_repo.get_active_cart(conn, session_id)
    if cart is None or cart.status != "open":
        raise RefusalError("CART_EMPTY", "there is no open cart to lock for booking")
    items = carts_repo.list_active_items(conn, cart.cart_id)
    if not items:
        raise RefusalError("CART_EMPTY", "the cart has no items")

    category_minor: dict[str, int] = {"transport": 0, "accommodation": 0}
    for it in items:
        cat = pricing_service.CATEGORY_OF_KIND.get(it.kind)
        if cat:
            category_minor[cat] += it.line_total_minor

    # Gate: on failure this writes the refusal in its own transaction and raises;
    # nothing else has been written yet, so the cart and session are untouched.
    result = budget_service.run_gate(
        conn, clock, session_id, checkpoint="lock", subtotal_minor=cart.subtotal_minor,
        tax_minor=cart.tax_minor, total_minor=cart.total_minor, category_minor=category_minor,
        actor="agent", agent_run_id=agent_run_id,
    )

    cap = session_service.compute_cap_snapshot(conn, session_id)
    lines = _cart_lines(items)
    snapshot_hash = compute_snapshot_hash(
        session_id=session_id, cart_id=cart.cart_id, version=cart.version, currency=cart.currency,
        lines=lines, subtotal_minor=cart.subtotal_minor, tax_minor=cart.tax_minor,
        total_minor=cart.total_minor,
    )
    now = clock.utc()
    expires_at = _add_seconds(now, ttl_seconds)
    confirmation_id = new_id("cnf")

    with transaction(conn):
        hold_ids = inventory_service.create_holds_for_cart_items(
            conn, clock, items, user_id=session.user_id, ttl_seconds=ttl_seconds
        )
        carts_repo.lock_cart(conn, cart.cart_id, snapshot_hash=snapshot_hash, updated_at=now)

        snapshot_json = canonical_json({
            "session_id": session_id, "cart_id": cart.cart_id, "version": cart.version,
            "currency": cart.currency, "lines": lines, "subtotal_minor": cart.subtotal_minor,
            "tax_minor": cart.tax_minor, "total_minor": cart.total_minor,
        })
        confirmations_repo.insert(
            conn, confirmation_id=confirmation_id, session_id=session_id, cart_id=cart.cart_id,
            cart_version=cart.version, snapshot_hash=snapshot_hash, snapshot_json=snapshot_json,
            currency=cart.currency, subtotal_minor=cart.subtotal_minor, tax_minor=cart.tax_minor,
            total_minor=cart.total_minor, effective_cap_minor=cap.effective_cap_minor,
            requested_at=now, expires_at=expires_at,
        )
        session_service.transition(conn, clock, session_id, "awaiting_confirmation")

        budget_service.record(conn, clock, session_id, result, actor="agent",
                              agent_run_id=agent_run_id, confirmation_id=confirmation_id,
                              cart_id=cart.cart_id)
        audit_service.append(
            conn, session_id=session_id, event_type="CONFIRMATION_REQUIRED", actor="agent",
            agent_run_id=agent_run_id, occurred_at=now, outcome="success",
            input_data={"cart_id": cart.cart_id}, cart_id=cart.cart_id, cart_version=cart.version,
            confirmation_id=confirmation_id,
            result_data={"confirmation_id": confirmation_id, "snapshot_hash": snapshot_hash,
                          "total_minor": cart.total_minor, "expires_at": expires_at, "hold_ids": hold_ids},
        )
    return confirmations_repo.get(conn, confirmation_id)


def _add_seconds(utc_timestamp: str, seconds: int) -> str:
    from src.core.clock import format_utc, parse_utc
    return format_utc(parse_utc(utc_timestamp) + __import__("datetime").timedelta(seconds=seconds))


def get_current(conn, session_id: str) -> Optional[Confirmation]:
    return confirmations_repo.get_current(conn, session_id)


def approve(
    conn, clock: Clock, session_id: str, confirmation_id: str, *, user_id: str,
    submitted_snapshot_hash: str,
) -> Confirmation:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    if session.user_id != user_id:
        raise RefusalError("SESSION_ACCESS_DENIED", "this user does not own the session")
    if session.status != "awaiting_confirmation":
        raise RefusalError("INVALID_STATE", f"session is not awaiting confirmation: {session.status}")

    confirmation = confirmations_repo.get(conn, confirmation_id)
    if confirmation is None or confirmation.session_id != session_id:
        raise RefusalError("CONFIRMATION_MISSING", "no such confirmation for this session")
    if confirmation.status != "pending":
        raise RefusalError("CONFIRMATION_ALREADY_USED", f"confirmation is {confirmation.status}")
    if clock.utc() >= confirmation.expires_at:
        raise RefusalError("CONFIRMATION_EXPIRED", "the confirmation has expired")

    cart = carts_repo.get_cart(conn, confirmation.cart_id)
    items = carts_repo.list_active_items(conn, confirmation.cart_id)
    recomputed_hash = compute_snapshot_hash(
        session_id=session_id, cart_id=cart.cart_id, version=cart.version, currency=cart.currency,
        lines=_cart_lines(items), subtotal_minor=cart.subtotal_minor, tax_minor=cart.tax_minor,
        total_minor=cart.total_minor,
    )
    if submitted_snapshot_hash != confirmation.snapshot_hash or recomputed_hash != confirmation.snapshot_hash:
        raise RefusalError("CONFIRMATION_STALE", "the cart hash does not match the confirmation snapshot")

    with transaction(conn):
        now_utc = clock.utc()
        now_existing = clock.existing()
        confirmations_repo.approve(conn, confirmation_id, decided_by_user_id=user_id, decided_at=now_utc)
        sessions_repo.set_confirmed_at(conn, session_id, confirmed_at=now_existing, updated_at=now_existing)
        audit_service.append(
            conn, session_id=session_id, event_type="CONFIRMATION_RECEIVED", actor="user",
            actor_user_id=user_id, occurred_at=now_utc, outcome="success",
            input_data={"confirmation_id": confirmation_id, "decision": "approved"},
            result_data={"confirmation_id": confirmation_id}, confirmation_id=confirmation_id,
            cart_id=confirmation.cart_id, cart_version=confirmation.cart_version,
        )
    return confirmations_repo.get(conn, confirmation_id)


def decline(
    conn, clock: Clock, session_id: str, confirmation_id: str, *, user_id: str,
    note: Optional[str] = None,
) -> Confirmation:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    if session.user_id != user_id:
        raise RefusalError("CONFIRMATION_NOT_OWNER", "this user does not own the session")

    confirmation = confirmations_repo.get(conn, confirmation_id)
    if confirmation is None or confirmation.session_id != session_id:
        raise RefusalError("CONFIRMATION_MISSING", "no such confirmation for this session")
    if confirmation.status != "pending":
        raise RefusalError("CONFIRMATION_ALREADY_USED", f"confirmation is {confirmation.status}")

    with transaction(conn):
        now_utc = clock.utc()
        confirmations_repo.decline(conn, confirmation_id, decided_by_user_id=user_id, decided_at=now_utc,
                                    decision_note=note)

        cart = carts_repo.get_cart(conn, confirmation.cart_id)
        hold_ids = [it.hold_id for it in carts_repo.list_active_items(conn, cart.cart_id) if it.hold_id]
        inventory_service.release_holds(conn, clock, hold_ids)
        carts_repo.reopen_cart(conn, cart.cart_id, updated_at=clock.utc())
        session_service.transition(conn, clock, session_id, "awaiting_input",
                                    last_error_code="confirmation_declined")

        audit_service.append(
            conn, session_id=session_id, event_type="CONFIRMATION_DECLINED", actor="user",
            actor_user_id=user_id, occurred_at=now_utc, outcome="info",
            input_data={"confirmation_id": confirmation_id, "note": note},
            result_data={"confirmation_id": confirmation_id}, confirmation_id=confirmation_id,
            cart_id=confirmation.cart_id, cart_version=confirmation.cart_version,
        )
    return confirmations_repo.get(conn, confirmation_id)


def supersede_pending(conn, clock: Clock, session_id: str, *, user_id: str) -> Optional[Confirmation]:
    """The user asked for a change while an approval was waiting: close that approval (it can no
    longer be approved), release its holds and reopen the cart so the agent can re-plan. Must run
    inside the caller's transaction, before the session moves on."""
    confirmation = confirmations_repo.get_current(conn, session_id)
    if confirmation is None:
        return None
    confirmations_repo.close(conn, confirmation.confirmation_id, status="invalidated", closed_reason="cart_changed")
    cart = carts_repo.get_cart(conn, confirmation.cart_id)
    hold_ids = [it.hold_id for it in carts_repo.list_active_items(conn, cart.cart_id) if it.hold_id]
    inventory_service.release_holds(conn, clock, hold_ids)
    carts_repo.reopen_cart(conn, cart.cart_id, updated_at=clock.utc())
    audit_service.append(
        conn, session_id=session_id, event_type="CONFIRMATION_INVALIDATED", actor="user",
        actor_user_id=user_id, occurred_at=clock.utc(), outcome="info",
        input_data={"confirmation_id": confirmation.confirmation_id, "reason": "user asked to re-plan"},
        result_data={"closed_reason": "cart_changed"}, confirmation_id=confirmation.confirmation_id,
        cart_id=confirmation.cart_id, cart_version=confirmation.cart_version,
    )
    return confirmations_repo.get(conn, confirmation.confirmation_id)


def expire_if_due(conn, clock: Clock, confirmation: Confirmation) -> Confirmation:
    if confirmation.status != "pending" or clock.utc() < confirmation.expires_at:
        return confirmation
    with transaction(conn):
        confirmations_repo.close(conn, confirmation.confirmation_id, status="expired", closed_reason="timeout")
        cart = carts_repo.get_cart(conn, confirmation.cart_id)
        hold_ids = [it.hold_id for it in carts_repo.list_active_items(conn, cart.cart_id) if it.hold_id]
        inventory_service.expire_holds(conn, clock, hold_ids)
        carts_repo.reopen_cart(conn, cart.cart_id, updated_at=clock.utc())
        session_service.transition(conn, clock, confirmation.session_id, "executing")
        audit_service.append(
            conn, session_id=confirmation.session_id, event_type="CONFIRMATION_EXPIRED", actor="system",
            occurred_at=clock.utc(), outcome="info",
            input_data={"confirmation_id": confirmation.confirmation_id},
            result_data={"closed_reason": "timeout"},
            confirmation_id=confirmation.confirmation_id,
        )
    return confirmations_repo.get(conn, confirmation.confirmation_id)
