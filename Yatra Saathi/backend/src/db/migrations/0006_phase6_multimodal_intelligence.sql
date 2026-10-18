-- Migration 0006: Phase 6 multimodal intelligence, notifications, and emergency assistance (working copy only).
-- Checksum is enforced by src/db/migrations/runner.py; do not edit once approved.

CREATE TABLE user_language_preferences (
  user_id            TEXT PRIMARY KEY,
  preferred_language TEXT NOT NULL DEFAULT 'en-IN' CHECK (preferred_language IN ('en-IN', 'hi-IN', 'ta-IN')),
  updated_at         TEXT NOT NULL,
  CONSTRAINT fk_langpref_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT
);

CREATE TABLE phase6_notification_preferences (
  user_id            TEXT PRIMARY KEY,
  enabled            INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  preferred_language TEXT NOT NULL DEFAULT 'en-IN' CHECK (preferred_language IN ('en-IN', 'hi-IN', 'ta-IN')),
  categories_json    TEXT NOT NULL DEFAULT '["TRIP_UPCOMING","TRIP_STARTING","BOOKING_CONFIRMED","BOOKING_CANCELLED","HOLD_EXPIRING","HOLD_EXPIRED","TRIP_PACK_READY","ITINERARY_UPDATED","TRAVEL_DAY_REMINDER"]',
  in_app_enabled     INTEGER NOT NULL DEFAULT 1 CHECK (in_app_enabled IN (0, 1)),
  browser_enabled    INTEGER NOT NULL DEFAULT 1 CHECK (browser_enabled IN (0, 1)),
  quiet_hours_json   TEXT NOT NULL DEFAULT '{"enabled":false,"start":"22:00","end":"08:00"}',
  updated_at         TEXT NOT NULL,
  CONSTRAINT fk_p6notpref_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT ck_p6notpref_cat_json CHECK (json_valid(categories_json)),
  CONSTRAINT ck_p6notpref_quiet_json CHECK (json_valid(quiet_hours_json))
);

CREATE TABLE phase6_notifications (
  notification_id    TEXT PRIMARY KEY,
  user_id            TEXT NOT NULL,
  event_type         TEXT NOT NULL CHECK (event_type IN ('TRIP_UPCOMING','TRIP_STARTING','BOOKING_CONFIRMED','BOOKING_CANCELLED','HOLD_EXPIRING','HOLD_EXPIRED','TRIP_PACK_READY','ITINERARY_UPDATED','TRAVEL_DAY_REMINDER')),
  title              TEXT NOT NULL,
  body               TEXT NOT NULL,
  language           TEXT NOT NULL DEFAULT 'en-IN' CHECK (language IN ('en-IN', 'hi-IN', 'ta-IN')),
  is_read            INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
  read_at            TEXT,
  trip_id            TEXT,
  booking_id         TEXT,
  dedupe_key         TEXT NOT NULL UNIQUE,
  created_at         TEXT NOT NULL,
  CONSTRAINT fk_p6not_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT
);

CREATE TRIGGER trg_p6notif_no_delete
BEFORE DELETE ON phase6_notifications
BEGIN
  SELECT RAISE(FAIL, 'phase6 notifications are audit-logged and cannot be deleted');
END;

CREATE TABLE phase6_emergency_contacts (
  contact_id         TEXT PRIMARY KEY,
  user_id            TEXT NOT NULL,
  name               TEXT NOT NULL,
  relationship       TEXT NOT NULL,
  phone_number       TEXT NOT NULL,
  is_primary         INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0, 1)),
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  CONSTRAINT fk_p6emc_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT
);

CREATE TABLE phase6_emergency_events (
  event_id           TEXT PRIMARY KEY,
  user_id            TEXT NOT NULL,
  event_type         TEXT NOT NULL CHECK (event_type IN ('EMERGENCY_ASSISTANCE_OPENED','SOS_ACTIVATED','EMERGENCY_CONTACT_SELECTED','TRIP_DETAILS_SHARE_REQUESTED')),
  trip_id            TEXT,
  booking_id         TEXT,
  details_json       TEXT NOT NULL DEFAULT '{}',
  created_at         TEXT NOT NULL,
  CONSTRAINT fk_p6sos_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT ck_p6sos_details_json CHECK (json_valid(details_json))
);

CREATE TRIGGER trg_p6sos_no_delete
BEFORE DELETE ON phase6_emergency_events
BEGIN
  SELECT RAISE(FAIL, 'emergency audit events cannot be deleted');
END;

CREATE INDEX ix_p6notif_user ON phase6_notifications (user_id, created_at);
CREATE INDEX ix_p6notif_dedupe ON phase6_notifications (dedupe_key);
CREATE INDEX ix_p6emc_user ON phase6_emergency_contacts (user_id);
CREATE INDEX ix_p6sos_user ON phase6_emergency_events (user_id, created_at);
