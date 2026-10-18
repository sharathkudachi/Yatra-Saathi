"""Dispatches a run to the (separate-process) agent service (section 12).

Backend -> agent: POST {AGENT_SERVICE_URL}/runs, header X-Service-Key, body
session_id/trigger/message-or-reason/agent_run_id/agent token. The agent
replies 202 and does its work asynchronously against the internal agent
routes. In tests, `set_dispatcher` swaps in a fake that runs synchronously.
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol

from src.core import agent_tokens
from src.core.clock import Clock
from src.core.config import Settings
from src.core.ids import new_id


class AgentDispatcher(Protocol):
    def __call__(self, *, session_id: str, trigger: str, reason: str, agent_run_id: str,
                 agent_token: str) -> None: ...


class HttpAgentDispatcher:
    """Real dispatcher: fires the HTTP call and does not wait for the agent to finish."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def __call__(self, *, session_id: str, trigger: str, reason: str, agent_run_id: str,
                 agent_token: str) -> None:
        if not self._settings.agent_service_url:
            return  # No agent process configured (e.g. backend-only demo); nothing to dispatch.
        import httpx
        httpx.post(
            f"{self._settings.agent_service_url}/runs",
            headers={"X-Service-Key": self._settings.agent_service_key or ""},
            json={"session_id": session_id, "trigger": trigger, "reason": reason,
                  "agent_run_id": agent_run_id, "agent_token": agent_token},
            timeout=5.0,
        )


def dispatch(
    settings: Settings, clock: Clock, *, session_id: str, trigger: str, reason: str,
    dispatcher: Optional[AgentDispatcher] = None,
) -> str:
    agent_run_id = new_id("run")
    if not settings.agent_token_secret:
        raise RuntimeError("AGENT_TOKEN_SECRET is not configured")
    agent_token = agent_tokens.issue(settings.agent_token_secret, session_id=session_id,
                                     run_id=agent_run_id, now=clock.now())
    active_dispatcher: AgentDispatcher = dispatcher or HttpAgentDispatcher(settings)
    active_dispatcher(session_id=session_id, trigger=trigger, reason=reason,
                      agent_run_id=agent_run_id, agent_token=agent_token)
    return agent_run_id
