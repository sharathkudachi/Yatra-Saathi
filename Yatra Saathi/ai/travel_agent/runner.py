# travel_agent/runner.py
"""Entry point: run_agent(...) -> AgentResult.

The signature is a PROPOSAL; how Developer 1 passes session/user/trip context
and resumes after a clarification requires Developer 1 confirmation.

Demo:  python -m travel_agent.runner "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹40,000"
"""
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from travel_agent.contracts import AgentResult, to_agent_result
from travel_agent.extraction import detect_language
from travel_agent.graph import RECURSION_LIMIT, compile_workflow
from travel_agent.state import DEFAULT_LANGUAGE
from travel_agent.tools.budget_tools import to_money

# The dataset's timezone: "today" for trip dates is the calendar day in India.
IST = timezone(timedelta(hours=5, minutes=30))

_CARRY_OVER = ("origin_name", "destination_name", "start_date", "end_date", "travellers",
               "nights", "budget_cap", "currency")


def run_agent(goal: str, *, session_id: Optional[str] = None, language: Optional[str] = None,
              budget_cap: Optional[Decimal | str] = None,
              previous: Optional[AgentResult] = None, today: Optional[date] = None,
              client: Optional[Any] = None, carry: Optional[Dict[str, Any]] = None,
              extras: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> AgentResult:
    """Plan a trip up to CONFIRMATION_REQUIRED. Never books or pays.

    budget_cap: a cap supplied by the backend (e.g. agent_sessions.spend_cap); it can
        only lower the cap stated in the goal, never raise it.
    previous: the result of an earlier awaiting_input turn; its requirements are
        carried over and the new goal text fills in what was missing.
    carry: plain-JSON requirements known before this message (the trip brief and
        what earlier turns of the same session established; see ai/service.py).
        Same role as `previous`; the new goal text still overrides any of them.
    now: the current instant (timezone-aware); flights that have already left are not
        offered. Defaults to the real time unless `today` pins a date (tests).
    client: a `backend_client.BackendClient`, required when driven by the real
        backend (`session_id` must also be set). When omitted, every node falls
        back to its own local, read-only SQLite copy for a standalone/offline run.
    """
    if now is None and today is None:
        now = datetime.now(timezone.utc)
    state: Dict[str, Any] = {
        "session_id": session_id,
        "goal": goal,
        "language": language or (previous.language if previous else None)
                    or detect_language(goal) or DEFAULT_LANGUAGE,
        "today": (today or datetime.now(IST).date()).isoformat(),
        "now": now.isoformat() if now else None,
        "events": [],
        "caller_budget_cap": to_money(budget_cap) if budget_cap is not None else None,
        "backend_client": client,
    }
    if previous is not None:
        carried = previous.requirements.model_dump()
        for key in _CARRY_OVER:
            value = carried.get(key)
            if value is not None:
                state[key] = value.isoformat() if isinstance(value, date) else value

    for key in _CARRY_OVER:
        value = (carry or {}).get(key)
        if value is not None:
            state[key] = to_money(value) if key == "budget_cap" else value

    # Non-requirement context from the caller (e.g. offer_options, pending_packages, preference).
    state.update(extras or {})

    workflow = compile_workflow()
    final = workflow.invoke(state, config={"recursion_limit": RECURSION_LIMIT})
    return to_agent_result(final, getattr(workflow, "engine", "langgraph"))


def _print_result(result: AgentResult) -> None:
    print(f"[engine: {result.engine}]")
    for event in result.events:
        line = f"{event.seq:>2}. {event.type:<22} {event.step:<18} {event.message}"
        if event.reason:
            line += f"\n    reason: {event.reason}"
        print(line)
    print(f"\nSTATUS: {result.status}\n{result.message}")


if __name__ == "__main__":
    # Standalone demo only: read GROQ_API_KEY from a local .env. When embedded in
    # Developer 1's app, configuration comes from their environment instead.
    try:
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv(usecwd=True))
    except ImportError:
        pass
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _print_result(run_agent(" ".join(sys.argv[1:]) or
                            "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹40,000"))
