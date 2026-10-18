-- Migration 0004: push notifications (working copy only). Two new tables; existing tables untouched.
-- Checksum is enforced by src/db/migrations/runner.py; do not edit once approved.
--
-- push_subscriptions  one row per browser/device that allowed notifications (Web Push), with the
--                     user's notification preferences for that device.
-- notifications_sent  every notification raised for a user: the dedupe key guarantees each event
--                     (plan ready, booking confirmed, flight departing/landed) is sent once, and the
--                     rows double as the in-app notification history.

CREATE TABLE push_subscriptions (
  subscription_id TEXT    PRIMARY KEY,
  user_id         TEXT    NOT NULL,
  endpoint        TEXT    NOT NULL UNIQUE,
  p256dh          TEXT    NOT NULL,
  auth            TEXT    NOT NULL,
  prefs_json      TEXT    NOT NULL DEFAULT '{}',
  created_at      TEXT    NOT NULL,
  updated_at      TEXT    NOT NULL,
  CONSTRAINT fk_push_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT ck_push_prefs_json CHECK (json_valid(prefs_json))
);

CREATE TABLE notifications_sent (
  notification_id TEXT    PRIMARY KEY,
  user_id         TEXT    NOT NULL,
  session_id      TEXT,
  kind            TEXT    NOT NULL,
  dedupe_key      TEXT    NOT NULL UNIQUE,
  title           TEXT    NOT NULL,
  body            TEXT    NOT NULL,
  url             TEXT,
  delivered_count INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT    NOT NULL,
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT fk_notif_session FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT ck_notif_kind CHECK (kind IN ('plan_ready','approval_ready','booking_confirmed','flight_departing','flight_landed','test'))
);
