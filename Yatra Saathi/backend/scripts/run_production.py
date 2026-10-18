"""Production entrypoint for FastAPI backend on Render / Cloud.

Usage (from backend/):
    python scripts/run_production.py
    OR
    python -m scripts.run_production

1. Ensures backend root is on sys.path.
2. Runs scripts.init_production_db to ensure database exists and is migrated.
3. Reads PORT from environment (default: 8000).
4. Starts Uvicorn listening on 0.0.0.0:${PORT}.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the backend root directory (parent of scripts/) is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import uvicorn
from scripts.init_production_db import init_db

if __name__ == "__main__":
    code = init_db()
    if code != 0:
        print(f"[Production] Database initialization failed with code {code}. Refusing to start.", file=sys.stderr)
        sys.exit(code)

    port = int(os.environ.get("PORT", "8000"))
    print(f"[Production] Launching Yatra Backend API on 0.0.0.0:{port}...")
    uvicorn.run("src.main:app", host="0.0.0.0", port=port, log_level="info")
