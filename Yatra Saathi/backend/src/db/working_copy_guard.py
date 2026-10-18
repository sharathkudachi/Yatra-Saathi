"""Protection of the original APS-01.db.

Rules (approved):
* The original is never written. It is only hashed (read in binary mode) and copied.
* A working copy is stamped with PRAGMA application_id = WORKING_COPY_APPLICATION_ID.
  This changes only the copy; an unstamped file is never treated as a working copy.
* Anything that writes refuses to run if its target resolves to the original file.
"""
from __future__ import annotations

import os
import secrets
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

from src.core.errors import (
    NotAWorkingCopy,
    OriginalDatabaseTampered,
    RefusedOriginalTarget,
    SafetyError,
)
from src.core.hashing import file_sha256

WORKING_COPY_APPLICATION_ID = 0x54345743  # ASCII "T4WC"


def verify_original_fingerprint(original_path: str, expected_sha256: str) -> str:
    if not os.path.isfile(original_path):
        raise SafetyError(f"original database not found: {original_path}")
    actual = file_sha256(original_path)
    if actual != expected_sha256:
        raise OriginalDatabaseTampered(
            f"original database fingerprint mismatch: expected {expected_sha256}, got {actual}"
        )
    return actual


def _same_file(a: str, b: str) -> bool:
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except (FileNotFoundError, NotADirectoryError):
        return False


def assert_not_original(target_path: str, original_path: Optional[str]) -> None:
    if original_path and _same_file(target_path, original_path):
        raise RefusedOriginalTarget(f"refusing to use the original database as a target: {target_path}")


def _readonly_uri(path: str) -> str:
    return Path(path).resolve().as_uri() + "?mode=ro"


def read_application_id(path: str) -> int:
    conn = sqlite3.connect(_readonly_uri(path), uri=True)
    try:
        return conn.execute("PRAGMA application_id").fetchone()[0]
    finally:
        conn.close()


def assert_working_copy(path: str, original_path: Optional[str] = None) -> None:
    """Raise unless `path` is an existing, stamped working copy that is not the original."""
    if not path:
        raise NotAWorkingCopy("no database path given")
    if not os.path.isfile(path):
        # Never let sqlite create a fresh, empty database by accident.
        raise NotAWorkingCopy(f"working copy not found: {path}")
    assert_not_original(path, original_path)
    try:
        app_id = read_application_id(path)
    except sqlite3.DatabaseError as exc:
        raise NotAWorkingCopy(f"not a SQLite database: {path}") from exc
    if app_id != WORKING_COPY_APPLICATION_ID:
        raise NotAWorkingCopy(f"database is not a marked working copy: {path}")


def make_working_copy(original_path: str, expected_sha256: str, dest_path: str,
                      overwrite: bool = False) -> dict:
    """Create a restorable working copy of the original database.

    1. verify the original fingerprint; 2. copy to a temporary file; 3. verify the copy's
    bytes equal the original; 4. stamp the copy; 5. atomically move into place;
    6. re-verify the original fingerprint.
    """
    verify_original_fingerprint(original_path, expected_sha256)
    assert_not_original(dest_path, original_path)
    dest_dir = os.path.dirname(os.path.abspath(dest_path))
    if not os.path.isdir(dest_dir):
        raise SafetyError(f"destination directory does not exist: {dest_dir}")
    if os.path.exists(dest_path):
        if not overwrite:
            raise SafetyError(f"working copy already exists (use overwrite): {dest_path}")
        # Only ever overwrite something that is itself a stamped working copy.
        assert_working_copy(dest_path, original_path)

    tmp_path = os.path.join(dest_dir, f".{os.path.basename(dest_path)}.tmp-{secrets.token_hex(4)}")
    try:
        shutil.copyfile(original_path, tmp_path)
        if file_sha256(tmp_path) != expected_sha256:
            raise SafetyError("copy does not match the original fingerprint")
        conn = sqlite3.connect(Path(tmp_path).resolve().as_uri() + "?mode=rw", uri=True)
        try:
            conn.execute(f"PRAGMA application_id = {WORKING_COPY_APPLICATION_ID}")
            conn.commit()
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SafetyError("working copy failed integrity_check")
        finally:
            conn.close()
        os.replace(tmp_path, dest_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    verify_original_fingerprint(original_path, expected_sha256)
    return {
        "original_sha256": expected_sha256,
        "working_copy": os.path.abspath(dest_path),
        "working_copy_sha256": file_sha256(dest_path),
        "application_id": WORKING_COPY_APPLICATION_ID,
    }
