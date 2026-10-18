"""Check the original fingerprint and the working copy's health.

Usage (from backend/):  python -m scripts.verify_db
Exit code 0 = all checks passed.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from src.core.config import REQUIRED_SCHEMA_VERSION, Settings
from src.core.errors import Tech4ceError
from src.db.working_copy_guard import (
    WORKING_COPY_APPLICATION_ID,
    assert_working_copy,
    verify_original_fingerprint,
)

NEW_TABLES = ("agent_audit_events", "agent_carts", "agent_cart_items",
              "agent_confirmations", "agent_session_state", "push_subscriptions", "notifications_sent")
LEGACY_TABLE_RENAMES = {
    "agent_carts": "legacy_agent_carts_pre_migration",
    "agent_confirmations": "legacy_agent_confirmations_pre_migration",
}


def main() -> int:
    ok = True
    try:
        s = Settings.from_env()
        original, sha = s.require_original()
        verify_original_fingerprint(original, sha)
        print(f"[ok] original fingerprint unchanged: {sha}")
        assert_working_copy(s.require_db_path(), original)
        print(f"[ok] working copy marked (application_id={WORKING_COPY_APPLICATION_ID:#x})")
    except Tech4ceError as exc:
        print(f"[FAIL] {exc}")
        return 2

    work = sqlite3.connect(Path(s.db_path).resolve().as_uri() + "?mode=ro", uri=True)
    orig = sqlite3.connect(Path(original).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        uv = work.execute("PRAGMA user_version").fetchone()[0]
        print(f"[{'ok' if uv >= REQUIRED_SCHEMA_VERSION else 'FAIL'}] schema version {uv} (required {REQUIRED_SCHEMA_VERSION})")
        ok &= uv >= REQUIRED_SCHEMA_VERSION
        integ = work.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"[{'ok' if integ == 'ok' else 'FAIL'}] integrity_check: {integ}")
        ok &= integ == "ok"
        fk = work.execute("PRAGMA foreign_key_check").fetchall()
        print(f"[{'ok' if not fk else 'FAIL'}] foreign_key_check violations: {len(fk)}")
        ok &= not fk
        tables = {r[0] for r in work.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in NEW_TABLES if t not in tables]
        print(f"[{'ok' if not missing else 'FAIL'}] new tables present (missing: {missing or 'none'})")
        ok &= not missing
        trig = work.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        print(f"[{'ok' if trig == 31 else 'FAIL'}] triggers: {trig} (expected 31)")
        ok &= trig == 31
        for (name, sql) in orig.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"):
            working_name = LEGACY_TABLE_RENAMES.get(name, name)
            wsql = work.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (working_name,)).fetchone()
            if name in LEGACY_TABLE_RENAMES:
                original_columns = tuple(orig.execute(f'PRAGMA table_info("{name}")'))
                working_columns = tuple(work.execute(f'PRAGMA table_info("{working_name}")'))
                same_def = wsql is not None and working_columns == original_columns
            else:
                same_def = wsql is not None and wsql[0] == sql
            oc = orig.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            wc = work.execute(f'SELECT count(*) FROM "{working_name}"').fetchone()[0]
            flag = "ok" if same_def else "FAIL"
            ok &= same_def
            print(f"[{flag}] existing table {name} ({working_name}): "
                  f"definition {'unchanged' if same_def else 'CHANGED'}; rows original={oc} working={wc}")
    finally:
        work.close()
        orig.close()
    verify_original_fingerprint(original, sha)
    print(f"[ok] original fingerprint unchanged after checks")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
