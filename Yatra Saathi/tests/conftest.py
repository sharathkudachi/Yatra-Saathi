"""Makes `backend/src` importable as `src` and `ai/travel_agent` importable as
`travel_agent` for everything under `tests/` (which lives at the repo root,
not under `backend/`) can do `from src.core...` / `from travel_agent...` under
both pytest and `python -m unittest`.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _dir in (os.path.join(_ROOT, "backend"), os.path.join(_ROOT, "ai")):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

# AI standalone-tool tests use the canonical working copy, read-only. Resolve
# defaults from the repository so pytest does not depend on a developer's shell
# environment or on an ai/data/APS-01.db duplicate.
_original_db = os.path.join(_ROOT, "data", "original", "APS-01.db")
_working_db = os.path.join(_ROOT, "backend", "var", "aps01_working.db")
os.environ.setdefault("APS_DB_ORIGINAL_PATH", _original_db)
os.environ.setdefault("APS_DB_PATH", _working_db)
os.environ.setdefault("APS01_DB_PATH", os.environ["APS_DB_PATH"])
