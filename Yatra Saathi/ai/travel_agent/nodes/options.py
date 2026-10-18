# travel_agent/nodes/options.py
"""OPTIONS: offer three trip packages and stop for the user's choice (status awaiting_input).
CHOOSE: once the user picks one, turn it into real offers and continue to budget check + cart.

Only used when the caller asks for choices (`offer_options`, set by ai/service.py for the live
app); a standalone run keeps the original single-plan flow.
"""
from decimal import Decimal
from typing import Any, Dict, List

from backend_client import BackendRefusal
from travel_agent.events import EventLog
from travel_agent.nodes.common import failure_update
from travel_agent.state import MAX_REPLANS, new_plan, set_step
from travel_agent.tools.budget_tools import format_money
from travel_agent.tools.flight_tools import flight_offer
from travel_agent.tools.hotel_tools import hotel_offer
from travel_agent.tool_planner import provenance
from travel_agent.tools.package_tools import _day, build_packages, card, describe, price, to_json

STYLE_ORDER = {"value": ("value", "comfort", "timing"), "comfort": ("comfort", "timing", "value"),
               "timing": ("timing", "comfort", "value"),
               # "cheaper": the three lowest-priced distinct combinations
               "cheapest": ("value", "value", "value")}


def _record_over_cap(state: Dict[str, Any], log: EventLog, styles, cap) -> list:
    """Put over-cap candidates through the backend's own budget check, so every refusal is a
    discrete, reasoned entry in the audit trail (BUDGET_CHECK refused, SPEND_CAP_EXCEEDED):
    the best combination for each style when it exceeds the cap, or the cheapest one when
    nothing fits at all. The backend -- not the agent -- is what refuses."""
    client, session_id = state.get("backend_client"), state.get("session_id")
    refused: list = []
    if client is None or cap is None:
        return refused
    unconstrained = build_packages(state.get("outbound_options") or [], state.get("return_options") or [],
                                   state.get("hotel_options") or [], travellers=state["travellers"], cap=None,
                                   tax_bp=state.get("tax_rate_bp") or 1200, styles=styles,
                                   exclude_hotels=state.get("exclude_hotels") or [], flight_time=state.get("flight_time"))
    over = [p for p in unconstrained if p["total"] > cap][:2]
    for pkg in over:
        out, ret, hotel = pkg["outbound"], pkg["return"], pkg["hotel"]
        args = {"option": pkg["key"], "outbound_fare": out["fare_id"], "return_fare": ret["fare_id"],
                "room_type": hotel["room_type_id"], "estimated_total": f"{pkg['total']:.2f}", "cap": f"{cap:.2f}",
                **provenance(state, "check_budget")}
        try:
            tool_call_id = client.tool_call(session_id, "check_option_budget", args)
            accepted = client.submit_results(session_id, tool_call_id, offers=[
                flight_offer(out, state["travellers"]), flight_offer(ret, state["travellers"]), hotel_offer(hotel)]
            ).get("accepted") or []
            if len(accepted) == 3:
                verdict = client.budget_check(session_id, [a["offer_ref"] for a in accepted])
                log.add("ACTION_REFUSED", "options",
                        f"{pkg['label']} ({hotel['hotel_name']}) refused by the hard spend cap.",
                        reason=f"Total {format_money(Decimal(verdict['total']), state['currency'])} exceeds the cap "
                               f"{format_money(Decimal(verdict['effective_cap']), state['currency'])}.",
                        error_code="over_budget", result={"passed": verdict.get("passed")})
                if not verdict.get("passed"):
                    refused.append((pkg, Decimal(verdict["total"]), Decimal(verdict["effective_cap"])))
        except BackendRefusal:
            continue  # e.g. a room already in the cart from an earlier choice; nothing to add
    return refused


