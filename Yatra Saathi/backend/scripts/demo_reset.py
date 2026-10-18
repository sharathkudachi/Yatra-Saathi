"""Recreates the working copy, migrates it, and seeds the demo data (section 14).

Usage (from backend/):  python -m scripts.demo_reset
Reads APS_DB_PATH / APS_DB_ORIGINAL_PATH / APS_DB_ORIGINAL_SHA256 from the environment.
"""
from __future__ import annotations

import json
import sys

from src.core.config import Settings
from src.core.errors import Tech4ceError
from src.db.connection import connect
from src.db.migrations.runner import apply_migrations
from src.db.working_copy_guard import make_working_copy
from scripts.seed_demo import seed


def main(argv: list[str] | None = None) -> int:
    try:
        settings = Settings.from_env()
        original, sha = settings.require_original()
        copy_result = make_working_copy(original, sha, settings.require_db_path(), overwrite=True)
        migration_result = apply_migrations(settings)
        conn = connect(settings)
        try:
            seed_result = seed(conn)
        finally:
            conn.close()
    except Tech4ceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"working_copy": copy_result, "migrations": migration_result, "seed": seed_result},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
