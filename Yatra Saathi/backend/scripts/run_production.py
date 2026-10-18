"""Production entrypoint for FastAPI backend on Render / Cloud.

Usage (from backend/): python -m scripts.run_production

1. Runs scripts.init_production_db to ensure working database copy exists and is migrated.
2. Reads PORT from environment (default: 8000).
3. Starts Uvicorn listening on 0.0.0.0:${PORT}.
"""
from __future__ import annotations

import os
import sys
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
