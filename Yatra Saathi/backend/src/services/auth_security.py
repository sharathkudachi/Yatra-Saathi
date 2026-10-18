"""Secure authentication utilities: Argon2id hashing, validation, rate limiting.

Security Guarantees:
- Passwords are NEVER stored in plaintext.
- Passwords are NEVER logged, printed, or sent to external services / AI.
- Password hashes are one-way Argon2id hashes.
- Login and registration are protected against brute-force abuse via auth_rate_limits.
"""
from __future__ import annotations

import datetime
import re
import sqlite3
from typing import Optional, Tuple

import argon2
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Argon2id password hasher with standard OWASP recommended parameters
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=argon2.Type.ID,
)

_USERNAME_REGEX = re.compile(r"^[a-z0-9_]{3,30}$")
_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

COMMON_WEAK_PASSWORDS = frozenset([
    "password", "password123", "12345678", "123456789", "1234567890",
    "qwertyui", "qwertyuiop", "admin123", "letmein123", "welcome123",
    "iloveyou", "monkey123", "dragon123", "sunshine", "princess",
])


def hash_password(plain_password: str) -> str:
    """Hash password using Argon2id. Never logs or prints password."""
    return _HASHER.hash(plain_password)


def verify_password(password_hash: Optional[str], plain_password: str) -> bool:
    """Verify password against Argon2id hash. Returns False safely on any mismatch."""
    if not password_hash or not plain_password:
        return False
    try:
        return _HASHER.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def validate_username(username: str) -> Tuple[bool, str]:
    """Validate username format: 3-30 lowercase alphanumeric and underscores."""
    if not username:
        return False, "Username is required."
    clean = username.strip().lower()
    if not _USERNAME_REGEX.match(clean):
        return False, "Username must be 3-30 characters and contain only lowercase letters, numbers, and underscores."
    return True, clean


def validate_email(email: str) -> Tuple[bool, str]:
    """Validate email format."""
    if not email:
        return False, "Email address is required."
    clean = email.strip().lower()
    if len(clean) > 320 or not _EMAIL_REGEX.match(clean):
        return False, "A valid email address is required."
    return True, clean


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """Validate password strength."""
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if len(password) > 128:
        return False, "Password cannot exceed 128 characters."
    if password.lower() in COMMON_WEAK_PASSWORDS:
        return False, "Password is too common or easily guessable. Please choose a stronger password."
    return True, ""


def check_rate_limit(
    conn: sqlite3.Connection,
    key: str,
    attempt_type: str,
    max_attempts: int = 5,
    window_seconds: int = 300,
    block_seconds: int = 300,
    now: Optional[datetime.datetime] = None,
) -> Tuple[bool, str]:
    """Check and record authentication attempt in auth_rate_limits table.
    
    Returns (allowed: bool, refusal_message: str).
    """
    now_dt = now or datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.isoformat()

    row = conn.execute(
        """SELECT attempt_count, first_attempt, last_attempt, blocked_until
           FROM auth_rate_limits
           WHERE attempt_key = ? AND attempt_type = ?""",
        (key, attempt_type),
    ).fetchone()

    if row is None:
        return True, ""

    count = row["attempt_count"] if isinstance(row, sqlite3.Row) else row[0]
    first_iso = row["first_attempt"] if isinstance(row, sqlite3.Row) else row[1]
    blocked_iso = row["blocked_until"] if isinstance(row, sqlite3.Row) else row[3]

    if blocked_iso:
        try:
            blocked_dt = datetime.datetime.fromisoformat(blocked_iso)
            if blocked_dt > now_dt:
                remaining_sec = int((blocked_dt - now_dt).total_seconds())
                return False, f"Too many failed attempts. Access temporarily locked for {max(1, remaining_sec)} seconds."
        except Exception:
            pass

    try:
        first_dt = datetime.datetime.fromisoformat(first_iso)
        if (now_dt - first_dt).total_seconds() > window_seconds:
            # Window expired
            return True, ""
    except Exception:
        return True, ""

    if count >= max_attempts:
        blocked_until = (now_dt + datetime.timedelta(seconds=block_seconds)).isoformat()
        conn.execute(
            """UPDATE auth_rate_limits
               SET blocked_until = ?, last_attempt = ?
               WHERE attempt_key = ? AND attempt_type = ?""",
            (blocked_until, now_iso, key, attempt_type),
        )
        return False, f"Too many failed attempts. Access temporarily locked for {block_seconds} seconds."

    return True, ""


def record_failed_attempt(
    conn: sqlite3.Connection,
    key: str,
    attempt_type: str,
    window_seconds: int = 300,
    block_seconds: int = 300,
    max_attempts: int = 5,
    now: Optional[datetime.datetime] = None,
) -> None:
    """Record an authentication failure in auth_rate_limits table."""
    now_dt = now or datetime.datetime.now(datetime.timezone.utc)
    now_iso = now_dt.isoformat()

    row = conn.execute(
        """SELECT attempt_count, first_attempt FROM auth_rate_limits
           WHERE attempt_key = ? AND attempt_type = ?""",
        (key, attempt_type),
    ).fetchone()

    if row is None:
        conn.execute(
            """INSERT INTO auth_rate_limits (attempt_key, attempt_type, attempt_count, first_attempt, last_attempt, blocked_until)
               VALUES (?, ?, 1, ?, ?, NULL)""",
            (key, attempt_type, now_iso, now_iso),
        )
        return

    count = row["attempt_count"] if isinstance(row, sqlite3.Row) else row[0]
    first_iso = row["first_attempt"] if isinstance(row, sqlite3.Row) else row[1]

    try:
        first_dt = datetime.datetime.fromisoformat(first_iso)
        if (now_dt - first_dt).total_seconds() > window_seconds:
            # Reset window
            conn.execute(
                """UPDATE auth_rate_limits
                   SET attempt_count = 1, first_attempt = ?, last_attempt = ?, blocked_until = NULL
                   WHERE attempt_key = ? AND attempt_type = ?""",
                (now_iso, now_iso, key, attempt_type),
            )
            return
    except Exception:
        pass

    new_count = count + 1
    blocked_until = None
    if new_count >= max_attempts:
        blocked_until = (now_dt + datetime.timedelta(seconds=block_seconds)).isoformat()

    conn.execute(
        """UPDATE auth_rate_limits
           SET attempt_count = ?, last_attempt = ?, blocked_until = ?
           WHERE attempt_key = ? AND attempt_type = ?""",
        (new_count, now_iso, blocked_until, key, attempt_type),
    )


def clear_failed_attempts(
    conn: sqlite3.Connection,
    key: str,
    attempt_type: str,
) -> None:
    """Clear failed attempts on successful authentication."""
    conn.execute(
        "DELETE FROM auth_rate_limits WHERE attempt_key = ? AND attempt_type = ?",
        (key, attempt_type),
    )
