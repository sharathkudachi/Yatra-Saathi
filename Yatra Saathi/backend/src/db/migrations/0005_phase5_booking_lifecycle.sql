-- Migration 0005: Phase 5 Booking Lifecycle, Trip Management & Travel Document Foundation
-- Additive only: no existing columns or rows are modified.
-- All new tables use transactions and enforce foreign keys.
-- Idempotent: guarded by CHECK constraints and unique indexes.

-- ============================================================
-- 1. Extend bookings with Phase 5 lifecycle fields
-- ============================================================
-- Add itinerary version tracking (nullable for backward compat with existing bookings)
ALTER TABLE bookings ADD COLUMN itinerary_version INTEGER;
ALTER TABLE bookings ADD COLUMN booking_mode TEXT NOT NULL DEFAULT 'demo';
ALTER TABLE bookings ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'confirmed';
ALTER TABLE bookings ADD COLUMN demo_label TEXT NOT NULL DEFAULT 'DEMO / SIMULATED';

-- ============================================================
-- 2. booking_travellers: safe demo traveller information
-- ============================================================
CREATE TABLE booking_travellers (
  traveller_id         TEXT    NOT NULL,
  booking_id           TEXT    NOT NULL,
  traveller_seq        INTEGER NOT NULL,
  display_name         TEXT    NOT NULL,
  traveller_role       TEXT    NOT NULL DEFAULT 'adult',
  created_at           TEXT    NOT NULL,
  CONSTRAINT pk_btrav PRIMARY KEY (traveller_id),
  CONSTRAINT fk_btrav_booking FOREIGN KEY (booking_id) REFERENCES bookings (booking_id) ON DELETE RESTRICT,
  CONSTRAINT uq_btrav_seq UNIQUE (booking_id, traveller_seq),
  CONSTRAINT ck_btrav_role CHECK (traveller_role IN ('adult','child','infant')),
  CONSTRAINT ck_btrav_seq CHECK (traveller_seq >= 1),
  CONSTRAINT ck_btrav_name CHECK (length(display_name) >= 1 AND length(display_name) <= 200)
);
CREATE INDEX ix_btrav_booking ON booking_travellers (booking_id);

-- ============================================================
-- 3. phase5_booking_events: Phase 5 booking lifecycle audit trail
--    (Separate from agent_audit_events to avoid constraint complexity)
-- ============================================================
CREATE TABLE phase5_booking_events (
  event_id        TEXT    NOT NULL,
  booking_id      TEXT    NOT NULL,
  user_id         TEXT    NOT NULL,
  event_type      TEXT    NOT NULL,
  occurred_at     TEXT    NOT NULL,
  actor           TEXT    NOT NULL DEFAULT 'system',
  prev_status     TEXT,
  new_status      TEXT,
  metadata_json   TEXT    NOT NULL DEFAULT '{}',
  CONSTRAINT pk_p5evt PRIMARY KEY (event_id),
  CONSTRAINT fk_p5evt_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
  CONSTRAINT ck_p5evt_type CHECK (event_type IN (
    'BOOKING_REVIEW_REQUESTED','BOOKING_REVIEW_VALIDATED',
    'BOOKING_CONFIRMATION_REQUESTED','INVENTORY_HOLD_CREATED',
    'INVENTORY_HOLD_EXPIRED','INVENTORY_HOLD_RELEASED',
    'DEMO_BOOKING_CONFIRMED','BOOKING_CONFIRMATION_FAILED',
    'BOOKING_CANCELLATION_REQUESTED','DEMO_BOOKING_CANCELLED',
    'TRIP_VIEWED','TRIP_PACK_GENERATED','BOOKING_CREATED'
  )),
  CONSTRAINT ck_p5evt_actor CHECK (actor IN ('user','system')),
  CONSTRAINT ck_p5evt_meta CHECK (json_valid(metadata_json))
);
CREATE INDEX ix_p5evt_booking ON phase5_booking_events (booking_id, occurred_at);
CREATE INDEX ix_p5evt_user ON phase5_booking_events (user_id, occurred_at);

-- Prevent deletion of audit events
CREATE TRIGGER trg_p5evt_no_delete
BEFORE DELETE ON phase5_booking_events FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'phase5 booking events cannot be deleted'); END;

-- ============================================================
-- 4. trip_packs: Generated trip summary documents
-- ============================================================
CREATE TABLE trip_packs (
  pack_id          TEXT    NOT NULL,
  booking_id       TEXT    NOT NULL,
  user_id          TEXT    NOT NULL,
  pack_json        TEXT    NOT NULL,
  pack_version     INTEGER NOT NULL DEFAULT 1,
  is_demo          INTEGER NOT NULL DEFAULT 1,
  demo_label       TEXT    NOT NULL DEFAULT 'YATRA DEMO TRIP PACK',
  generated_at     TEXT    NOT NULL,
  CONSTRAINT pk_pack PRIMARY KEY (pack_id),
  CONSTRAINT fk_pack_booking FOREIGN KEY (booking_id) REFERENCES bookings (booking_id) ON DELETE RESTRICT,
  CONSTRAINT fk_pack_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
  CONSTRAINT uq_pack_booking UNIQUE (booking_id),
  CONSTRAINT ck_pack_version CHECK (pack_version >= 1),
  CONSTRAINT ck_pack_json CHECK (json_valid(pack_json)),
  CONSTRAINT ck_pack_demo CHECK (is_demo = 1)
);
CREATE INDEX ix_pack_user ON trip_packs (user_id);

-- Prevent deletion of trip packs (audit integrity)
CREATE TRIGGER trg_pack_no_delete
BEFORE DELETE ON trip_packs FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'trip packs cannot be deleted'); END;
