# travel_agent/graph.py
"""The LangGraph workflow.

The topology is declared once (NODES / EDGES / ROUTES) and compiled with
LangGraph's StateGraph. If langgraph is not installed yet, `compile_workflow`
falls back to a minimal executor that walks the *same* declaration, so tests run
today; the demo should use real LangGraph (see requirements note in the README
of the final report).
"""
from typing import Any, Callable, Dict, Tuple

from travel_agent.nodes.activity_search import activity_search_node
from travel_agent.nodes.budget_check import budget_check_node, route_after_budget
from travel_agent.nodes.cart import cart_node, route_after_cart
from travel_agent.nodes.clarify import clarify_node
from travel_agent.nodes.fail import fail_node
from travel_agent.nodes.flight_search import flight_search_node
from travel_agent.nodes.hotel_search import hotel_search_node
from travel_agent.nodes.intake import intake_node, route_after_intake
from travel_agent.nodes.options import choose_node, options_node, route_after_choose, route_after_options
from travel_agent.nodes.planner import planner_node
from travel_agent.nodes.replan import replan_node
from travel_agent.state import TravelAgentState

END_NODE = "end"
ENTRY = "intake"
# Worst case: intake, planner, 4 × (3 searches + budget_check), 3 replans, fail ≈ 22 steps.
RECURSION_LIMIT = 40


def _continue_unless_failed(next_node: str) -> Callable[[Dict[str, Any]], str]:
    def route(state: Dict[str, Any]) -> str:
        return "fail" if state.get("failure") else next_node
    route.__name__ = f"route_to_{next_node}"
    return route


# Workflow node -> the plan step it carries out (for PLAN_STEP_* audit entries).
_STEP_OF_NODE = {"planner": "understand", "flight_search": "flight_search", "hotel_search": "hotel_search",
                 "activity_search": "activity_search", "budget_check": "budget_check", "options": "budget_check",
                 "replan": "replan", "cart": "cart"}


def _with_step_events(name: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]):
    """Report each plan step to the backend audit trail as it starts and finishes."""
    key = _STEP_OF_NODE.get(name)
    if key is None:
        return fn

    def wrapped(state: Dict[str, Any]) -> Dict[str, Any]:
        client, session_id = state.get("backend_client"), state.get("session_id")

        def report(event: str, note: Any = None) -> None:
            if client is not None and session_id:
                try:
                    client.plan_step_event(session_id, key, event, note)
                except Exception:  # the audit hint must never break planning
                    pass
        if name != "planner":
            report("started")
        update = fn(state) or {}
        status = next((s.get("status") for s in update.get("plan") or [] if s.get("key") == key), None)
        if update.get("failure") or status == "failed" or (name == "options" and not update.get("packages")):
            report("failed", str(update.get("failure") or update.get("error_code") or "did not succeed")[:300])
        elif status in ("done", "skipped") or name in ("planner", "options"):
            report("completed", "skipped" if status == "skipped" else None)
        return update
    wrapped.__name__ = getattr(fn, "__name__", name)
    return wrapped


NODES: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "intake": intake_node,
    "clarify": clarify_node,
    "planner": planner_node,
    "flight_search": flight_search_node,
    "hotel_search": hotel_search_node,
    "activity_search": activity_search_node,
    "budget_check": budget_check_node,
    "replan": replan_node,
    "cart": cart_node,
    "options": options_node,
    "choose": choose_node,
    "fail": fail_node,
}
NODES = {name: _with_step_events(name, fn) for name, fn in NODES.items()}

EDGES: Dict[str, str] = {
    "clarify": END_NODE,
    "planner": "flight_search",
    "fail": END_NODE,
}

ROUTES: Dict[str, Tuple[Callable[[Dict[str, Any]], str], Tuple[str, ...]]] = {
    "intake": (route_after_intake, ("clarify", "planner", "choose", "fail")),
    # Live app: offer 3 packages and wait for the user's choice; standalone: the original single plan.
    "activity_search": (lambda s: "options" if s.get("offer_options") else "budget_check", ("options", "budget_check")),
    "options": (route_after_options, ("replan", "fail", END_NODE)),
    "choose": (route_after_choose, ("budget_check", "replan", "fail")),
    "flight_search": (_continue_unless_failed("hotel_search"), ("hotel_search", "fail")),
    "hotel_search": (_continue_unless_failed("activity_search"), ("activity_search", "fail")),
    "budget_check": (route_after_budget, ("cart", "replan", "fail")),
    "replan": (_continue_unless_failed("flight_search"), ("flight_search", "fail")),
    "cart": (route_after_cart, ("fail", END_NODE)),
}


def build_langgraph():
    """Compile the workflow with LangGraph. Raises ImportError if it isn't installed."""
    from langgraph.graph import END, START, StateGraph

    def target(name: str):
        return END if name == END_NODE else name

    graph = StateGraph(TravelAgentState)
    for name, fn in NODES.items():
        graph.add_node(name, fn)
    graph.add_edge(START, ENTRY)
    for source, dest in EDGES.items():
        graph.add_edge(source, target(dest))
    for source, (router, dests) in ROUTES.items():
        graph.add_conditional_edges(source, router, {d: target(d) for d in dests})
    return graph.compile()


class FallbackWorkflow:
    """Dev/test stand-in used only when langgraph is missing. Same nodes, edges and routes."""

    engine = "fallback"

    def invoke(self, state: Dict[str, Any], config: Dict[str, Any] | None = None) -> Dict[str, Any]:
        limit = (config or {}).get("recursion_limit", RECURSION_LIMIT)
        state, node = dict(state), ENTRY
        for _ in range(limit):
            state.update(NODES[node](state) or {})
            if node in ROUTES:
                router, allowed = ROUTES[node]
                node = router(state)
                if node not in allowed:
                    raise ValueError(f"route returned unknown node {node!r}")
            else:
                node = EDGES[node]
            if node == END_NODE:
                return state
        raise RecursionError(f"workflow exceeded {limit} steps")


def compile_workflow():
    try:
        workflow = build_langgraph()
        workflow.engine = "langgraph"
        return workflow
    except ImportError:
        return FallbackWorkflow()
