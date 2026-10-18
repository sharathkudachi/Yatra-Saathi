# travel_agent/nodes/clarify.py
"""CLARIFICATION: ask only for what is missing, then stop (status awaiting_input)."""
from typing import Any, Dict

from travel_agent.events import EventLog
from travel_agent.llm import generate_text
from travel_agent.messages import _MESSAGES, message

_FIELD_KEYS = {"origin": "field.origin", "destination": "field.destination",
               "start_date": "field.start_date", "end_date": "field.end_date",
               "travellers": "field.travellers", "budget_cap": "field.budget_cap"}


def build_question(language: str, missing: list, issues: list) -> str:
    lines = [message(language, "clarify_intro")]
    lines += [f"{i}. {message(language, _FIELD_KEYS[f])}" for i, f in enumerate(missing, start=1)]
    return "\n".join(issues + lines)


def clarify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    language = state.get("language", "en-IN")
    missing = state.get("missing_fields", [])
    issues = state.get("input_issues", [])
    question = build_question(language, missing, issues)
    if language not in _MESSAGES:  # no template for this language: let the LLM phrase it
        question = generate_text("clarify", language=language,
                                 missing=", ".join(missing), issues="; ".join(issues) or "none") or question
    log.add("CLARIFICATION_REQUIRED", "clarify", "More information is needed before searching.",
            arguments={"missing_fields": missing, "issues": issues}, result={"question": question})
    return {"events": log.events, "clarification_question": question,
            "status": "awaiting_input", "message": question, "current_step": "clarify"}
