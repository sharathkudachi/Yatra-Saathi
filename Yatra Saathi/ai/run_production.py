"""Production entrypoint for AI agent service on Render / Cloud.

Usage (from ai/): python run_production.py
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    print(f"[Production] Launching Yatra AI Agent Service on 0.0.0.0:{port}...")
    uvicorn.run("service:app", host="0.0.0.0", port=port, log_level="info")
