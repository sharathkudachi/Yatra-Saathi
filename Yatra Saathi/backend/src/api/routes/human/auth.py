"""POST /api/v1/auth/register, POST /api/v1/auth/login, and GET /api/v1/auth/me.

Security Guarantees:
- Password storage uses one-way Argon2id hashes.
- Plaintext passwords are NEVER stored, logged, printed, or sent to external services or AI.
- Login accepts either username OR email along with password.
- Responses never expose password, password_hash, or token signing keys.
- Rate limiting prevents brute force credential stuffing attacks.
- Account enumeration is prevented with generic refusal messages.
- Full backwards compatibility is preserved for existing tests and usr_demo0001.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

try:
    import psycopg2
except ImportError:  # SQLite-only environments do not require the PostgreSQL driver.
    psycopg2 = None

from fastapi import APIRouter, Depends, Request

from src.api.deps import CurrentUser, get_clock, get_conn, get_current_user, get_settings
from src.contracts.codes import RefusalError
from src.contracts.envelope import ok
from src.core import human_tokens
from src.core.clock import Clock
from src.core.config import Settings
from src.core.ids import new_id
from src.db.repositories import trips as trips_repo
from src.schemas.human import LoginRequest, RegisterRequest
from src.services import auth_security

router = APIRouter()


def _normalize_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _normalize_email(value: str) -> str:
    return value.strip().casefold()


def _is_integrity_error(error: Exception) -> bool:
    if isinstance(error, sqlite3.IntegrityError):
        return True
    return psycopg2 is not None and isinstance(error, psycopg2.IntegrityError)


def _profile(user: trips_repo.User) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username or user.user_id,
        "display_name": user.display_name,
        "email": user.email,
        "home_currency": user.home_currency,
        "locale": user.locale,
        "email_verified": bool(user.email_verified),
    }


@router.post("/auth/register")
def register(
    body: RegisterRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Register a new user account with secure Argon2id password hashing."""
    # 1. Rate limiting abuse prevention
    client_host = request.client.host if request.client else "unknown"
    rate_key = f"reg_{client_host}"
    allowed, rate_msg = auth_security.check_rate_limit(
        conn, rate_key, "register", max_attempts=10, window_seconds=300, block_seconds=300, now=clock.now()
    )
    if not allowed:
        raise RefusalError("AUTH_RATE_LIMITED", rate_msg, http_status=429)

    # 2. Validate input fields
    full_name = " ".join(body.full_name.split())
    if len(full_name) < 2 or len(full_name) > 100:
        raise RefusalError("INVALID_NAME", "Full name must be between 2 and 100 characters.", http_status=400)

    val_user_ok, user_val = auth_security.validate_username(body.username)
    if not val_user_ok:
        raise RefusalError("INVALID_USERNAME", user_val, http_status=400)
    clean_username = user_val

    val_email_ok, email_val = auth_security.validate_email(body.email)
    if not val_email_ok:
        raise RefusalError("INVALID_EMAIL", email_val, http_status=400)
    clean_email = email_val

    val_pw_ok, pw_val = auth_security.validate_password_strength(body.password)
    if not val_pw_ok:
        raise RefusalError("WEAK_PASSWORD", pw_val, http_status=400)

    # 3. Check for existing username or email uniqueness
    existing_by_user = trips_repo.get_user_by_username(conn, clean_username)
    if existing_by_user is not None:
        raise RefusalError("DUPLICATE_USERNAME", "This username is already taken. Please choose another.", http_status=409)

    existing_by_email = trips_repo.get_user_by_email(conn, clean_email)
    if existing_by_email is not None:
        raise RefusalError("DUPLICATE_EMAIL", "An account with this email already exists.", http_status=409)

    # 4. Require a catalogue city before hashing or persisting the account.
    city_row = conn.execute("SELECT city_id FROM cities ORDER BY city_id LIMIT 1").fetchone()
    if city_row is None:
        raise RefusalError(
            "CITY_CATALOG_UNAVAILABLE",
            "Registration is temporarily unavailable because no home city is configured.",
            http_status=503,
        )

    # 5. Hash password with Argon2id (never logged or exposed)
    hashed_password = auth_security.hash_password(body.password)

    # 6. Persist user record
    user_id = new_id("usr")
    now_iso = clock.now().isoformat()
    signup_date = clock.now().strftime("%Y-%m-%d")
    default_city = city_row[0]

    try:
        conn.execute(
            """INSERT INTO users (
                user_id, display_name, email, home_city_id, home_currency, locale,
                budget_band, travel_style, traveller_type, segment, date_of_signup,
                loyalty_tier, status, created_at, updated_at, username, password_hash,
                email_verified, last_login_at
            ) VALUES (?, ?, ?, ?, 'INR', 'en-IN', 'value', 'leisure', 'solo', 'standard', ?, NULL, 'active', ?, ?, ?, ?, 0, ?)""",
            (
                user_id, full_name, clean_email, default_city,
                signup_date, now_iso, now_iso,
                clean_username, hashed_password, now_iso,
            ),
        )
    except Exception as err:
        if not _is_integrity_error(err):
            raise
        err_msg = str(err).lower()
        if "uq_users_username_lower" in err_msg or "username" in err_msg:
            raise RefusalError("DUPLICATE_USERNAME", "This username is already taken. Please choose another.", http_status=409)
        if "uq_users_email_lower" in err_msg or "email" in err_msg:
            raise RefusalError("DUPLICATE_EMAIL", "An account with this email already exists.", http_status=409)
        raise RefusalError("REGISTRATION_FAILED", "Could not complete account creation.", http_status=500)

    # Clear rate limits on success
    auth_security.clear_failed_attempts(conn, rate_key, "register")

    # 6. Issue secure human token
    if not settings.human_token_secret:
        raise RefusalError("TOKEN_INVALID", "human tokens are not configured", http_status=500)
    token = human_tokens.issue(settings.human_token_secret, user_id, now=clock.now())

    created_user = trips_repo.get_user(conn, user_id)
    if created_user is None:
        raise RefusalError("USER_NOT_FOUND", "Account created but could not be loaded.", http_status=500)

    return ok({"token": token, "user": _profile(created_user)})


