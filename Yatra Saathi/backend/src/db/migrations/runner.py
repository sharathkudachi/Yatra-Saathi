"""Applies the approved migrations to the working copy only.

Guards: the original fingerprint is verified before and after; the target must be a
stamped working copy that is not the original; each migration file must match its
approved checksum; each migration runs in one transaction with PRAGMA user_version.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from src.core.config import Settings
from src.core.errors import MigrationError, SafetyError
from src.core.hashing import file_sha256
from src.db.working_copy_guard import assert_working_copy, verify_original_fingerprint

MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))

# (version, file name, approved SHA-256 of the file)
MIGRATIONS = (
    (1, "0001_agent_tables.sql", "d8a1e04661d760c267399bebb22d157b5f8d1aab12d655609a6a788fc6c88d62"),
    (2, "0002_existing_indexes.sql", "0a40fbebeeef27113ab45657228841e7cfe78642a1676d01bf857fb2d15f8df3"),
    (3, "0003_multi_currency_cart.sql", "3e0b4f34680579da2e66335da2c9a264929cae5ff6e48afb91a2d2a25b650b9f"),
    (4, "0004_notifications.sql", "0392132a904984093c982f896c8ff7a4fc3cc8015740a771ea48b982a1a7b490"),
    (5, "0005_phase5_booking_lifecycle.sql", "a63f6f5f5d4877c004f2f6f33084e706ac387ee234bdbd072ba52978e2c6908f"),
    (6, "0006_phase6_multimodal_intelligence.sql", "498c8a3ff261eacbace6020f65fd92d618192ce729d1d1eb44739e663ce35aad"),
    (7, "0007_user_authentication.sql", "d07fe8c2fa5e794f650d9ec245f32d4ac050776f3fe2cdf4dc91c336934bdb44"),
)

_LEGACY_TABLE_RENAMES = {
    "agent_carts": "legacy_agent_carts_pre_migration",
    "agent_confirmations": "legacy_agent_confirmations_pre_migration",
}
_LEGACY_COLUMNS = {
    "agent_carts": (
        "cart_id", "session_id", "plan_id", "plan_version", "cart_version", "status", "currency",
        "subtotal", "total", "spend_cap", "remaining_budget", "items_json", "hold_references_json",
        "created_at", "updated_at",
    ),
    "agent_confirmations": (
        "confirmation_id", "session_id", "plan_id", "plan_version", "cart_id", "cart_version",
        "confirmed_amount", "currency", "token", "status", "confirmed_at", "invalidated_at",
        "invalidation_reason", "created_at",
    ),
}


def load_migration(version: int, migrations_dir: Optional[str] = None) -> str:
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    for v, name, approved in MIGRATIONS:
        if v == version:
            path = os.path.join(migrations_dir, name)
            actual = file_sha256(path)
            if actual != approved:
                raise MigrationError(f"{name} differs from the approved schema (sha256 {actual})")
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
    raise MigrationError(f"unknown migration version {version}")


def _schema_objects(conn: sqlite3.Connection) -> tuple[tuple, ...]:
    return tuple(conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ))


def _matches_original_legacy_schema(conn: sqlite3.Connection, original_path: str) -> bool:
    """Recognize the verified v0 source schema with the older agent tables still present."""
    original = sqlite3.connect(Path(original_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if original.execute("PRAGMA user_version").fetchone()[0] != 0:
            return False
        if _schema_objects(conn) != _schema_objects(original):
            return False
        for table, expected_columns in _LEGACY_COLUMNS.items():
            columns = tuple(row[1] for row in conn.execute(f'PRAGMA table_info("{table}")'))
            if columns != expected_columns:
                return False
            archived = _LEGACY_TABLE_RENAMES[table]
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (archived,)).fetchone():
                return False
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            for foreign_key in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
                if foreign_key[2] in _LEGACY_TABLE_RENAMES:
                    return False
        return True
    finally:
        original.close()


def apply_migrations(settings: Settings, migrations_dir: Optional[str] = None) -> list[int]:
    original_path, original_sha = settings.require_original()
    verify_original_fingerprint(original_path, original_sha)
    db_path = settings.require_db_path()
    assert_working_copy(db_path, original_path)

    # Load and checksum every pending file before touching the database.
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=rw", uri=True, isolation_level=None)
    applied: list[int] = []
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        preserve_legacy_tables = _matches_original_legacy_schema(conn, original_path)
        if preserve_legacy_tables:
            # The fingerprinted source is v0. Its two old tables conflict by name,
            # but not by schema, with the approved migration-owned tables.
            current = 0
        pending = [(v, load_migration(v, migrations_dir)) for v, _n, _s in MIGRATIONS if v > current]
        for version, sql in pending:
            if version == 1 and preserve_legacy_tables:
                rename_sql = "\n".join(
                    f'ALTER TABLE "{table}" RENAME TO "{legacy}";'
                    for table, legacy in _LEGACY_TABLE_RENAMES.items()
                )
                sql = f"{rename_sql}\n{sql}"
            try:
                conn.executescript(f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
            except sqlite3.Error as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise MigrationError(f"migration {version} failed: {exc}") from exc
            applied.append(version)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SafetyError("working copy failed integrity_check after migrations")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SafetyError(f"foreign key violations after migrations: {violations[:5]}")
    finally:
        conn.close()

    verify_original_fingerprint(original_path, original_sha)
    return applied
