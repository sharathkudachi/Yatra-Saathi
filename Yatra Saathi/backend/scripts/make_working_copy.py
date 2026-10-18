"""Create the restorable working copy of APS-01.db.

Usage (from backend/):  python -m scripts.make_working_copy [--overwrite]
Reads APS_DB_ORIGINAL_PATH, APS_DB_ORIGINAL_SHA256 and APS_DB_PATH from the environment.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.core.config import Settings
from src.core.errors import Tech4ceError
from src.db.working_copy_guard import make_working_copy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true",
                        help="replace an existing working copy (must itself be a working copy)")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        original, sha = settings.require_original()
        result = make_working_copy(original, sha, settings.require_db_path(), overwrite=args.overwrite)
    except Tech4ceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
