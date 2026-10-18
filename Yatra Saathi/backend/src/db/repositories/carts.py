"""Repository for `agent_carts` and `agent_cart_items`."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Cart:
    cart_id: str
    session_id: str
    status: str
    version: int
    currency: str
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    snapshot_hash: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Cart":
        return cls(row["cart_id"], row["session_id"], row["status"], row["version"],
                   row["currency"], row["subtotal_minor"], row["tax_minor"], row["total_minor"],
                   row["snapshot_hash"], row["created_at"], row["updated_at"])


@dataclass(frozen=True)
class CartItem:
    cart_item_id: str
    cart_id: str
    session_id: str
    item_group_id: str
    kind: str
    entity_type: str
    entity_id: str
    inventory_id: str
    for_date: str
    units: int
    unit_price_minor: int
    line_total_minor: int
    source_event_id: str
    source_offer_index: int
    hold_id: Optional[str]
    status: str
    added_in_version: int
    removed_in_version: Optional[int]
    added_at: str
    removed_at: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "CartItem":
        return cls(**{k: row[k] for k in row.keys()})


def get_active_cart(conn: sqlite3.Connection, session_id: str) -> Optional[Cart]:
    row = conn.execute(
        "SELECT * FROM agent_carts WHERE session_id = ? AND status IN ('open','locked')",
        (session_id,),
    ).fetchone()
    return Cart.from_row(row) if row else None


def get_booked_cart(conn: sqlite3.Connection, session_id: str) -> Optional[Cart]:
    """The session's booked cart, if any (a session books at most once)."""
    row = conn.execute(
        "SELECT * FROM agent_carts WHERE session_id = ? AND status = 'booked' ORDER BY updated_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return Cart.from_row(row) if row else None


def get_cart(conn: sqlite3.Connection, cart_id: str) -> Optional[Cart]:
    row = conn.execute("SELECT * FROM agent_carts WHERE cart_id = ?", (cart_id,)).fetchone()
    return Cart.from_row(row) if row else None


def insert_cart(conn: sqlite3.Connection, *, cart_id: str, session_id: str, currency: str,
                 created_at: str) -> None:
    conn.execute(
        """INSERT INTO agent_carts (cart_id, session_id, status, version, currency,
             subtotal_minor, tax_minor, total_minor, snapshot_hash, created_at, updated_at)
           VALUES (?, ?, 'open', 1, ?, 0, 0, 0, NULL, ?, ?)""",
        (cart_id, session_id, currency, created_at, created_at),
    )


def update_totals(conn: sqlite3.Connection, cart_id: str, *, version: int, subtotal_minor: int,
                   tax_minor: int, total_minor: int, updated_at: str) -> None:
    conn.execute(
        """UPDATE agent_carts SET version = ?, subtotal_minor = ?, tax_minor = ?, total_minor = ?,
             updated_at = ? WHERE cart_id = ?""",
        (version, subtotal_minor, tax_minor, total_minor, updated_at, cart_id),
    )


def lock_cart(conn: sqlite3.Connection, cart_id: str, *, snapshot_hash: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE agent_carts SET status = 'locked', snapshot_hash = ?, updated_at = ? WHERE cart_id = ?",
        (snapshot_hash, updated_at, cart_id),
    )


def reopen_cart(conn: sqlite3.Connection, cart_id: str, *, updated_at: str) -> None:
    conn.execute(
        "UPDATE agent_carts SET status = 'open', updated_at = ? WHERE cart_id = ?",
        (updated_at, cart_id),
    )


def set_status(conn: sqlite3.Connection, cart_id: str, *, status: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE agent_carts SET status = ?, updated_at = ? WHERE cart_id = ?",
        (status, updated_at, cart_id),
    )


def list_active_items(conn: sqlite3.Connection, cart_id: str) -> list[CartItem]:
    cur = conn.execute(
        "SELECT * FROM agent_cart_items WHERE cart_id = ? AND status = 'active' ORDER BY added_at",
        (cart_id,),
    )
    return [CartItem.from_row(r) for r in cur.fetchall()]


def list_items_by_group(conn: sqlite3.Connection, cart_id: str, item_group_id: str) -> list[CartItem]:
    cur = conn.execute(
        "SELECT * FROM agent_cart_items WHERE cart_id = ? AND item_group_id = ? AND status = 'active'",
        (cart_id, item_group_id),
    )
    return [CartItem.from_row(r) for r in cur.fetchall()]


def insert_item(conn: sqlite3.Connection, item: CartItem) -> None:
    conn.execute(
        """INSERT INTO agent_cart_items (
             cart_item_id, cart_id, session_id, item_group_id, kind, entity_type, entity_id,
             inventory_id, for_date, units, unit_price_minor, line_total_minor, source_event_id,
             source_offer_index, hold_id, status, added_in_version, removed_in_version,
             added_at, removed_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item.cart_item_id, item.cart_id, item.session_id, item.item_group_id, item.kind,
         item.entity_type, item.entity_id, item.inventory_id, item.for_date, item.units,
         item.unit_price_minor, item.line_total_minor, item.source_event_id,
         item.source_offer_index, item.hold_id, item.status, item.added_in_version,
         item.removed_in_version, item.added_at, item.removed_at),
    )


def remove_item(conn: sqlite3.Connection, cart_item_id: str, *, removed_in_version: int,
                 removed_at: str) -> None:
    conn.execute(
        """UPDATE agent_cart_items SET status = 'removed', removed_in_version = ?, removed_at = ?
           WHERE cart_item_id = ?""",
        (removed_in_version, removed_at, cart_item_id),
    )


def set_hold_id(conn: sqlite3.Connection, cart_item_id: str, *, hold_id: str) -> None:
    conn.execute("UPDATE agent_cart_items SET hold_id = ? WHERE cart_item_id = ?", (hold_id, cart_item_id))
