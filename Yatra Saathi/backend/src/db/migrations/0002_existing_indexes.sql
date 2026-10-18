-- Migration 0002: the two approved indexes on existing tables (working copy only).
-- Approved schema; do not edit. Checksum is enforced by app/db/migrations/runner.py.

CREATE INDEX IF NOT EXISTS ix_flights_route_departs ON flights (origin_airport_id, dest_airport_id, departs_at);
CREATE INDEX IF NOT EXISTS ix_flight_fares_flight   ON flight_fares (flight_id);