def options_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    client, session_id = state.get("backend_client"), state.get("session_id")
    cur, travellers, cap = state["currency"], state["travellers"], state.get("budget_cap")
    styles = STYLE_ORDER.get(state.get("preference") or "", STYLE_ORDER["value"])
    refused = _record_over_cap(state, log, styles, cap)
    packages = build_packages(state.get("outbound_options") or [], state.get("return_options") or [],
                              state.get("hotel_options") or [], travellers=travellers, cap=cap,
                              tax_bp=state.get("tax_rate_bp") or 1200, styles=styles,
                              exclude_hotels=state.get("exclude_hotels") or [],
                              flight_time=state.get("flight_time"))
    if not packages:
        # Nothing fits the cap: report the cheapest combination and let the replan loop try cheaper strategies.
        cheapest = build_packages(state.get("outbound_options") or [], state.get("return_options") or [],
                                  state.get("hotel_options") or [], travellers=travellers, cap=None,
                                  tax_bp=state.get("tax_rate_bp") or 1200, styles=("value",))
        total = cheapest[0]["total"] if cheapest else Decimal("0.00")
        log.add("ACTION_REFUSED", "options", "No package fits the hard spend cap.",
                reason=f"Cheapest package {format_money(total, cur)} is over the cap {format_money(cap, cur)}.",
                error_code="over_budget", result={"total_cost": total, "budget_cap": cap})
        return {"events": log.events, "within_budget": False, "total_cost": total, "error_code": "over_budget",
                "current_step": "options"}

    fmt = format_money
    replan_count = state.get("replan_count", 0)
    if refused and client is not None:
        # Failure -> re-plan, as a discrete audit entry: the refused option is replaced by ones that fit.
        pkg, total, limit = refused[0]
        reason = (f"{pkg['label']} ({pkg['hotel']['hotel_name']}) totals {fmt(total, cur)}, over the "
                  f"{fmt(limit, cur)} cap by {fmt(total - limit, cur)}: re-planned with options within the cap.")
        try:
            client.replan(session_id, "SPEND_CAP_EXCEEDED", reason)
            replan_count += 1
            log.add("REPLAN", "options", "Re-planned within the spend cap.", reason=reason,
                    arguments={"replan_count": replan_count})
        except BackendRefusal:
            pass  # re-plan limit reached; the options below still all fit the cap
    lines: List[str] = [f"Here {'are' if len(packages) > 1 else 'is'} {len(packages)} way{'s' if len(packages) > 1 else ''} "
                        f"to do {state['origin_name']} → {state['destination_name']}, "
                        f"{_day(state['start_date'])} to {_day(state['end_date'])}, within your {fmt(cap, cur)} cap:"]
    for i, pkg in enumerate(packages, start=1):
        lines.append(describe(pkg, i, cur, travellers, fmt))
    numbers = [str(i) for i in range(1, len(packages) + 1)]
    choices = numbers[0] if len(numbers) == 1 else f"{', '.join(numbers[:-1])} or {numbers[-1]}"
    lines.append(f"Reply with {choices} to choose "
                 f"(or tap Choose). You can also ask me to change it: “cheaper”, “better hotel”, "
                 f"“other hotels”, “morning flights” or new dates.")
    question = "\n".join(lines)
    cards = [{**card(pkg, i, cur), "origin": state["origin_name"], "destination": state["destination_name"]}
             for i, pkg in enumerate(packages, start=1)]
    log.add("CLARIFICATION_REQUIRED", "options", f"Offered {len(packages)} trip option(s) to choose from.",
            result={"options": cards})
    if client is not None:
        client.clarification(session_id, question, options=cards)
    plan = set_step(state["plan"], "budget_check", "done")
    return {"events": log.events, "packages": [{**to_json(p), "index": i} for i, p in enumerate(packages, start=1)],
            "within_budget": True,
            "status": "awaiting_input", "message": question, "clarification_question": question,
            "clarification_required": True, "plan": plan, "current_step": "options", "replan_count": replan_count}


def route_after_options(state: Dict[str, Any]) -> str:
    if state.get("failure"):
        return "fail"
    if state.get("packages"):
        return "end"
    return "replan" if state.get("replan_count", 0) < MAX_REPLANS else "fail"


def _dec(fare: Dict[str, Any]) -> Dict[str, Any]:
    return {**fare, "unit_price": Decimal(str(fare["unit_price"]))}


