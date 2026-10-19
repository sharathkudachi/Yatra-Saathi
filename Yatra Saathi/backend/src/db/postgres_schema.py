"""PostgreSQL DDL schema and idempotent migrations for Yatra Saathi.

Executes all necessary PostgreSQL DDL definitions for user accounts,
sessions, carts, bookings, notifications, emergency services, and catalog tables.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("yatra.db.postgres_schema")

POSTGRES_DDL_STATEMENTS = [
    # 1. Schema migration version tracking
    """CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name VARCHAR(128) NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );""",

    # 2. Reference / Catalog tables
    """CREATE TABLE IF NOT EXISTS currencies (
        iso4217 VARCHAR(3) PRIMARY KEY,
        name VARCHAR(64) NOT NULL,
        symbol VARCHAR(8) NOT NULL,
        exponent INTEGER NOT NULL DEFAULT 2
    );""",

    """CREATE TABLE IF NOT EXISTS countries (
        country_id VARCHAR(32) PRIMARY KEY,
        name VARCHAR(128) NOT NULL,
        iso2 VARCHAR(2) NOT NULL,
        iso3 VARCHAR(3) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS languages (
        language_id VARCHAR(32) PRIMARY KEY,
        bcp47 VARCHAR(32) NOT NULL UNIQUE,
        english_name VARCHAR(128) NOT NULL,
        native_name VARCHAR(128) NOT NULL,
        script VARCHAR(32) NOT NULL,
        rtl INTEGER NOT NULL DEFAULT 0,
        tts_supported INTEGER NOT NULL DEFAULT 0,
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS cities (
        city_id VARCHAR(32) PRIMARY KEY,
        country_id VARCHAR(32),
        name VARCHAR(128) NOT NULL,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
        status VARCHAR(32) NOT NULL DEFAULT 'active'
    );""",

    """CREATE TABLE IF NOT EXISTS airports (
        airport_id VARCHAR(32) PRIMARY KEY,
        city_id VARCHAR(32),
        name VARCHAR(128) NOT NULL,
        iata VARCHAR(3) NOT NULL,
        icao VARCHAR(4),
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
        status VARCHAR(32) NOT NULL DEFAULT 'active'
    );""",

    """CREATE TABLE IF NOT EXISTS airlines (
        airline_id VARCHAR(32) PRIMARY KEY,
        name VARCHAR(128) NOT NULL,
        iata VARCHAR(3) NOT NULL,
        icao VARCHAR(4),
        status VARCHAR(32) NOT NULL DEFAULT 'active'
    );""",

    """CREATE TABLE IF NOT EXISTS hotels (
        hotel_id VARCHAR(32) PRIMARY KEY,
        city_id VARCHAR(32),
        name VARCHAR(128) NOT NULL,
        star_rating INTEGER NOT NULL DEFAULT 3,
        address TEXT,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        status VARCHAR(32) NOT NULL DEFAULT 'active'
    );""",

    """CREATE TABLE IF NOT EXISTS hotel_room_types (
        room_type_id VARCHAR(32) PRIMARY KEY,
        hotel_id VARCHAR(32),
        name VARCHAR(128) NOT NULL,
        max_occupancy INTEGER NOT NULL DEFAULT 2,
        status VARCHAR(32) NOT NULL DEFAULT 'active'
    );""",

    """CREATE TABLE IF NOT EXISTS flights (
        flight_id VARCHAR(32) PRIMARY KEY,
        airline_id VARCHAR(32),
        flight_number VARCHAR(32) NOT NULL,
        origin_airport_id VARCHAR(32) NOT NULL,
        dest_airport_id VARCHAR(32) NOT NULL,
        departs_at VARCHAR(32) NOT NULL,
        arrives_at VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active'
    );""",

    """CREATE TABLE IF NOT EXISTS flight_fares (
        fare_id VARCHAR(32) PRIMARY KEY,
        flight_id VARCHAR(32) NOT NULL,
        cabin_class VARCHAR(32) NOT NULL DEFAULT 'economy',
        baggage_allowance_kg INTEGER NOT NULL DEFAULT 15,
        status VARCHAR(32) NOT NULL DEFAULT 'active'
    );""",

    """CREATE TABLE IF NOT EXISTS inventory_calendar (
        inventory_id VARCHAR(64) PRIMARY KEY,
        entity_type VARCHAR(32) NOT NULL,
        entity_id VARCHAR(32) NOT NULL,
        for_date VARCHAR(10) NOT NULL,
        total_units INTEGER NOT NULL DEFAULT 10,
        booked_units INTEGER NOT NULL DEFAULT 0,
        held_units INTEGER NOT NULL DEFAULT 0,
        closed_to_arrival INTEGER NOT NULL DEFAULT 0,
        min_stay_nights INTEGER NOT NULL DEFAULT 1,
        price VARCHAR(32) NOT NULL DEFAULT '0',
        currency VARCHAR(3) NOT NULL DEFAULT 'INR'
    );""",

    # 3. User Accounts and Authentication (Migration 0007)
    """CREATE TABLE IF NOT EXISTS users (
        user_id VARCHAR(64) PRIMARY KEY,
        display_name VARCHAR(128) NOT NULL,
        email VARCHAR(255) NOT NULL,
        home_city_id VARCHAR(32) NOT NULL REFERENCES cities(city_id),
        home_currency VARCHAR(3) NOT NULL DEFAULT 'INR',
        locale VARCHAR(16) NOT NULL DEFAULT 'en-IN',
        budget_band TEXT NOT NULL,
        travel_style TEXT NOT NULL,
        traveller_type TEXT NOT NULL,
        segment TEXT NOT NULL,
        date_of_signup TEXT NOT NULL,
        loyalty_tier TEXT,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        created_at VARCHAR(32) NOT NULL,
        updated_at TEXT NOT NULL,
        username VARCHAR(64),
        password_hash TEXT,
        email_verified INTEGER NOT NULL DEFAULT 0,
        last_login_at VARCHAR(32)
    );""",

    """CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (LOWER(email));""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_lower ON users (LOWER(username)) WHERE username IS NOT NULL;""",

    """CREATE TABLE IF NOT EXISTS auth_rate_limits (
        attempt_key VARCHAR(255) NOT NULL,
        attempt_type VARCHAR(64) NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 1,
        first_attempt VARCHAR(64) NOT NULL,
        last_attempt VARCHAR(64) NOT NULL,
        blocked_until VARCHAR(64),
        CONSTRAINT pk_auth_rate_limits PRIMARY KEY (attempt_key, attempt_type)
    );""",

    """CREATE INDEX IF NOT EXISTS ix_auth_rate_limits_key ON auth_rate_limits (attempt_key);""",

    """CREATE TABLE IF NOT EXISTS auth_audit_log (
        log_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64),
        event_type VARCHAR(64) NOT NULL,
        ip_address VARCHAR(64),
        user_agent TEXT,
        details TEXT NOT NULL DEFAULT '{}',
        created_at VARCHAR(32) NOT NULL
    );""",

    # 4. Trips & Budgets
    """CREATE TABLE IF NOT EXISTS trips (
        trip_id VARCHAR(64) PRIMARY KEY,
        owner_user_id VARCHAR(64),
        user_id VARCHAR(64),
        title VARCHAR(255) NOT NULL,
        origin_city_id VARCHAR(32),
        destination_city_id VARCHAR(32),
        start_date VARCHAR(10) NOT NULL,
        end_date VARCHAR(10) NOT NULL,
        party_size INTEGER NOT NULL DEFAULT 1,
        adults INTEGER NOT NULL DEFAULT 1,
        children INTEGER NOT NULL DEFAULT 0,
        trip_type VARCHAR(32) NOT NULL DEFAULT 'leisure',
        is_group_trip INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'planning',
        home_currency VARCHAR(3) NOT NULL DEFAULT 'INR',
        notes TEXT,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32)
    );""",

    """CREATE TABLE IF NOT EXISTS budgets (
        budget_id VARCHAR(64) PRIMARY KEY,
        trip_id VARCHAR(64) NOT NULL,
        currency VARCHAR(3) NOT NULL DEFAULT 'INR',
        total VARCHAR(32) NOT NULL,
        total_amount VARCHAR(32),
        committed VARCHAR(32) NOT NULL DEFAULT '0',
        remaining VARCHAR(32) NOT NULL DEFAULT '0',
        accommodation_cap VARCHAR(32),
        transport_cap VARCHAR(32),
        food_cap VARCHAR(32),
        activities_cap VARCHAR(32),
        misc_cap VARCHAR(32),
        alert_threshold_pct INTEGER DEFAULT 80,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32)
    );""",

    """CREATE TABLE IF NOT EXISTS itineraries (
        itinerary_id VARCHAR(64) PRIMARY KEY,
        trip_id VARCHAR(64) NOT NULL,
        name VARCHAR(255) NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        generated_by VARCHAR(64) NOT NULL DEFAULT 'system',
        total_cost VARCHAR(32) NOT NULL DEFAULT '0.00',
        currency VARCHAR(3) NOT NULL DEFAULT 'INR',
        total_duration_minutes INTEGER NOT NULL DEFAULT 0,
        total_carbon_kg DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        optimizer_weights TEXT,
        status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS itinerary_items (
        item_id VARCHAR(64) PRIMARY KEY,
        itinerary_id VARCHAR(64) NOT NULL,
        day_index INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        starts_at VARCHAR(32),
        ends_at VARCHAR(32),
        item_type VARCHAR(32) NOT NULL DEFAULT 'activity',
        entity_type VARCHAR(32),
        entity_id VARCHAR(64),
        title VARCHAR(255) NOT NULL,
        cost VARCHAR(32) NOT NULL DEFAULT '0.00',
        currency VARCHAR(3) NOT NULL DEFAULT 'INR',
        carbon_kg DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        duration_minutes INTEGER NOT NULL DEFAULT 0,
        source VARCHAR(32) NOT NULL DEFAULT 'system',
        explanation TEXT,
        locked INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL
    );""",

    # 5. Agent Sessions, State & Carts (Migration 0001)
    """CREATE TABLE IF NOT EXISTS agent_sessions (
        session_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        trip_id VARCHAR(64),
        goal_text TEXT NOT NULL DEFAULT '',
        goal_language VARCHAR(32) NOT NULL DEFAULT 'en-IN',
        constraints_json TEXT NOT NULL DEFAULT '{}',
        plan_steps_json TEXT NOT NULL DEFAULT '[]',
        current_step VARCHAR(64),
        spend_cap VARCHAR(32),
        spend_committed VARCHAR(32) NOT NULL DEFAULT '0.00',
        currency VARCHAR(3) NOT NULL DEFAULT 'INR',
        requires_confirmation INTEGER NOT NULL DEFAULT 0,
        confirmed_at VARCHAR(32),
        replan_count INTEGER NOT NULL DEFAULT 0,
        last_error_code VARCHAR(64),
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS agent_session_state (
        session_id VARCHAR(64) PRIMARY KEY,
        version INTEGER NOT NULL DEFAULT 1,
        checksum VARCHAR(64) NOT NULL,
        size_bytes INTEGER NOT NULL,
        state_json TEXT NOT NULL DEFAULT '{}',
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS agent_carts (
        cart_id VARCHAR(64) PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        currency VARCHAR(3) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'open',
        version INTEGER NOT NULL DEFAULT 1,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS agent_cart_items (
        item_id VARCHAR(64) PRIMARY KEY,
        cart_id VARCHAR(64) NOT NULL,
        item_group_id VARCHAR(64) NOT NULL,
        entity_type VARCHAR(32) NOT NULL,
        entity_id VARCHAR(64) NOT NULL,
        inventory_id VARCHAR(64) NOT NULL,
        for_date VARCHAR(10) NOT NULL,
        units INTEGER NOT NULL DEFAULT 1,
        unit_price_minor BIGINT NOT NULL,
        line_total_minor BIGINT NOT NULL,
        currency VARCHAR(3) NOT NULL,
        added_at VARCHAR(32) NOT NULL,
        removed_at VARCHAR(32)
    );""",

    """CREATE TABLE IF NOT EXISTS agent_confirmations (
        confirmation_id VARCHAR(64) PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        cart_id VARCHAR(64) NOT NULL,
        cart_version INTEGER NOT NULL,
        cart_hash VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        requested_at VARCHAR(32) NOT NULL,
        expires_at VARCHAR(32) NOT NULL,
        decided_at VARCHAR(32),
        consumed_at VARCHAR(32),
        consumed_by_booking_id VARCHAR(64)
    );""",

    # 6. Holds, Bookings, Travellers, Payments (Migration 0005)
    """CREATE TABLE IF NOT EXISTS holds (
        hold_id VARCHAR(64) PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        cart_id VARCHAR(64),
        inventory_id VARCHAR(64) NOT NULL,
        units INTEGER NOT NULL DEFAULT 1,
        status VARCHAR(32) NOT NULL DEFAULT 'held',
        expires_at VARCHAR(32) NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        idempotency_key VARCHAR(128)
    );""",

    """CREATE TABLE IF NOT EXISTS bookings (
        booking_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        trip_id VARCHAR(64),
        itinerary_id VARCHAR(64),
        booking_reference VARCHAR(64) NOT NULL,
        channel VARCHAR(32) NOT NULL DEFAULT 'agent',
        total_amount VARCHAR(32) NOT NULL,
        currency VARCHAR(3) NOT NULL,
        tax_amount VARCHAR(32) NOT NULL DEFAULT '0',
        status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
        created_at VARCHAR(32) NOT NULL,
        idempotency_key VARCHAR(128) NOT NULL,
        itinerary_version INTEGER,
        booking_mode VARCHAR(32) NOT NULL DEFAULT 'demo',
        lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
        demo_label VARCHAR(64) NOT NULL DEFAULT 'DEMO / SIMULATED'
    );""",

    """CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_ref ON bookings (booking_reference);""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_idempotency ON bookings (idempotency_key);""",

    """CREATE TABLE IF NOT EXISTS booking_items (
        booking_item_id VARCHAR(64) PRIMARY KEY,
        booking_id VARCHAR(64) NOT NULL,
        entity_type VARCHAR(32) NOT NULL,
        entity_id VARCHAR(64) NOT NULL,
        inventory_id VARCHAR(64) NOT NULL,
        title VARCHAR(255) NOT NULL,
        for_date VARCHAR(10) NOT NULL,
        units INTEGER NOT NULL DEFAULT 1,
        unit_price VARCHAR(32) NOT NULL,
        line_total VARCHAR(32) NOT NULL,
        currency VARCHAR(3) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
        created_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS booking_travellers (
        traveller_id VARCHAR(64) PRIMARY KEY,
        booking_id VARCHAR(64) NOT NULL,
        traveller_seq INTEGER NOT NULL,
        display_name VARCHAR(128) NOT NULL,
        traveller_role VARCHAR(32) NOT NULL DEFAULT 'adult',
        created_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS payments (
        payment_id VARCHAR(64) PRIMARY KEY,
        booking_id VARCHAR(64) NOT NULL,
        amount VARCHAR(32) NOT NULL,
        currency VARCHAR(3) NOT NULL,
        method VARCHAR(32) NOT NULL DEFAULT 'simulated',
        status VARCHAR(32) NOT NULL DEFAULT 'completed',
        transaction_ref VARCHAR(128) NOT NULL,
        created_at VARCHAR(32) NOT NULL
    );""",

    # 7. Notifications and Preferences (Migration 0004 & 0006)
    """CREATE TABLE IF NOT EXISTS push_subscriptions (
        subscription_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        endpoint TEXT NOT NULL,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        prefs_json TEXT NOT NULL DEFAULT '{}',
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS notifications_sent (
        notification_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        dedupe_key VARCHAR(128) NOT NULL,
        title VARCHAR(255) NOT NULL,
        body TEXT NOT NULL,
        icon VARCHAR(255),
        url VARCHAR(255),
        data_json TEXT NOT NULL DEFAULT '{}',
        sent_at VARCHAR(32) NOT NULL,
        read_at VARCHAR(32)
    );""",

    """CREATE UNIQUE INDEX IF NOT EXISTS uq_notif_dedupe ON notifications_sent (dedupe_key);""",

    """CREATE TABLE IF NOT EXISTS user_language_preferences (
        user_id VARCHAR(64) PRIMARY KEY,
        preferred_language VARCHAR(16) NOT NULL DEFAULT 'en-IN',
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS phase6_notification_preferences (
        user_id VARCHAR(64) PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 1,
        preferred_language VARCHAR(16) NOT NULL DEFAULT 'en-IN',
        categories_json TEXT NOT NULL DEFAULT '["TRIP_UPCOMING","TRIP_STARTING","BOOKING_CONFIRMED","BOOKING_CANCELLED","HOLD_EXPIRING","HOLD_EXPIRED","TRIP_PACK_READY","ITINERARY_UPDATED","TRAVEL_DAY_REMINDER"]',
        in_app_enabled INTEGER NOT NULL DEFAULT 1,
        browser_enabled INTEGER NOT NULL DEFAULT 1,
        quiet_hours_json TEXT NOT NULL DEFAULT '{"enabled":false,"start":"22:00","end":"08:00"}',
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS phase6_notifications (
        notification_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        event_type VARCHAR(64) NOT NULL DEFAULT 'TRIP_UPCOMING',
        category VARCHAR(64) DEFAULT 'general',
        title VARCHAR(255) NOT NULL,
        body TEXT NOT NULL,
        language VARCHAR(16) NOT NULL DEFAULT 'en-IN',
        is_read INTEGER NOT NULL DEFAULT 0,
        read_at VARCHAR(32),
        trip_id VARCHAR(64),
        booking_id VARCHAR(64),
        dedupe_key VARCHAR(128),
        priority VARCHAR(32) NOT NULL DEFAULT 'normal',
        action_url VARCHAR(255),
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at VARCHAR(32) NOT NULL,
        dismissed_at VARCHAR(32)
    );""",

    """CREATE INDEX IF NOT EXISTS ix_p6notif_user ON phase6_notifications (user_id, created_at);""",
    """CREATE INDEX IF NOT EXISTS ix_p6notif_dedupe ON phase6_notifications (dedupe_key);""",

    """CREATE TABLE IF NOT EXISTS trip_packs (
        pack_id VARCHAR(64) PRIMARY KEY,
        booking_id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        pack_json TEXT NOT NULL,
        pack_version INTEGER NOT NULL DEFAULT 1,
        is_demo INTEGER NOT NULL DEFAULT 1,
        demo_label VARCHAR(128) NOT NULL DEFAULT 'YATRA DEMO TRIP PACK',
        generated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS phase6_emergency_contacts (
        contact_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        name VARCHAR(128) NOT NULL,
        relationship VARCHAR(64) NOT NULL,
        phone_number VARCHAR(32) NOT NULL,
        is_primary INTEGER NOT NULL DEFAULT 1,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS phase6_emergency_events (
        event_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        trip_id VARCHAR(64),
        booking_id VARCHAR(64),
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS phase5_booking_events (
        event_id VARCHAR(64) PRIMARY KEY,
        booking_id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        occurred_at VARCHAR(32) NOT NULL,
        actor VARCHAR(32) NOT NULL DEFAULT 'system',
        prev_status VARCHAR(64),
        new_status VARCHAR(64),
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );""",

    # 8. Emergency Assistance & Trusted Contacts (Phase 6)
    """CREATE TABLE IF NOT EXISTS trusted_contacts (
        contact_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        contact_name VARCHAR(128) NOT NULL,
        relationship VARCHAR(64) NOT NULL,
        phone_number VARCHAR(32) NOT NULL,
        is_primary INTEGER NOT NULL DEFAULT 0,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS emergency_events (
        event_id VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        severity VARCHAR(32) NOT NULL DEFAULT 'high',
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        address TEXT,
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at VARCHAR(32) NOT NULL,
        resolved_at VARCHAR(32)
    );""",

    # 9. Audit Events (Hash-chained ledger)
    """CREATE TABLE IF NOT EXISTS agent_audit_events (
        event_id VARCHAR(64) PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        seq INTEGER NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        occurred_at VARCHAR(32) NOT NULL,
        actor VARCHAR(32) NOT NULL,
        actor_user_id VARCHAR(64),
        agent_run_id VARCHAR(64),
        outcome VARCHAR(32) NOT NULL,
        reason_code VARCHAR(64),
        reason TEXT,
        input_json TEXT NOT NULL DEFAULT '{}',
        result_json TEXT NOT NULL DEFAULT '{}',
        request_id VARCHAR(64),
        caused_by_event_id VARCHAR(64),
        plan_version INTEGER,
        step_id VARCHAR(64),
        cart_id VARCHAR(64),
        cart_version INTEGER,
        confirmation_id VARCHAR(64),
        booking_id VARCHAR(64),
        prev_hash VARCHAR(64),
        hash VARCHAR(64) NOT NULL,
        schema_version INTEGER NOT NULL DEFAULT 1
    );""",

    """CREATE INDEX IF NOT EXISTS ix_audit_session_seq ON agent_audit_events (session_id, seq);""",
    """CREATE INDEX IF NOT EXISTS ix_audit_hash ON agent_audit_events (hash);""",
    """CREATE INDEX IF NOT EXISTS ix_inventory_search ON inventory_calendar (entity_id, for_date, currency);""",
    """CREATE INDEX IF NOT EXISTS ix_flights_search ON flights (origin_airport_id, dest_airport_id, status);""",
    """CREATE INDEX IF NOT EXISTS ix_flight_fares_flight ON flight_fares (flight_id);"""
]


_DEFAULT_CURRENCIES = [
    ("INR", "Indian Rupee", "₹", 2),
    ("USD", "US Dollar", "$", 2),
    ("EUR", "Euro", "€", 2),
    ("GBP", "Pound Sterling", "£", 2),
    ("AED", "UAE Dirham", "د.إ", 2),
    ("SGD", "Singapore Dollar", "S$", 2),
    ("THB", "Thai Baht", "฿", 2),
    ("LKR", "Sri Lankan Rupee", "Rs", 2),
    ("NPR", "Nepalese Rupee", "Rs", 2),
    ("BTN", "Bhutanese Ngultrum", "Nu.", 2),
    ("MVR", "Maldivian Rufiyaa", ".ރ", 2),
    ("JPY", "Japanese Yen", "¥", 0),
    ("KRW", "South Korean Won", "₩", 0),
    ("KWD", "Kuwaiti Dinar", "د.ك", 3),
    ("BHD", "Bahraini Dinar", ".د.ب", 3),
    ("AUD", "Australian Dollar", "A$", 2),
    ("CAD", "Canadian Dollar", "C$", 2),
    ("CHF", "Swiss Franc", "CHF", 2),
    ("MYR", "Malaysian Ringgit", "RM", 2),
    ("IDR", "Indonesian Rupiah", "Rp", 2),
    ("VND", "Vietnamese Dong", "₫", 0),
    ("CNY", "Chinese Yuan", "¥", 2),
    ("QAR", "Qatari Riyal", "ر.ق", 2),
    ("SAR", "Saudi Riyal", "ر.س", 2),
    ("NZD", "New Zealand Dollar", "NZ$", 2),
]


# Additive compatibility migration for databases with the earlier Postgres users table.
# The original SQLite contract requires these profile fields, but existing Postgres rows
# have no values for them; omit NOT NULL/defaults here to preserve those rows unchanged.
POSTGRES_USER_REGISTRATION_MIGRATION = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS home_city_id VARCHAR(32) REFERENCES cities(city_id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS budget_band TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS travel_style TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS traveller_type TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS segment TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS date_of_signup TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS loyalty_tier TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TEXT",
)


def init_postgres_schema(conn: Any) -> int:
    """Applies the PostgreSQL schema idempotently."""
    # Ensure auth_rate_limits has canonical columns if table was created previously with legacy schema
    migration_stmts = [
        "ALTER TABLE auth_rate_limits DROP CONSTRAINT IF EXISTS auth_rate_limits_pkey",
        "ALTER TABLE auth_rate_limits ALTER COLUMN ip_address DROP NOT NULL",
        "ALTER TABLE auth_rate_limits ALTER COLUMN first_attempt_at DROP NOT NULL",
        "ALTER TABLE auth_rate_limits ALTER COLUMN last_attempt_at DROP NOT NULL",
        "ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS attempt_key VARCHAR(255)",
        "ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS attempt_type VARCHAR(64) DEFAULT 'login'",
        "ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 1",
        "ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS first_attempt VARCHAR(64)",
        "ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS last_attempt VARCHAR(64)",
        "ALTER TABLE auth_rate_limits ADD COLUMN IF NOT EXISTS blocked_until VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_auth_rate_limits_key ON auth_rate_limits (attempt_key)",
        # agent_sessions additive columns
        "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS goal_text TEXT DEFAULT ''",
        "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS goal_language VARCHAR(32) DEFAULT 'en-IN'",
        "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS constraints_json TEXT DEFAULT '{}'",
        "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS plan_steps_json TEXT DEFAULT '[]'",
        "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS spend_committed VARCHAR(32) DEFAULT '0.00'",
        "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS confirmed_at VARCHAR(32)",
        "ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(64)",
        # phase6_notifications additive columns
        "ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS event_type VARCHAR(64) DEFAULT 'TRIP_UPCOMING'",
        "ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS language VARCHAR(16) DEFAULT 'en-IN'",
        "ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS is_read INTEGER DEFAULT 0",
        "ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS trip_id VARCHAR(64)",
        "ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS booking_id VARCHAR(64)",
        "ALTER TABLE phase6_notifications ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(128)",
        "CREATE INDEX IF NOT EXISTS ix_p6notif_user ON phase6_notifications (user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_p6notif_dedupe ON phase6_notifications (dedupe_key)",
        # trips additive columns
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(64)",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS origin_city_id VARCHAR(32)",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS adults INTEGER DEFAULT 1",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS children INTEGER DEFAULT 0",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS trip_type VARCHAR(32) DEFAULT 'leisure'",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS is_group_trip INTEGER DEFAULT 0",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS home_currency VARCHAR(3) DEFAULT 'INR'",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        "UPDATE trips SET owner_user_id = user_id WHERE owner_user_id IS NULL AND user_id IS NOT NULL",
        # budgets additive columns
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS total_amount VARCHAR(32)",
        "UPDATE budgets SET total_amount = total WHERE total_amount IS NULL AND total IS NOT NULL",
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS accommodation_cap VARCHAR(32)",
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS transport_cap VARCHAR(32)",
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS food_cap VARCHAR(32)",
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS activities_cap VARCHAR(32)",
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS misc_cap VARCHAR(32)",
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS alert_threshold_pct INTEGER DEFAULT 80",
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        # cities additive columns
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS state VARCHAR(128)",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS country_code VARCHAR(8)",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS region VARCHAR(64)",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS population INTEGER",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS season_profile TEXT",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS peak_months TEXT",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS primary_language VARCHAR(32)",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE cities ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        "UPDATE cities SET lat = latitude WHERE lat IS NULL AND latitude IS NOT NULL",
        "UPDATE cities SET lng = longitude WHERE lng IS NULL AND longitude IS NOT NULL",
        # hotels additive columns
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS property_type VARCHAR(64)",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS address_line TEXT",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS guest_score DOUBLE PRECISION",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS review_count INTEGER",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS checkin_time VARCHAR(16)",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS checkout_time VARCHAR(16)",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS has_xr_scene INTEGER DEFAULT 0",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS base_currency VARCHAR(3) DEFAULT 'INR'",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS chain_code VARCHAR(32)",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS distance_to_centre_km DOUBLE PRECISION",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS created_at VARCHAR(32)",
        "ALTER TABLE hotels ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        "UPDATE hotels SET lat = latitude WHERE lat IS NULL AND latitude IS NOT NULL",
        "UPDATE hotels SET lng = longitude WHERE lng IS NULL AND longitude IS NOT NULL",
        "UPDATE hotels SET address_line = address WHERE address_line IS NULL AND address IS NOT NULL",
        # hotel_room_types additive columns
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS bed_config VARCHAR(64)",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS size_sqm INTEGER",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS max_adults INTEGER DEFAULT 2",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS max_children INTEGER DEFAULT 0",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS smoking_allowed INTEGER DEFAULT 0",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS base_rate VARCHAR(32)",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'INR'",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS total_units INTEGER DEFAULT 10",
        "ALTER TABLE hotel_room_types ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        # airports additive columns
        "ALTER TABLE airports ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION",
        "ALTER TABLE airports ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION",
        "ALTER TABLE airports ADD COLUMN IF NOT EXISTS is_international INTEGER DEFAULT 0",
        "ALTER TABLE airports ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        "UPDATE airports SET lat = latitude WHERE lat IS NULL AND latitude IS NOT NULL",
        "UPDATE airports SET lng = longitude WHERE lng IS NULL AND longitude IS NOT NULL",
        # airlines additive columns
        "ALTER TABLE airlines ADD COLUMN IF NOT EXISTS country_id VARCHAR(32)",
        "ALTER TABLE airlines ADD COLUMN IF NOT EXISTS alliance VARCHAR(64)",
        "ALTER TABLE airlines ADD COLUMN IF NOT EXISTS low_cost INTEGER DEFAULT 0",
        "ALTER TABLE airlines ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        # flights additive columns
        "ALTER TABLE flights ADD COLUMN IF NOT EXISTS aircraft_type VARCHAR(64)",
        "ALTER TABLE flights ADD COLUMN IF NOT EXISTS duration_minutes INTEGER DEFAULT 0",
        "ALTER TABLE flights ADD COLUMN IF NOT EXISTS stops INTEGER DEFAULT 0",
        "ALTER TABLE flights ADD COLUMN IF NOT EXISTS carbon_kg DOUBLE PRECISION DEFAULT 0.0",
        "ALTER TABLE flights ADD COLUMN IF NOT EXISTS cabin_classes VARCHAR(64)",
        "ALTER TABLE flights ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
        # flight_fares additive columns
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'INR'",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS fare_class VARCHAR(32)",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS base_fare VARCHAR(32)",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS taxes VARCHAR(32)",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS refundable INTEGER DEFAULT 0",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS changeable INTEGER DEFAULT 0",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS change_fee VARCHAR(32)",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS baggage_kg INTEGER DEFAULT 15",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS cabin_baggage_kg INTEGER DEFAULT 7",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS seats_total INTEGER DEFAULT 180",
        "ALTER TABLE flight_fares ADD COLUMN IF NOT EXISTS updated_at VARCHAR(32)",
    ]
    for stmt in migration_stmts:
        try:
            conn.execute(stmt)
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"[Postgres Schema] Migration notice on '{stmt}': {exc}")

    for ddl in POSTGRES_DDL_STATEMENTS:
        try:
            conn.execute(ddl)
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"[Postgres Schema] DDL notice: {exc}")

    # Apply after table creation so this works for both fresh and existing databases.
    # Keep the additive migration atomic and fail startup if any statement is rejected.
    try:
        conn.execute("BEGIN")
        for stmt in POSTGRES_USER_REGISTRATION_MIGRATION:
            conn.execute(stmt)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("[Postgres Schema] Registration-column migration failed")
        raise

    # Seed default reference currencies if table is empty
    try:
        cur = conn.execute("SELECT COUNT(*) FROM currencies")
        row = cur.fetchone()
        cnt = row[0] if row else 0
        if cnt == 0:
            for code, name, sym, exp in _DEFAULT_CURRENCIES:
                try:
                    conn.execute(
                        "INSERT INTO currencies (iso4217, name, symbol, exponent) VALUES (?, ?, ?, ?) ON CONFLICT (iso4217) DO NOTHING",
                        (code, name, sym, exp),
                    )
                except Exception:
                    pass
            conn.commit()
            logger.info("[Postgres Schema] Seeded 25 reference currencies.")
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"[Postgres Schema] Notice on currencies seeding: {exc}")

    logger.info("[Postgres Schema] Applied full PostgreSQL DDL schema idempotently.")
    return len(POSTGRES_DDL_STATEMENTS)
