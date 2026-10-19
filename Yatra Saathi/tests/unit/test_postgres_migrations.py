"""Static checks for PostgreSQL-only migration files."""
from pathlib import Path
import re
import unittest

from src.db.migrations.runner import MIGRATIONS
from src.db.postgres_schema import POSTGRES_USER_REGISTRATION_MIGRATION


class TestPostgresRegistrationMigration(unittest.TestCase):
    def test_registration_migration_contains_only_expected_transactional_changes(self):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "backend"
            / "src"
            / "db"
            / "migrations"
            / "0008_postgres_user_registration_columns.sql"
        )
        source = migration_path.read_text(encoding="utf-8")
        self.assertIn(r"\set ON_ERROR_STOP on", source)

        sql_body = re.sub(r"(?m)^\s*--.*$", "", source)
        sql_body = re.sub(r"(?m)^\s*\\set\s+ON_ERROR_STOP\s+on\s*$", "", sql_body)
        statements = [statement.strip() for statement in sql_body.split(";") if statement.strip()]

        expected_alters = [
            re.sub(r"^ALTER TABLE users", "ALTER TABLE public.users", statement)
            .replace("REFERENCES cities(city_id)", "REFERENCES public.cities(city_id)")
            for statement in POSTGRES_USER_REGISTRATION_MIGRATION
        ]
        self.assertEqual(statements, ["BEGIN", *expected_alters, "COMMIT"])
        self.assertTrue(all("IF NOT EXISTS" in statement for statement in expected_alters))
        self.assertFalse(any(re.search(r"\b(?:NOT NULL|DEFAULT|UPDATE|INSERT|DELETE|DROP|TRUNCATE)\b", statement, re.I)
                             for statement in expected_alters))

    def test_postgres_migration_is_not_registered_for_sqlite_runner(self):
        migration_name = "0008_postgres_user_registration_columns.sql"
        self.assertNotIn(migration_name, {name for _version, name, _checksum in MIGRATIONS})


if __name__ == "__main__":
    unittest.main()