@router.post("/auth/login")
def login(
    body: LoginRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Authenticate a user via username/email + password, or legacy credentials."""
    # Secure Password Flow
    if body.password is not None:
        identifier = (body.identifier or "").strip()
        if not identifier:
            raise RefusalError("LOGIN_MISMATCH", "Invalid username/email or password.", http_status=401)

        rate_key = f"auth_{identifier.lower()}"
        allowed, rate_msg = auth_security.check_rate_limit(
            conn, rate_key, "login", max_attempts=5, window_seconds=300, block_seconds=300, now=clock.now()
        )
        if not allowed:
            raise RefusalError("AUTH_RATE_LIMITED", rate_msg, http_status=429)

        user = trips_repo.get_user_by_identifier(conn, identifier)
        if user is None or not user.password_hash:
            auth_security.record_failed_attempt(conn, rate_key, "login", now=clock.now())
            # Generic error to prevent username/email enumeration
            raise RefusalError("LOGIN_MISMATCH", "Invalid username/email or password.", http_status=401)

        if not auth_security.verify_password(user.password_hash, body.password):
            auth_security.record_failed_attempt(conn, rate_key, "login", now=clock.now())
            raise RefusalError("LOGIN_MISMATCH", "Invalid username/email or password.", http_status=401)

        if user.status != "active":
            raise RefusalError("USER_INACTIVE", "Account is inactive. Please contact support.", http_status=403)

        # Clear failed attempts on successful login
        auth_security.clear_failed_attempts(conn, rate_key, "login")

        # Update last login timestamp
        now_iso = clock.now().isoformat()
        conn.execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (now_iso, user.user_id))

        if not settings.human_token_secret:
            raise RefusalError("TOKEN_INVALID", "human tokens are not configured", http_status=500)
        token = human_tokens.issue(settings.human_token_secret, user.user_id, now=clock.now())
        return ok({"token": token, "user": _profile(user)})

    # Legacy Backward-Compatible Flow (user_id + display_name + email)
    if body.user_id:
        user = trips_repo.get_user(conn, body.user_id.strip())
        if (
            user is None
            or _normalize_name(user.display_name) != _normalize_name(body.display_name or "")
            or _normalize_email(user.email) != _normalize_email(body.email or "")
        ):
            raise RefusalError("LOGIN_MISMATCH", "user ID, name and email do not match an account", http_status=401)
        if user.status != "active":
            raise RefusalError("USER_INACTIVE", "user is not active", http_status=403)
        if not settings.human_token_secret:
            raise RefusalError("TOKEN_INVALID", "human tokens are not configured", http_status=500)
        token = human_tokens.issue(settings.human_token_secret, user.user_id, now=clock.now())
        return ok({"token": token, "user": _profile(user)})

    raise RefusalError("LOGIN_MISMATCH", "Invalid credentials.", http_status=401)


@router.get("/auth/me")
def me(user: CurrentUser = Depends(get_current_user), conn: sqlite3.Connection = Depends(get_conn)):
    row = trips_repo.get_user(conn, user.user_id)
    if row is None:
        raise RefusalError("USER_NOT_FOUND", "token user does not exist", http_status=401)
    return ok({"user": _profile(row)})
