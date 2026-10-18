"""The approved schema is applied exactly, additively, and only to the working copy."""
import re
import sqlite3
import unittest

from src.core.enums import EVENT_TYPES
from src.db.connection import connect
from src.db.migrations.runner import MIGRATIONS, apply_migrations, load_migration
from tests.support import (EXPECTED_EXISTING_ROW_COUNTS, LEGACY_AGENT_ROW_COUNTS, WorkingCopy,
                           assert_original_untouched)

NEW_TABLES = {"agent_audit_events", "agent_carts", "agent_cart_items",
              "agent_confirmations", "agent_session_state", "push_subscriptions", "notifications_sent",
              "booking_travellers", "phase5_booking_events", "trip_packs",
              "user_language_preferences", "phase6_notification_preferences",
              "phase6_notifications", "phase6_emergency_contacts", "phase6_emergency_events",
              "auth_rate_limits"}
LEGACY_TABLE_RENAMES = {
    "agent_carts": "legacy_agent_carts_pre_migration",
    "agent_confirmations": "legacy_agent_confirmations_pre_migration",
}
PRESERVED_LEGACY_TABLES = {
    "agent_conversations", "agent_events", "agent_plans", "agent_replan_history",
    "agent_runtime_state", "agent_tool_results", "agent_transactions",
    *LEGACY_TABLE_RENAMES.values(),
}
NEW_INDEXES = {
    "ix_audit_session_type", "ix_audit_type_time", "ix_audit_caused_by",
    "ux_carts_one_active", "ix_carts_session",
    "ux_items_active_inventory", "ix_items_cart", "ix_items_group", "ix_items_hold",
    "ux_cnf_one_pending", "ux_cnf_cart_version", "ux_cnf_one_booking_per_session",
    "ux_cnf_booking", "ix_cnf_session_time",
    "ix_btrav_booking", "ix_p5evt_booking", "ix_p5evt_user", "ix_pack_user",
    "ix_p6notif_user", "ix_p6notif_dedupe", "ix_p6emc_user", "ix_p6sos_user",
    "ix_auth_rate_limits_key",
}
EXISTING_TABLE_INDEXES = {
    "ix_flights_route_departs": "flights",
    "ix_flight_fares_flight": "flight_fares",
    "uq_users_username_lower": "users",
    "uq_users_email_lower": "users",
}
TRIGGERS = {
    "agent_audit_events": {"trg_audit_no_update", "trg_audit_no_delete", "trg_audit_seq_gapless",
                           "trg_audit_chain_link", "trg_audit_cause_same_session"},
    "agent_carts": {"trg_carts_currency_session", "trg_carts_immutable_keys", "trg_carts_status_forward",
                    "trg_carts_terminal_frozen", "trg_carts_version_monotonic", "trg_carts_no_delete"},
    "agent_cart_items": {"trg_items_session_match", "trg_items_inventory_match",
                         "trg_items_source_valid", "trg_items_cart_open_ins", "trg_items_cart_open_upd",
                         "trg_items_immutable", "trg_items_removed_frozen", "trg_items_no_delete"},
    "agent_confirmations": {"trg_cnf_insert_pending", "trg_cnf_cart_locked_match", "trg_cnf_transitions",
                            "trg_cnf_terminal_frozen", "trg_cnf_owner_only", "trg_cnf_snapshot_immutable",
                            "trg_cnf_consume_owner", "trg_cnf_no_delete"},
    "agent_session_state": {"trg_state_insert_v1", "trg_state_version_step",
                            "trg_state_session_immutable", "trg_state_no_delete"},
    "phase5_booking_events": {"trg_p5evt_no_delete"},
    "trip_packs": {"trg_pack_no_delete"},
    "phase6_notifications": {"trg_p6notif_no_delete"},
    "phase6_emergency_events": {"trg_p6sos_no_delete"},
}


def setUpModule():
    assert_original_untouched()
    global PRISTINE, MIGRATED
    PRISTINE = WorkingCopy(migrate=False)
    MIGRATED = WorkingCopy(migrate=True)


