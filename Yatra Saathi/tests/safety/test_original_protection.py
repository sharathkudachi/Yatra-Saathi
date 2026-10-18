"""Invariant: the original APS-01.db is never modified or used as a target.

Refusal cases use a *fake* original in a temp directory, so no test ever points a
write operation at the real original. The real original is only hashed and copied.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from src.core.errors import (NotAWorkingCopy, OriginalDatabaseTampered, RefusedOriginalTarget,
                             SafetyError, MigrationError)
from src.core.hashing import file_sha256
from src.db.connection import connect
from src.db.migrations.runner import MIGRATIONS_DIR, apply_migrations, load_migration
from src.db.working_copy_guard import (WORKING_COPY_APPLICATION_ID, make_working_copy,
                                       read_application_id)
from tests.support import (RECORDED_ORIGINAL_SHA256, WorkingCopy, assert_original_untouched,
                           original_path, settings_for)


def setUpModule():
    assert_original_untouched()


def tearDownModule():
    assert_original_untouched()


class FakeOriginal:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="t4fake-")
        self.path = os.path.join(self.dir, "fake_original.db")
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()
        self.sha = file_sha256(self.path)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class MakeWorkingCopyTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOriginal()

    def tearDown(self):
        self.fake.cleanup()

    def test_copy_is_marked_and_original_unchanged(self):
        dest = os.path.join(self.fake.dir, "work.db")
        result = make_working_copy(self.fake.path, self.fake.sha, dest)
        self.assertEqual(read_application_id(dest), WORKING_COPY_APPLICATION_ID)
        self.assertEqual(read_application_id(self.fake.path), 0)
        self.assertEqual(file_sha256(self.fake.path), self.fake.sha)
        self.assertNotEqual(result["working_copy_sha256"], self.fake.sha)

    def test_refuses_original_as_destination(self):
        with self.assertRaises(RefusedOriginalTarget):
            make_working_copy(self.fake.path, self.fake.sha, self.fake.path, overwrite=True)
        self.assertEqual(file_sha256(self.fake.path), self.fake.sha)

    def test_refuses_symlink_to_original_as_destination(self):
        link = os.path.join(self.fake.dir, "link.db")
        try:
            os.symlink(self.fake.path, link)
        except OSError:
            self.skipTest("Symlinks not supported on this platform without elevated privileges")
        with self.assertRaises(RefusedOriginalTarget):
            make_working_copy(self.fake.path, self.fake.sha, link, overwrite=True)
        self.assertEqual(file_sha256(self.fake.path), self.fake.sha)

    def test_refuses_when_original_fingerprint_differs(self):
        dest = os.path.join(self.fake.dir, "work.db")
        with self.assertRaises(OriginalDatabaseTampered):
            make_working_copy(self.fake.path, "0" * 64, dest)
        self.assertFalse(os.path.exists(dest))

    def test_refuses_to_overwrite_non_working_copy(self):
        dest = os.path.join(self.fake.dir, "other.db")
        sqlite3.connect(dest).close()
        with self.assertRaises(SafetyError):
            make_working_copy(self.fake.path, self.fake.sha, dest)
        with self.assertRaises(NotAWorkingCopy):
            make_working_copy(self.fake.path, self.fake.sha, dest, overwrite=True)

    def test_overwrite_of_existing_working_copy_restores_it(self):
        dest = os.path.join(self.fake.dir, "work.db")
        make_working_copy(self.fake.path, self.fake.sha, dest)
        conn = sqlite3.connect(dest)
        conn.execute("INSERT INTO t VALUES (2)")
        conn.commit()
        conn.close()
        make_working_copy(self.fake.path, self.fake.sha, dest, overwrite=True)
        conn = sqlite3.connect(dest)
        self.assertEqual(conn.execute("SELECT count(*) FROM t").fetchone()[0], 1)
        conn.close()


class ConnectionGuardTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOriginal()

    def tearDown(self):
        self.fake.cleanup()

    def test_refuses_original_path(self):
        s = settings_for(self.fake.path, original=self.fake.path, sha=self.fake.sha)
        with self.assertRaises(RefusedOriginalTarget):
            connect(s, require_schema=False)

    def test_refuses_unmarked_database(self):
        other = os.path.join(self.fake.dir, "unmarked.db")
        shutil.copyfile(self.fake.path, other)
        s = settings_for(other, original=self.fake.path, sha=self.fake.sha)
        with self.assertRaises(NotAWorkingCopy):
            connect(s, require_schema=False)

    def test_refuses_missing_file_and_does_not_create_it(self):
        missing = os.path.join(self.fake.dir, "missing.db")
        s = settings_for(missing, original=self.fake.path, sha=self.fake.sha)
        with self.assertRaises(NotAWorkingCopy):
            connect(s, require_schema=False)
        self.assertFalse(os.path.exists(missing))

    def test_refuses_unmigrated_working_copy(self):
        dest = os.path.join(self.fake.dir, "work.db")
        make_working_copy(self.fake.path, self.fake.sha, dest)
        s = settings_for(dest, original=self.fake.path, sha=self.fake.sha)
        with self.assertRaises(SafetyError):
            connect(s)
        connect(s, require_schema=False).close()  # allowed when schema not required


class MigrationGuardTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOriginal()

    def tearDown(self):
        self.fake.cleanup()

    def test_refuses_to_migrate_the_original(self):
        s = settings_for(self.fake.path, original=self.fake.path, sha=self.fake.sha)
        with self.assertRaises(RefusedOriginalTarget):
            apply_migrations(s)
        self.assertEqual(file_sha256(self.fake.path), self.fake.sha)

    def test_refuses_to_migrate_unmarked_database(self):
        other = os.path.join(self.fake.dir, "unmarked.db")
        shutil.copyfile(self.fake.path, other)
        before = file_sha256(other)
        s = settings_for(other, original=self.fake.path, sha=self.fake.sha)
        with self.assertRaises(NotAWorkingCopy):
            apply_migrations(s)
        self.assertEqual(file_sha256(other), before)

    def test_refuses_when_original_fingerprint_differs(self):
        dest = os.path.join(self.fake.dir, "work.db")
        make_working_copy(self.fake.path, self.fake.sha, dest)
        before = file_sha256(dest)
        s = settings_for(dest, original=self.fake.path, sha="f" * 64)
        with self.assertRaises(OriginalDatabaseTampered):
            apply_migrations(s)
        self.assertEqual(file_sha256(dest), before)

    def test_refuses_tampered_migration_file(self):
        tmp = tempfile.mkdtemp(prefix="t4mig-")
        try:
            for name in os.listdir(MIGRATIONS_DIR):
                if name.endswith(".sql"):
                    shutil.copyfile(os.path.join(MIGRATIONS_DIR, name), os.path.join(tmp, name))
            load_migration(1, tmp)  # unmodified copy is accepted
            with open(os.path.join(tmp, "0001_agent_tables.sql"), "a", encoding="utf-8") as fh:
                fh.write("\n-- tampered\n")
            with self.assertRaises(MigrationError):
                load_migration(1, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RealOriginalTests(unittest.TestCase):
    def test_real_original_fingerprint_matches_recorded_value(self):
        self.assertEqual(file_sha256(original_path()), RECORDED_ORIGINAL_SHA256)

    def test_real_copy_and_migration_leave_original_untouched(self):
        wc = WorkingCopy(migrate=True)
        try:
            self.assertEqual(file_sha256(original_path()), RECORDED_ORIGINAL_SHA256)
            self.assertNotEqual(file_sha256(wc.path), RECORDED_ORIGINAL_SHA256)
        finally:
            wc.cleanup()


if __name__ == "__main__":
    unittest.main()
