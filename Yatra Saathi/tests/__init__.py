"""Makes `backend/src` importable as `src` and `ai/travel_agent` importable as
`travel_agent`, so tests can do `from src.core...` / `from travel_agent...`
regardless of whether they're run via `python -m unittest` or `pytest`, and
regardless of the current working directory."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _dir in (os.path.join(_ROOT, "backend"), os.path.join(_ROOT, "ai")):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

# tests/ai/unit/* (Developer 2's own unit tests) read the original DB directly,
# read-only, through travel_agent's standalone-demo reader. Point it at the same
# original the rest of the suite uses, so only APS_DB_ORIGINAL_PATH needs setting.
if os.environ.get("APS_DB_ORIGINAL_PATH") and not os.environ.get("APS01_DB_PATH"):
    os.environ["APS01_DB_PATH"] = os.environ["APS_DB_ORIGINAL_PATH"]
