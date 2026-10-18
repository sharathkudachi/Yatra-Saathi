"""The HTTP response envelope shared by every agent and human endpoint (section 12).

Kept to the standard library so `app/agent/` and `app/tools/` (Developer 2, a
separate process) can import it without pulling in FastAPI/pydantic.
"""
from __future__ import annotations

from typing import Any, Optional


def ok(data: Optional[dict] = None, *, status: str = "ok") -> dict:
    return {"ok": True, "status": status, "data": data, "refusal": None}


def refused(code: str, message: str, *, audit_event_id: Optional[str] = None,
            status: str = "refused", **extra: Any) -> dict:
    refusal = {"code": code, "message": message, "audit_event_id": audit_event_id}
    refusal.update(extra)
    return {"ok": False, "status": status, "data": None, "refusal": refusal}