def tearDownModule():
    PRISTINE.cleanup()
    MIGRATED.cleanup()
    assert_original_untouched()


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.conn = MIGRATED.raw(readonly=True)

    def tearDown(self):
        self.conn.close()

    def names(self, kind):
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'", (kind,))}

    def test_schema_version(self):
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], 7)

    def test_new_tables_and_legacy_tables_are_distinct(self):
        tables = set(self.names("table"))
        self.assertEqual(tables - set(EXPECTED_EXISTING_ROW_COUNTS) - PRESERVED_LEGACY_TABLES, NEW_TABLES)
        self.assertTrue(PRESERVED_LEGACY_TABLES <= tables)

    def test_triggers_all_on_new_tables(self):
        # 0003 dropped trg_items_currency_match; Phase 5 added 2; Phase 6 added 2
        found = self.names("trigger")
        self.assertEqual(len(found), 35)
        self.assertNotIn("trg_items_currency_match", found)
        for table, expected in TRIGGERS.items():
            self.assertEqual({n for n, t in found.items() if t == table}, expected)
        self.assertTrue(set(found.values()) <= NEW_TABLES, "no trigger may be on an existing table")

    def test_indexes(self):
        found = self.names("index")
        self.assertEqual({n for n, t in found.items() if t in NEW_TABLES}, NEW_INDEXES)
        for name, table in EXISTING_TABLE_INDEXES.items():
            self.assertEqual(found.get(name), table)
        extra = {n for n, t in found.items() if t not in NEW_TABLES} - set(EXISTING_TABLE_INDEXES)
        extra -= {n for n, t in found.items() if t in PRESERVED_LEGACY_TABLES}
        self.assertEqual(extra, set(), "no other indexes on existing tables")

    def test_existing_tables_unchanged(self):
        pristine = PRISTINE.raw(readonly=True)
        try:
            for table, count in EXPECTED_EXISTING_ROW_COUNTS.items():
                with self.subTest(table=table):
                    orig_sql = pristine.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
                    migrated_name = LEGACY_TABLE_RENAMES.get(table, table)
                    if table == "bookings":
                        # Additive extension in Phase 5
                        old_columns = {r[1] for r in pristine.execute('PRAGMA table_info("bookings")')}
                        new_columns = {r[1] for r in self.conn.execute('PRAGMA table_info("bookings")')}
                        self.assertTrue(old_columns <= new_columns)
                        self.assertEqual(new_columns - old_columns, {"itinerary_version", "booking_mode", "lifecycle_status", "demo_label"})
                    elif table == "users":
                        # Additive extension in Phase 7 (authentication)
                        old_columns = {r[1] for r in pristine.execute('PRAGMA table_info("users")')}
                        new_columns = {r[1] for r in self.conn.execute('PRAGMA table_info("users")')}
                        self.assertTrue(old_columns <= new_columns)
                        self.assertEqual(new_columns - old_columns, {"username", "password_hash", "email_verified", "last_login_at"})
                    elif migrated_name == table:
                        new_sql = self.conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (migrated_name,)).fetchone()[0]
                        self.assertEqual(new_sql, orig_sql)
                    else:
                        old_columns = tuple(pristine.execute(f'PRAGMA table_info("{table}")'))
                        new_columns = tuple(self.conn.execute(f'PRAGMA table_info("{migrated_name}")'))
                        self.assertEqual(new_columns, old_columns)
                    self.assertEqual(self.conn.execute(f'SELECT count(*) FROM "{migrated_name}"').fetchone()[0], count)
        finally:
            pristine.close()

    def test_legacy_agent_rows_are_preserved(self):
        for old_name, count in LEGACY_AGENT_ROW_COUNTS.items():
            with self.subTest(table=old_name):
                migrated_name = LEGACY_TABLE_RENAMES.get(old_name, old_name)
                self.assertEqual(
                    self.conn.execute(f'SELECT count(*) FROM "{migrated_name}"').fetchone()[0], count
                )

    def test_integrity_and_foreign_keys(self):
        self.assertEqual(self.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_existing_table_indexes_are_used(self):
        plan = " ".join(r[3] for r in self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT flight_id FROM flights WHERE origin_airport_id=? AND dest_airport_id=? "
            "AND departs_at >= ? AND departs_at < ?", ("a", "b", "2026-10-06", "2026-10-07")))
        self.assertIn("ix_flights_route_departs", plan)
        plan = " ".join(r[3] for r in self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM flight_fares WHERE flight_id=?", ("x",)))
        self.assertIn("ix_flight_fares_flight", plan)

    def test_event_types_match_schema(self):
        sql = load_migration(1)
        listed = re.search(r"ck_audit_type CHECK \(event_type IN \(([^)]*)\)\)", sql).group(1)
        self.assertEqual(tuple(x.strip().strip("'") for x in listed.split(",")), EVENT_TYPES)
        self.assertEqual(len(EVENT_TYPES), 23)

    def test_migration_files_match_approved_checksums(self):
        for version, _name, _sha in MIGRATIONS:
            load_migration(version)  # raises MigrationError if a file differs


class MigrationBehaviourTests(unittest.TestCase):
    def test_second_run_applies_nothing(self):
        self.assertEqual(apply_migrations(MIGRATED.settings), [])

    def test_legacy_schema_is_reconciled_when_version_marker_is_stale(self):
        wc = WorkingCopy(migrate=False)
        try:
            conn = wc.raw()
            conn.execute("PRAGMA user_version = 4")
            conn.close()
            self.assertEqual(apply_migrations(wc.settings), [1, 2, 3, 4, 5, 6, 7])
            conn = wc.raw(readonly=True)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 7)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM legacy_agent_carts_pre_migration").fetchone()[0], 171)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM legacy_agent_confirmations_pre_migration").fetchone()[0], 171)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_audit_events").fetchone()[0], 0)
            finally:
                conn.close()
        finally:
            wc.cleanup()
        assert_original_untouched()

    def test_application_connection_enforces_foreign_keys(self):
        conn = connect(MIGRATED.settings)
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO agent_session_state VALUES ('agt_nosuch', 1, '{}', ?, "
                             "'2026-09-24T10:00:00.000Z')", ("a" * 64,))
        finally:
            conn.close()

    def test_readonly_connection_cannot_write(self):
        conn = connect(MIGRATED.settings, readonly=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE currencies SET name = name")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
