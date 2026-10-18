"""Live demo verification (Phase 11). Run from the repo root: backend/.venv/bin/python docs/live_demo.py
Drives the REAL backend (FastAPI, real services, real DB working copy) and the REAL
travel_agent (LangGraph, LLM off for determinism) through the full flow, printing
actual outputs at every step -- nothing here is a canned/expected transcript.
"""
import os
import sqlite3
import sys
from datetime import date, datetime, timezone

os.environ["TRAVEL_AGENT_DISABLE_LLM"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai"))

from fastapi.testclient import TestClient
from backend_client import BackendClient
from src.core import agent_tokens, human_tokens
from src.core.clock import FixedClock
from src.core.config import Settings
from src.db.working_copy_guard import make_working_copy
from src.db.migrations.runner import apply_migrations
from travel_agent.runner import run_agent

ORIGINAL = os.environ["APS_DB_ORIGINAL_PATH"]
ORIGINAL_SHA = "ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a"
HUMAN_SECRET, AGENT_SECRET = "demo-h", "demo-a"


def fingerprint():
    import hashlib
    h = hashlib.sha256()
    with open(ORIGINAL, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def run_scenario(label, goal, spend_cap, workdir, followup="16 Nov 2026 to 19 Nov 2026"):
    print(f"\n{'=' * 70}\nSCENARIO: {label}\nGOAL: {goal!r}\nCAP: ₹{spend_cap}\n{'=' * 70}")
    db_path = os.path.join(workdir, f"{label}.db")
    make_working_copy(ORIGINAL, ORIGINAL_SHA, db_path)
    settings = Settings.from_env({
        "APS_DB_PATH": db_path, "APS_DB_ORIGINAL_PATH": ORIGINAL, "APS_DB_ORIGINAL_SHA256": ORIGINAL_SHA,
        "HUMAN_TOKEN_SECRET": HUMAN_SECRET, "AGENT_TOKEN_SECRET": AGENT_SECRET,
        "DEMO_LOGIN_USER_IDS": "",
    })
    apply_migrations(settings)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    user_id = conn.execute("SELECT user_id FROM users WHERE status='active' AND home_currency='INR' LIMIT 1").fetchone()[0]
    conn.close()

    from src.main import create_app
    clock = FixedClock(datetime(2026, 9, 24, tzinfo=timezone.utc))
    app = create_app(settings, clock=clock)
    client = TestClient(app)

    human_token = human_tokens.issue(HUMAN_SECRET, user_id, now=clock.now())
    hh = {"Authorization": f"Bearer {human_token}"}

    r = client.post("/api/v1/sessions", json={
        "trip_id": None, "goal_text": goal, "goal_language": "en-IN",
        "spend_cap": spend_cap, "currency": "INR",
    }, headers=hh)
    print("1. GOAL INTAKE -> session created:", r.json()["data"]["session_id"], r.json()["data"]["status"])
    session_id = r.json()["data"]["session_id"]

    client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": goal}, headers=hh)
    print("   dispatched -> status now 'executing'")

    agent_token = agent_tokens.issue(AGENT_SECRET, session_id=session_id, run_id="run_" + "d" * 16, now=clock.now())
    bc = BackendClient(client, agent_token)

    result = run_agent(goal, session_id=session_id, client=bc, today=date(2026, 9, 24))
    print(f"2. AGENT RESULT: status={result.status!r} error_code={result.error_code!r}")
    print(f"   {result.message}")

    if result.status == "awaiting_input":
        print(f"2b. CLARIFICATION ANSWERED: {followup!r}")
        client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": followup}, headers=hh)
        result = run_agent(followup, session_id=session_id, client=bc, previous=result, today=date(2026, 9, 24))
        print(f"    AGENT RESULT (after clarification): status={result.status!r} error_code={result.error_code!r}")
        print(f"    {result.message}")

    if result.cart:
        print(f"3. CART: {len(result.cart.lines)} line(s), agent-side total (pre-tax) ~₹{result.cart.total}")

    session_view = client.get(f"/api/v1/sessions/{session_id}", headers=hh).json()["data"]
    print(f"4. BACKEND SESSION STATE: status={session_view['status']!r} spend_committed={session_view['spend_committed']}")

    confirmation_id = None
    if session_view["status"] == "awaiting_confirmation":
        current = client.get(f"/api/v1/sessions/{session_id}/confirmations/current", headers=hh).json()["data"]
        confirmation_id, snap = current["confirmation_id"], current["snapshot_hash"]
        print(f"5. CONFIRMATION REQUIRED: id={confirmation_id} total={current['total']} cap={current['effective_cap']}")
        print("6. HUMAN CONFIRMS (explicit approve call)...")
        approve = client.post(f"/api/v1/sessions/{session_id}/confirmations/{confirmation_id}/approve",
                              json={"snapshot_hash": snap}, headers=hh)
        if approve.status_code == 200:
            b = approve.json()["data"]
            print(f"   MOCK BOOKING SUCCESS: booking_id={b['booking_id']} ref={b['booking_reference']} total={b['total_amount']}")
        else:
            print(f"   BOOKING REFUSED: {approve.json()}")

    audit = client.get(f"/api/v1/sessions/{session_id}/audit", headers=hh).json()["data"]["events"]
    print(f"\n7. AUDIT TIMELINE ({len(audit)} events, chronological):")
    for e in audit:
        extra = f" [{e['reason_code']}] {e['reason']}" if e.get("reason_code") else ""
        print(f"   {e['seq']:>2}. {e['occurred_at']}  {e['event_type']:<24} actor={e['actor']:<6}{extra}")

    verify = client.get(f"/api/v1/sessions/{session_id}/audit/verify", headers=hh).json()["data"]
    print(f"\n8. AUDIT VERIFY: ok={verify['ok']} chain_ok={verify['chain_ok']} seq_gapless={verify['seq_gapless']}")
    return result.status


if __name__ == "__main__":
    import tempfile
    workdir = tempfile.mkdtemp(prefix="live-demo-")
    print("Working directory (temp, isolated from the original DB):", workdir)
    print("Original DB fingerprint BEFORE:", fingerprint())

    s1 = run_scenario("goa-as-requested", "Plan a 3-day Goa trip from Bengaluru for 2 people under ₹25,000",
                      "25000.00", workdir)
    s2 = run_scenario("working-equivalent-over-cap",
                      "Plan a 3-day trip from Visakhapatnam to New Delhi for 2 people under ₹25,000",
                      "25000.00", workdir, followup="28 Sep 2026 to 30 Sep 2026")
    s3 = run_scenario("working-equivalent-within-cap",
                      "Plan a 3-day trip from Visakhapatnam to New Delhi for 2 people under ₹60,000",
                      "60000.00", workdir, followup="28 Sep 2026 to 30 Sep 2026")

    print("\nOriginal DB fingerprint AFTER: ", fingerprint())
    print(f"\nFINAL: scenario 1 (as literally requested) -> {s1}; "
         f"scenario 2 (real route, same 25k cap) -> {s2}; scenario 3 (real route, 60k cap) -> {s3}")
