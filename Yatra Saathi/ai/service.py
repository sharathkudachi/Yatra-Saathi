"""The agent as a real separate HTTP process (Option A).

Exposes `POST /runs`, exactly what the backend's `agent_dispatch.HttpAgentDispatcher`
already calls: `{session_id, trigger, reason, agent_run_id, agent_token}`, with
header `X-Service-Key`. Replies 202 immediately and runs the LangGraph workflow
in a background task, talking back to the backend only through `BackendClient`
over HTTP -- this process never opens a database connection.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

for candidate in [Path(__file__).parent / ".env.agent", Path(".env.agent"), Path("ai/.env.agent")]:
    if candidate.exists():
        load_dotenv(candidate)
        break
load_dotenv()

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from backend_client import BackendClient, BackendRefusal
from travel_agent.runner import _CARRY_OVER, IST, run_agent

logger = logging.getLogger("travel_agent.service")

app = FastAPI(title="Tech4ce Travel Agent (Developer 2)")


class RunRequest(BaseModel):
    session_id: str
    trigger: str  # "start" | "resume"
    reason: str
    agent_run_id: str
    agent_token: str


def _known_requirements(client: BackendClient, session_id: str) -> tuple[dict, dict, int]:
    """What is already known before this message: the trip brief the user filled in
    (session constraints), overlaid with what earlier turns of this session established
    (saved agent state). Returns (carry, context, state_version)."""
    context = client.get_context(session_id)
    constraints = context.get("constraints") or {}
    carry = {k: constraints[k] for k in _CARRY_OVER if constraints.get(k) not in (None, "")}
    saved = client.get_state(session_id)
    remembered = (saved.get("state") or {}).get("requirements") or {}
    carry.update({k: v for k, v in remembered.items() if k in _CARRY_OVER and v is not None})
    # Packages offered last turn (so "2" can pick one) and what the user has said they prefer.
    choice = (saved.get("state") or {}).get("choice") or {}
    context["_extras"] = {"offer_options": True, "tax_rate_bp": context.get("tax_rate_bp") or 1200,
                          "pending_packages": choice.get("packages") or [],
                          "preference": choice.get("preference"), "exclude_hotels": choice.get("exclude_hotels") or [],
                          "flight_time": choice.get("flight_time"), "tool_plan": choice.get("tool_plan") or {}}
    # The session's currency is fixed at creation; the cart, cap and booking all use it.
    if context.get("currency"):
        carry["currency"] = context["currency"]
    return carry, context, saved.get("version") or 0


def _remember(client: BackendClient, session_id: str, result, version: int,
              previous_packages: list | None = None) -> None:
    """Save the requirements so the user's next reply only has to fill the gaps."""
    requirements = result.requirements.model_dump(mode="json")
    state = {"requirements": {k: requirements.get(k) for k in _CARRY_OVER},
             "choice": {"packages": result.packages or (previous_packages or []), "preference": result.preference,
                        "exclude_hotels": result.exclude_hotels, "flight_time": result.flight_time,
                        "tool_plan": result.tool_plan}}
    try:
        client.put_state(session_id, state, if_match_version=version or None)
    except BackendRefusal:
        logger.warning("could not save agent state for session %s", session_id, exc_info=True)
        try:  # never lose the trip details themselves
            client.put_state(session_id, {"requirements": state["requirements"]}, if_match_version=version or None)
        except BackendRefusal:
            logger.warning("could not save requirements for session %s", session_id, exc_info=True)


def _run_in_background(body: RunRequest) -> None:
    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
    with httpx.Client(base_url=backend_url, timeout=30.0) as http:
        client = BackendClient(http, body.agent_token)
        try:
            carry, context, version = _known_requirements(client, body.session_id)
            # The session's enforced cap (MIN of the brief's budget and any trip budget) is the
            # ceiling; a budget stated in chat can only lower it.
            result = run_agent(body.reason, session_id=body.session_id, client=client,
                               today=datetime.now(IST).date(), now=datetime.now(timezone.utc),
                               language=context.get("goal_language"), carry=carry,
                               budget_cap=context.get("effective_cap"), extras=context["_extras"])
            # Keep last turn's packages after a choice, so the user can switch to another option.
            _remember(client, body.session_id, result, version, context["_extras"]["pending_packages"])
            logger.info("run %s for session %s finished: %s", body.agent_run_id, body.session_id,
                       result.status)
        except Exception:
            logger.exception("run %s for session %s crashed", body.agent_run_id, body.session_id)
            # Don't leave the session stuck in 'executing': hand control back so the user can retry.
            try:
                client.clarification(body.session_id, "Sorry, something went wrong while I was planning. "
                                                      "Please send your request again.")
            except Exception:
                logger.exception("could not hand session %s back to the user", body.session_id)


@app.post("/runs", status_code=202)
def create_run(body: RunRequest, background_tasks: BackgroundTasks,
               x_service_key: str = Header(default="")):
    expected = os.environ.get("AGENT_SERVICE_KEY", "")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=401, detail="invalid service key")
    background_tasks.add_task(_run_in_background, body)
    return {"accepted": True, "agent_run_id": body.agent_run_id}


@app.get("/health")
def health():
    return {"ok": True}
