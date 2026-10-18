"""Read-only repositories for `users`, `trips`, `budgets` (existing tables)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class User:
    user_id: str
    display_name: str
    email: str
    home_currency: str
    locale: str
    status: str
    username: Optional[str] = None
    password_hash: Optional[str] = None
    email_verified: int = 0
    last_login_at: Optional[str] = None


def _user_from_row(row: sqlite3.Row | tuple) -> User:
    if isinstance(row, sqlite3.Row) or hasattr(row, "keys"):
        return User(
            user_id=row["user_id"],
            display_name=row["display_name"],
            email=row["email"],
            home_currency=row["home_currency"],
            locale=row["locale"],
            status=row["status"],
            username=row["username"] if "username" in row.keys() else None,
            password_hash=row["password_hash"] if "password_hash" in row.keys() else None,
            email_verified=row["email_verified"] if "email_verified" in row.keys() else 0,
            last_login_at=row["last_login_at"] if "last_login_at" in row.keys() else None,
        )
    return User(
        row[0], row[1], row[2], row[3], row[4], row[5],
        row[6] if len(row) > 6 else None,
        row[7] if len(row) > 7 else None,
        row[8] if len(row) > 8 else 0,
        row[9] if len(row) > 9 else None,
    )


def get_user(conn: sqlite3.Connection, user_id: str) -> Optional[User]:
    row = conn.execute(
        "SELECT user_id, display_name, email, home_currency, locale, status, username, password_hash, email_verified, last_login_at FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return _user_from_row(row)


def get_user_by_identifier(conn: sqlite3.Connection, identifier: str) -> Optional[User]:
    clean = identifier.strip().lower()
    row = conn.execute(
        """SELECT user_id, display_name, email, home_currency, locale, status, username, password_hash, email_verified, last_login_at 
           FROM users 
           WHERE lower(username) = ? OR lower(email) = ?""",
        (clean, clean),
    ).fetchone()
    if not row:
        return None
    return _user_from_row(row)


def get_user_by_username(conn: sqlite3.Connection, username: str) -> Optional[User]:
    clean = username.strip().lower()
    row = conn.execute(
        """SELECT user_id, display_name, email, home_currency, locale, status, username, password_hash, email_verified, last_login_at 
           FROM users 
           WHERE lower(username) = ?""",
        (clean,),
    ).fetchone()
    if not row:
        return None
    return _user_from_row(row)


def get_user_by_email(conn: sqlite3.Connection, email: str) -> Optional[User]:
    clean = email.strip().lower()
    row = conn.execute(
        """SELECT user_id, display_name, email, home_currency, locale, status, username, password_hash, email_verified, last_login_at 
           FROM users 
           WHERE lower(email) = ?""",
        (clean,),
    ).fetchone()
    if not row:
        return None
    return _user_from_row(row)


@dataclass(frozen=True)
class Trip:
    trip_id: str
    owner_user_id: str
    start_date: str
    end_date: str
    party_size: int
    adults: int
    children: int
    home_currency: str
    status: str


def get_trip(conn: sqlite3.Connection, trip_id: str) -> Optional[Trip]:
    row = conn.execute(
        """SELECT trip_id, owner_user_id, start_date, end_date, party_size, adults, children,
                  home_currency, status
           FROM trips WHERE trip_id = ?""",
        (trip_id,),
    ).fetchone()
    if not row:
        return None
    return Trip(row["trip_id"], row["owner_user_id"], row["start_date"], row["end_date"],
                row["party_size"], row["adults"], row["children"], row["home_currency"], row["status"])


@dataclass(frozen=True)
class Budget:
    budget_id: str
    trip_id: str
    total_amount: str
    currency: str
    accommodation_cap: Optional[str]
    transport_cap: Optional[str]
    food_cap: Optional[str]
    activities_cap: Optional[str]
    misc_cap: Optional[str]
    alert_threshold_pct: int


def get_budget_for_trip(conn: sqlite3.Connection, trip_id: str) -> Optional[Budget]:
    row = conn.execute(
        """SELECT budget_id, trip_id, total_amount, currency, accommodation_cap, transport_cap,
                  food_cap, activities_cap, misc_cap, alert_threshold_pct
           FROM budgets WHERE trip_id = ?""",
        (trip_id,),
    ).fetchone()
    if not row:
        return None
    return Budget(row["budget_id"], row["trip_id"], row["total_amount"], row["currency"],
                  row["accommodation_cap"], row["transport_cap"], row["food_cap"],
                  row["activities_cap"], row["misc_cap"], row["alert_threshold_pct"])
