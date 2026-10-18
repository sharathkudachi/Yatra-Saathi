"""The final booking transaction (section 8.5). Mocked provider only.

Order, exactly as approved:
  BOOKING_ATTEMPT (own transaction, always written first)
  then, inside one BEGIN IMMEDIATE transaction:
    1. reload/verify prices from inventory_calendar
    2. recalculate item totals
    3. calculate 12% tax
    4. calculate final total
    5. compare with the effective cap (re-read live)
    6. validate the confirmation
    7. validate the cart hash
    8. mock-book: bookings, booking_items, payments, holds -> confirmed,
       cart -> booked, confirmation -> consumed, session -> completed
  Any failure: rollback, then commit BOOKING_REFUSED/BOOKING_FAILED separately,
  release holds where relevant.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.contracts.codes import RefusalError
from src.core import money
from src.core.clock import Clock
from src.core.hashing import sha256_hex
from src.core.ids import new_booking_reference, new_id
from src.db.repositories import bookings as bookings_repo
from src.db.repositories import carts as carts_repo
from src.db.repositories import confirmations as confirmations_repo
from src.db.repositories import sessions as sessions_repo
from src.db.unit_of_work import transaction
from src.services import audit_service, budget_service, confirmation_service, inventory_service
from src.services import pricing_service, session_service
from src.services.mock_booking_provider import MockBookingProvider


@dataclass(frozen=True)
class BookingOutcome:
    booking_id: str
    booking_reference: str
    total_amount: str


def _hold_ids_for_cart(conn, cart_id: str) -> list[str]:
    return [it.hold_id for it in carts_repo.list_active_items(conn, cart_id) if it.hold_id]


def _already_booked(conn, session_id: str) -> bool:
    return bookings_repo.get_by_session_confirmed(conn, session_id) is not None


def _write_refusal(conn, clock: Clock, session_id: str, *, event_type: str, code: str, message: str,
                    confirmation_id: Optional[str] = None, cart_id: Optional[str] = None,
                    booking_id: Optional[str] = None) -> None:
    with transaction(conn):
        audit_service.append(
            conn, session_id=session_id, event_type=event_type, actor="system",
            occurred_at=clock.utc(), outcome="refused" if event_type == "BOOKING_REFUSED" else "failed",
            input_data={}, result_data={}, reason_code=code, reason=message,
            confirmation_id=confirmation_id, cart_id=cart_id, booking_id=booking_id,
        )


def attempt_booking(
    conn, clock: Clock, session_id: str, confirmation_id: str, *, tax_rate_bp: int,
    provider: Optional[MockBookingProvider] = None,
) -> BookingOutcome:
    provider = provider or MockBookingProvider()

    if _already_booked(conn, session_id):
        _write_refusal(conn, clock, session_id, event_type="BOOKING_REFUSED",
                        code="SESSION_ALREADY_BOOKED", message="this session already has a booking",
                        confirmation_id=confirmation_id)
        raise RefusalError("SESSION_ALREADY_BOOKED", "this session already has a booking")

    with transaction(conn):
        audit_service.append(
            conn, session_id=session_id, event_type="BOOKING_ATTEMPT", actor="system",
            occurred_at=clock.utc(), outcome="info", input_data={"confirmation_id": confirmation_id},
            result_data={}, confirmation_id=confirmation_id,
        )

    try:
        with transaction(conn):
            outcome = _final_check_and_book(conn, clock, session_id, confirmation_id,
                                            tax_rate_bp=tax_rate_bp, provider=provider)
        return outcome
    except _PriceChanged as exc:
        confirmations_repo.close(conn, confirmation_id, status="invalidated", closed_reason="price_changed")
        cart = carts_repo.get_cart(conn, exc.cart_id)
        if cart is not None:
            inventory_service.release_holds(conn, clock, _hold_ids_for_cart(conn, cart.cart_id))
            carts_repo.reopen_cart(conn, cart.cart_id, updated_at=clock.utc())
        session_service.transition(conn, clock, session_id, "executing")
        _write_refusal(conn, clock, session_id, event_type="BOOKING_REFUSED", code="PRICE_CHANGED",
                        message=str(exc), confirmation_id=confirmation_id)
        raise RefusalError("PRICE_CHANGED", str(exc)) from exc
    except _CapExceeded as exc:
        confirmations_repo.close(conn, confirmation_id, status="invalidated", closed_reason="cart_changed")
        cart = carts_repo.get_cart(conn, exc.cart_id)
        if cart is not None:
            inventory_service.release_holds(conn, clock, _hold_ids_for_cart(conn, cart.cart_id))
            carts_repo.reopen_cart(conn, cart.cart_id, updated_at=clock.utc())
        session_service.transition(conn, clock, session_id, "executing")
        with transaction(conn):
            budget_service.record(conn, clock, session_id, exc.result, actor="system",
                                  confirmation_id=confirmation_id, cart_id=exc.cart_id)
            audit_service.append(
                conn, session_id=session_id, event_type="BOOKING_REFUSED", actor="system",
                occurred_at=clock.utc(), outcome="refused", input_data={},
                result_data={}, reason_code="SPEND_CAP_EXCEEDED", reason=str(exc),
                confirmation_id=confirmation_id,
            )
        raise RefusalError("SPEND_CAP_EXCEEDED", str(exc)) from exc
    except RefusalError as exc:
        _write_refusal(conn, clock, session_id, event_type="BOOKING_REFUSED", code=exc.code,
                        message=exc.message, confirmation_id=confirmation_id)
        raise
    except _ProviderFailure as exc:
        cart = carts_repo.get_cart(conn, exc.cart_id)
        if cart is not None:
            inventory_service.release_holds(conn, clock, _hold_ids_for_cart(conn, cart.cart_id))
        session_service.transition(conn, clock, session_id, "failed", last_error_code="booking_failed")
        _write_refusal(conn, clock, session_id, event_type="BOOKING_FAILED", code="BOOKING_FAILED",
                        message=str(exc), confirmation_id=confirmation_id)
        raise RuntimeError(str(exc)) from exc


class _PriceChanged(Exception):
    def __init__(self, message: str, cart_id: str):
        super().__init__(message)
        self.cart_id = cart_id


class _CapExceeded(Exception):
    def __init__(self, message: str, cart_id: str, result):
        super().__init__(message)
        self.cart_id = cart_id
        self.result = result


class _ProviderFailure(Exception):
    def __init__(self, message: str, cart_id: str):
        super().__init__(message)
        self.cart_id = cart_id


def _final_check_and_book(conn, clock: Clock, session_id: str, confirmation_id: str, *,
                           tax_rate_bp: int, provider: MockBookingProvider) -> BookingOutcome:
    session = sessions_repo.get(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session: {session_id}")

    confirmation = confirmations_repo.get(conn, confirmation_id)
    if confirmation is None or confirmation.session_id != session_id:
        raise RefusalError("CONFIRMATION_MISSING", "no such confirmation for this session")
    if confirmation.status != "approved":
        if confirmation.status == "pending":
            raise RefusalError("CONFIRMATION_MISSING", "the confirmation has not been approved")
        raise RefusalError("CONFIRMATION_ALREADY_USED", f"confirmation is {confirmation.status}")
    if clock.utc() >= confirmation.expires_at:
        raise RefusalError("CONFIRMATION_EXPIRED", "the confirmation has expired")
    if confirmation.decided_by_user_id is None:
        raise RefusalError("CONFIRMATION_NOT_OWNER", "the confirmation was never decided by a user")

    cart = carts_repo.get_cart(conn, confirmation.cart_id)
    items = carts_repo.list_active_items(conn, cart.cart_id)

    # 1. reload/verify prices from inventory_calendar
    repriced = pricing_service.reprice_all(conn, items, cart.currency)
    if any(r.price_changed for r in repriced):
        raise _PriceChanged("one or more prices changed between confirmation and booking", cart.cart_id)

    # 2-4. recalc item totals, tax, final total
    totals = pricing_service.totals_for_lines(repriced, tax_rate_bp)

    # 5. compare with the effective cap (re-read live)
    result = budget_service.evaluate(conn, session_id, checkpoint="final",
                                      subtotal_minor=totals.subtotal_minor, tax_minor=totals.tax_minor,
                                      total_minor=totals.total_minor)
    if not result.passed:
        # The failing BUDGET_CHECK must survive this transaction's rollback, so it is
        # written by the caller (attempt_booking) once this transaction has been rolled back.
        raise _CapExceeded("final total exceeds the effective cap", cart.cart_id, result)
    budget_service.record(conn, clock, session_id, result, actor="system",
                          confirmation_id=confirmation_id, cart_id=cart.cart_id)

    # 6. validate the confirmation (already checked above: approved, session, unexpired, unused, owner-decided)

    # 7. validate the cart hash (recomputed = confirmation = cart)
    recomputed_hash = confirmation_service.compute_snapshot_hash(
        session_id=session_id, cart_id=cart.cart_id, version=cart.version, currency=cart.currency,
        lines=[{"inventory_id": r.cart_item.inventory_id, "for_date": r.cart_item.for_date,
                 "units": r.cart_item.units, "unit_price_minor": r.live_unit_price_minor} for r in repriced],
        subtotal_minor=totals.subtotal_minor, tax_minor=totals.tax_minor, total_minor=totals.total_minor,
    )
    if recomputed_hash != confirmation.snapshot_hash:
        raise _PriceChanged("cart hash no longer matches the confirmation snapshot", cart.cart_id)

    # 8. mock-book
    provider_result = provider.charge(amount_minor=totals.total_minor, currency=cart.currency)
    if not provider_result.success:
        raise _ProviderFailure(provider_result.failure_code or "provider failure", cart.cart_id)

    now_existing = clock.existing()
    booking_id = new_id("bkg")
    booking_reference = new_booking_reference()
    idempotency_key = f"idem_{sha256_hex(confirmation_id)[:16]}"
    total_amount = money.format_minor(totals.total_minor)
    tax_amount = money.format_minor(totals.tax_minor)

    bookings_repo.insert_booking(
        conn, booking_id=booking_id, user_id=session.user_id, trip_id=session.trip_id,
        booking_reference=booking_reference, total_amount=total_amount, currency=cart.currency,
        tax_amount=tax_amount, idempotency_key=idempotency_key, created_at=now_existing,
    )
    for r in repriced:
        line = bookings_repo.BookingLine(
            entity_type=r.cart_item.entity_type, entity_id=r.cart_item.entity_id,
            inventory_id=r.cart_item.inventory_id, title=r.cart_item.kind,
            for_date=r.cart_item.for_date, units=r.cart_item.units,
            unit_price=money.format_minor(r.live_unit_price_minor),
            line_total=money.format_minor(money.line_total_minor(r.cart_item.units, r.live_unit_price_minor)),
            currency=cart.currency,
        )
        bookings_repo.insert_booking_item(conn, booking_item_id=new_id("bit"), booking_id=booking_id,
                                          line=line, updated_at=now_existing)
    payment_idempotency_key = f"pidem_{sha256_hex(confirmation_id + ':payment')[:16]}"
    bookings_repo.insert_payment(
        conn, payment_id=new_id("pay"), booking_id=booking_id, amount=total_amount,
        currency=cart.currency, gateway_reference=provider_result.gateway_reference,
        idempotency_key=payment_idempotency_key, created_at=now_existing,
    )

    hold_ids = _hold_ids_for_cart(conn, cart.cart_id)
    inventory_service.confirm_holds(conn, clock, hold_ids, booking_id=booking_id)
    carts_repo.set_status(conn, cart.cart_id, status="booked", updated_at=clock.utc())
    confirmations_repo.consume(conn, confirmation_id, consumed_at=clock.utc(), booking_id=booking_id)
    sessions_repo.set_completed(conn, session_id, spend_committed=total_amount, updated_at=now_existing)

    audit_service.append(
        conn, session_id=session_id, event_type="BOOKING_SUCCESS", actor="system",
        occurred_at=clock.utc(), outcome="success",
        input_data={"confirmation_id": confirmation_id},
        result_data={"booking_id": booking_id, "booking_reference": booking_reference,
                      "total_amount": total_amount, "gateway_reference": provider_result.gateway_reference},
        confirmation_id=confirmation_id, cart_id=cart.cart_id, booking_id=booking_id,
    )
    return BookingOutcome(booking_id=booking_id, booking_reference=booking_reference,
                          total_amount=total_amount)
