"""Creates/releases the holds backing a locked cart (section 9). This backend
only ever releases or expires holds it created itself."""
from __future__ import annotations

from datetime import timedelta

from src.core.clock import Clock
from src.core.ids import new_id, new_idempotency_key
from src.db.repositories import carts as carts_repo
from src.db.repositories import holds as holds_repo
from src.db.repositories.carts import CartItem


def create_holds_for_cart_items(conn, clock: Clock, items: list[CartItem], *, user_id: str,
                                 ttl_seconds: int) -> list[str]:
    expires_at = _existing_after(clock, ttl_seconds)
    hold_ids: list[str] = []
    for item in items:
        hold_id = new_id("hld")
        idempotency_key = new_idempotency_key("hidem")
        holds_repo.insert(conn, hold_id=hold_id, inventory_id=item.inventory_id, user_id=user_id,
                           units=item.units, idempotency_key=idempotency_key,
                           created_at=clock.existing(), expires_at=expires_at)
        carts_repo.set_hold_id(conn, item.cart_item_id, hold_id=hold_id)
        hold_ids.append(hold_id)
    return hold_ids


def _existing_after(clock: Clock, ttl_seconds: int) -> str:
    from src.core.clock import format_existing
    return format_existing(clock.now() + timedelta(seconds=ttl_seconds))


def release_holds(conn, clock: Clock, hold_ids: list[str]) -> None:
    for hold_id in hold_ids:
        holds_repo.release(conn, hold_id, released_at=clock.existing())


def confirm_holds(conn, clock: Clock, hold_ids: list[str], *, booking_id: str) -> None:
    for hold_id in hold_ids:
        holds_repo.confirm(conn, hold_id, booking_id=booking_id, updated_at=clock.existing())


def expire_holds(conn, clock: Clock, hold_ids: list[str]) -> None:
    for hold_id in hold_ids:
        holds_repo.expire(conn, hold_id, updated_at=clock.existing())
