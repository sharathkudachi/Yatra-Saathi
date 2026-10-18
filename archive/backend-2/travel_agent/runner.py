# travel_agent/runner.py
"""Entry point: run_agent(...) -> AgentResult.

The signature is a PROPOSAL; how Developer 1 passes session/user/trip context
and resumes after a clarification requires Developer 1 confirmation.

Demo:  python -m travel_agent.runner "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹40,000"
"""
import sys
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from travel_agent.contracts import AgentResult, to_agent_result
from travel_agent.extraction import detect_language
from travel_agent.graph import RECURSION_LIMIT, compile_workflow
from travel_agent.state import DEFAULT_LANGUAGE
from travel_agent.tools.budget_tools import to_money

_CARRY_OVER = ("origin_name", "destination_name", "start_date", "end_date", "travellers",
               "nights", "budget_cap", "currency")


def run_agent(goal: str, *, session_id: Optional[str] = None, language: Optional[str] = None,
              budget_cap: Optional[Decimal | str] = None,
              previous: Optional[AgentResult] = None, today: Optional[date] = None) -> AgentResult:
    """Plan a trip up to CONFIRMATION_REQUIRED. Never books or pays.

    budget_cap: a cap supplied by the backend (e.g. agent_sessions.spend_cap); it can
        only lower the cap stated in the goal, never raise it.
    previous: the result of an earlier awaiting_input turn; its requirements are
        carried over and the new goal text fills in what was missing.
    """
    state: Dict[str, Any] = {
        "session_id": session_id,
        "goal": goal,
        "language": language or (previous.language if previous else None)
                    or detect_language(goal) or DEFAULT_LANGUAGE,
        "today": (today or date.today()).isoformat(),
        "events": [],
        "caller_budget_cap": to_money(budget_cap) if budget_cap is not None else None,
    }
    if previous is not None:
        carried = previous.requirements.model_dump()
        for key in _CARRY_OVER:
            value = carried.get(key)
            if value is not None:
                state[key] = value.isoformat() if isinstance(value, date) else value

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
