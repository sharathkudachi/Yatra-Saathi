"""Apply the approved migrations to the working copy (never the original).

Usage (from backend/):  python -m scripts.apply_migrations
"""
from __future__ import annotations

import sys

from src.core.config import Settings
from src.core.errors import Tech4ceError
from src.db.migrations.runner import apply_migrations


def main() -> int:
    try:
        applied = apply_migrations(Settings.from_env())
    except Tech4ceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"applied migrations: {applied or 'none (already up to date)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
