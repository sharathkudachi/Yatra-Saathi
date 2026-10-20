"""Static safety checks for the targeted PostgreSQL registration-city seed."""
from pathlib import Path
import re
import unittest

from src.db.migrations.runner import MIGRATIONS


class TestPostgresRegistrationCitySeed(unittest.TestCase):
    def test_seed_is_transactional_idempotent_insert_of_canonical_reference_rows(self):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "backend"
            / "src"
            / "db"
            / "migrations"
            / "0009_postgres_registration_city_catalog.sql"
        )
        source = migration_path.read_text(encoding="utf-8")
        self.assertIn(r"\set ON_ERROR_STOP on", source)

        sql_body = re.sub(r"(?m)^\s*--.*$", "", source)
        sql_body = re.sub(r"(?m)^\s*\\set\s+ON_ERROR_STOP\s+on\s*$", "", sql_body)
        statements = [
            " ".join(statement.split())
            for statement in sql_body.split(";")
            if statement.strip()
        ]
        expected_country = " ".join(
            """INSERT INTO public.countries (country_id, name, iso2, iso3)
            VALUES ('cnt_b8092331', 'Sri Lanka', 'LK', 'LKA')
            ON CONFLICT (country_id) DO NOTHING""".split()
        )
        expected_language = " ".join(
            """INSERT INTO public.languages (
                language_id, bcp47, english_name, native_name, script, rtl, tts_supported, updated_at
            ) VALUES (
                'lng_5c34a3a2', 'si', 'Sinhala', U&'\\0DC3\\0DD2\\0D82\\0DC4\\0DBD',
                'Sinh', 0, 0, '2026-08-18T10:00:00+05:30'
            ) ON CONFLICT (language_id) DO NOTHING""".split()
        )
        expected_city = " ".join(
            """INSERT INTO public.cities (
                city_id, name, state, country_id, country_code, lat, lng, timezone,
                region, population, season_profile, peak_months, primary_language,
                description, status, updated_at
            ) VALUES (
                'cty_009c9fd2', 'Kandy', NULL, 'cnt_b8092331', 'LK',
                7.290572, 80.633728, 'Asia/Colombo', 'South Asia', 125000,
                'winter', '12,1,2,3', 'si',
                'Kandy is the kind of place that rewards a second day. The centre is compact enough to walk, the lakefront stays busy well into the evening, and the best of it is off the main road.',
                'active', '2026-08-18T10:00:00+05:30'
            ) ON CONFLICT (city_id) DO NOTHING""".split()
        )
        self.assertEqual(statements, ["BEGIN", expected_country, expected_language, expected_city, "COMMIT"])
        self.assertEqual(len(re.findall(r"(?i)\bINSERT\s+INTO\b", source)), 3)
        self.assertNotRegex(source, r"(?i)\b(?:UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b")

    def test_postgres_seed_is_not_registered_in_sqlite_migration_runner(self):
        migration_name = "0009_postgres_registration_city_catalog.sql"
        self.assertNotIn(migration_name, {name for _version, name, _checksum in MIGRATIONS})


if __name__ == "__main__":
    unittest.main()
