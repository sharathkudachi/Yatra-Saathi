-- Migration 0007: Secure User Authentication, Registration & Credential Storage
-- Additive only: extends users table with username, password_hash, email_verified, last_login_at.
-- Enforces uniqueness constraints on username and email (case-insensitive).
-- Preserves existing demo user (usr_demo0001) and all historical user records.

ALTER TABLE users ADD COLUMN username TEXT;
ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN last_login_at TEXT;

-- Seed username and password hash for existing demo user
UPDATE users 
SET username = 'usr_demo0001',
    password_hash = '$argon2id$v=19$m=65536,t=3,p=4$YYeqjFJESyftnO5vSIAeIw$ZC4FJtDLGldjICcaZ2lKHlhnjvDnHlRb0HYdtyTXy4Q',
    email_verified = 1
WHERE user_id = 'usr_demo0001';

-- Enforce database-level uniqueness on username (case-insensitive)
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_lower ON users (lower(username)) WHERE username IS NOT NULL;

-- Enforce database-level uniqueness on email (case-insensitive)
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email));

-- ============================================================
-- Authentication Rate Limiting & Abuse Prevention
-- ============================================================
CREATE TABLE auth_rate_limits (
  attempt_key   TEXT    NOT NULL,
  attempt_type  TEXT    NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 1,
  first_attempt TEXT    NOT NULL,
  last_attempt  TEXT    NOT NULL,
  blocked_until TEXT,
  CONSTRAINT pk_auth_rate_limits PRIMARY KEY (attempt_key, attempt_type)
);
CREATE INDEX ix_auth_rate_limits_key ON auth_rate_limits (attempt_key);
