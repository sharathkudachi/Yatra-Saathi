"""A fake agent for tests: drives the internal agent HTTP routes the way the
real (Developer 2) agent process would, using FastAPI's TestClient instead of
a real HTTP call. Also provides a "rogue" variant that tries every bypass
(approving/booking/paying from the agent side, writing audit rows directly,
using another session's token) -- all of which must be refused.
"""
from __future__ import annotations

from typing import Optional

from fastapi.testclient import TestClient

AGENT_PREFIX = "/internal/agent/v1"


class FakeAgentClient:
    """Thin wrapper: every call carries the agent's own Authorization header."""

    def __init__(self, client: TestClient, agent_token: str):
        self.client = client
        self.headers = {"Authorization": f"Bearer {agent_token}"}

    def get_context(self, session_id: str) -> dict:
        r = self.client.get(f"{AGENT_PREFIX}/sessions/{session_id}/context", headers=self.headers)
        return r.json()

    def submit_plan(self, session_id: str, steps: list[dict], **kwargs) -> dict:
        r = self.client.put(f"{AGENT_PREFIX}/sessions/{session_id}/plan",
                            json={"steps": steps, **kwargs}, headers=self.headers)
        return r.json()

    def tool_call(self, session_id: str, tool: str, arguments: dict) -> str:
        r = self.client.post(f"{AGENT_PREFIX}/sessions/{session_id}/tool-calls",
                             json={"tool": tool, "arguments": arguments}, headers=self.headers)
        return r.json()["data"]["tool_call_id"]

    def submit_results(self, session_id: str, tool_call_id: str, offers: list[dict],
                        activities: Optional[list[dict]] = None) -> dict:
        r = self.client.post(f"{AGENT_PREFIX}/sessions/{session_id}/tool-calls/{tool_call_id}/results",
                             json={"offers": offers, "activities": activities or []}, headers=self.headers)
        return r.json()

    def budget_check(self, session_id: str, offer_refs: list[str]) -> dict:
        r = self.client.post(f"{AGENT_PREFIX}/sessions/{session_id}/budget-checks",
                             json={"offer_refs": offer_refs}, headers=self.headers)
        return r.json()

    def add_to_cart(self, session_id: str, offer_refs: list[str]) -> dict:
        r = self.client.post(f"{AGENT_PREFIX}/sessions/{session_id}/cart/items",
                             json={"offer_refs": offer_refs}, headers=self.headers)
        return r.json()

    def request_booking(self, session_id: str) -> dict:
        r = self.client.post(f"{AGENT_PREFIX}/sessions/{session_id}/booking-requests", headers=self.headers)
        return r.json()

    def replan(self, session_id: str, reason_code: str, reason: str,
               caused_by_event_id: Optional[str] = None) -> dict:
        r = self.client.post(f"{AGENT_PREFIX}/sessions/{session_id}/replans",
                             json={"reason_code": reason_code, "reason": reason,
                                   "caused_by_event_id": caused_by_event_id}, headers=self.headers)
        return r.json()

    # --- Rogue bypass attempts, expected to always be refused ---

    def rogue_try_approve_confirmation(self, session_id: str, confirmation_id: str) -> dict:
        """Agent tokens must never work on human routes."""
        r = self.client.post(
            f"/api/v1/sessions/{session_id}/confirmations/{confirmation_id}/approve",
            json={"snapshot_hash": "0" * 64}, headers=self.headers,
        )
        return {"status_code": r.status_code, "body": r.json()}