def choose_node(state: Dict[str, Any]) -> Dict[str, Any]:
    log = EventLog(state)
    client, session_id = state.get("backend_client"), state.get("session_id")
    pkg = state["chosen_package"]
    out, ret = _dec(pkg["outbound"]), _dec(pkg["return"])
    hotel = {**pkg["hotel"], "total_price": Decimal(str(pkg["hotel"]["total_price"])),
             "nightly": [{**n, "price": Decimal(str(n["price"]))} for n in pkg["hotel"]["nightly"]]}
    log.add("PLAN_UPDATED", "choose", f"You chose option {pkg.get('index', '')}: {pkg['label']}.",
            result={"option": pkg["key"]})
    # Searches happened on the earlier turn that offered the options.
    plan = state.get("plan") or new_plan()
    for step in ("understand", "flight_search", "hotel_search", "activity_search"):
        plan = set_step(plan, step, "done")
    if client is not None:
        # Re-offer the chosen flights and room: the backend re-validates and re-prices them.
        args = {"option": pkg["key"], "outbound_fare": out["fare_id"], "return_fare": ret["fare_id"],
                "room_type": hotel["room_type_id"], "requested_by": "user_choice"}
        tool_call_id = client.tool_call(session_id, "choose_option", args)
        try:
            # Switching options replaces the previous choice: clear it before checking the new one.
            previous = (client.get_context(session_id).get("cart") or {}).get("item_group_ids") or []
            for group_id in previous:
                client.remove_cart_item_group(session_id, group_id)
            result = client.submit_results(session_id, tool_call_id, offers=[
                flight_offer(out, state["travellers"]), flight_offer(ret, state["travellers"]), hotel_offer(hotel)])
        except BackendRefusal as exc:
            return _replan_choice(log, plan, pkg, exc.message)
        accepted = result.get("accepted") or []
        if len(accepted) != 3:
            reason = (result.get("rejected") or [{}])[0].get("message") or "part of that option is no longer available"
            return _replan_choice(log, plan, pkg, reason)
        out, ret, hotel = ({**out, "offer_ref": accepted[0]["offer_ref"]}, {**ret, "offer_ref": accepted[1]["offer_ref"]},
                           {**hotel, "offer_ref": accepted[2]["offer_ref"]})
    return {"events": log.events, "selected_outbound": out, "selected_return": ret, "selected_hotel": hotel,
            "selected_activities": [], "plan": plan, "current_step": "choose"}


def _replan_choice(log: EventLog, plan, pkg: Dict[str, Any], why: str) -> Dict[str, Any]:
    """The chosen option can't be booked any more (sold out, price changed): re-plan with fresh
    searches rather than stop -- the user gets new options."""
    reason = f"Option {pkg.get('index', '')} ({pkg['label']}) can't be booked now: {why}."
    log.add("ACTION_REFUSED", "choose", "The chosen option is no longer available.", reason=reason,
            error_code="sold_out")
    return {"events": log.events, "plan": plan, "replan_reason": reason, "replan_code": "SOLD_OUT",
            "chosen_package": None, "current_step": "choose"}


def route_after_choose(state: Dict[str, Any]) -> str:
    if state.get("failure"):
        return "fail"
    if state.get("replan_reason"):
        return "replan" if state.get("replan_count", 0) < MAX_REPLANS else "fail"
    return "budget_check"


def chosen_summary(state: Dict[str, Any]) -> str:
    """Detailed recap of the chosen option for the cart-ready message."""
    pkg = state.get("chosen_package")
    if not pkg:
        return ""
    out, ret, hotel = _dec(pkg["outbound"]), _dec(pkg["return"]), pkg["hotel"]
    hotel = {**hotel, "nightly": [{**n, "price": Decimal(str(n["price"]))} for n in hotel["nightly"]]}
    cost = price(out, ret, hotel, state["travellers"], state.get("tax_rate_bp") or 1200)
    return describe({**pkg, "outbound": out, "return": ret, "hotel": hotel, **cost}, pkg.get("index", 1),
                    state["currency"], state["travellers"], format_money)
