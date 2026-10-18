"""LLM function calling: the model's tool calls are used only when their arguments match the
requirements; anything else falls back to the workflow, and the audit says which was which."""
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from travel_agent import tool_planner

STATE = {"origin_name": "Mumbai", "destination_name": "Lucknow", "start_date": "2026-11-16",
         "end_date": "2026-11-19", "travellers": 2, "budget_cap": Decimal("45000.00"), "currency": "INR"}


def fake_client(calls):
    tool_calls = [SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
                  for i, (n, a) in enumerate(calls)]
    message = SimpleNamespace(tool_calls=tool_calls)
    create = mock.Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=message)]))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), create


class ToolPlannerTests(unittest.TestCase):
    def test_model_calls_with_matching_arguments_are_credited_to_the_model(self):
        exp = tool_planner.expected_calls(STATE)
        client, create = fake_client([
            ("search_flights", exp["search_flights:outbound"]), ("search_flights", exp["search_flights:return"]),
            ("search_hotels", exp["search_hotels"]),
            ("check_budget", {"cap": "45000.00", "currency": "INR"})])
        with mock.patch.object(tool_planner, "llm_enabled", return_value=True), \
             mock.patch.object(tool_planner, "_client", return_value=client):
            plan = tool_planner.plan_tool_calls(STATE)
        self.assertTrue(all(e["requested_by"] == "llm_function_call" for e in plan.values()), plan)
        self.assertEqual(create.call_args.kwargs["tool_choice"], "required")
        self.assertEqual({t["function"]["name"] for t in create.call_args.kwargs["tools"]},
                         {"search_flights", "search_hotels", "check_budget"})

    def test_wrong_arguments_are_rejected_and_the_workflow_steps_in(self):
        exp = tool_planner.expected_calls(STATE)
        client, _ = fake_client([("search_flights", {**exp["search_flights:outbound"], "date": "2026-11-17"}),
                                 ("search_hotels", exp["search_hotels"])])
        with mock.patch.object(tool_planner, "llm_enabled", return_value=True), \
             mock.patch.object(tool_planner, "_client", return_value=client):
            plan = tool_planner.plan_tool_calls(STATE)
        self.assertEqual(plan["search_flights:outbound"]["requested_by"], "workflow")
        self.assertEqual(plan["search_flights:outbound"]["llm_arguments_rejected"], {"date": "2026-11-17"})
        self.assertEqual(plan["search_hotels"]["requested_by"], "llm_function_call")
        self.assertEqual(plan["search_flights:return"]["requested_by"], "workflow")  # the model never asked

    def test_without_an_llm_the_workflow_issues_every_call(self):
        with mock.patch.object(tool_planner, "llm_enabled", return_value=False):
            plan = tool_planner.plan_tool_calls(STATE)
        self.assertEqual({e["requested_by"] for e in plan.values()}, {"workflow"})

    def test_model_errors_fall_back(self):
        broken = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=mock.Mock(side_effect=RuntimeError("quota")))))
        with mock.patch.object(tool_planner, "llm_enabled", return_value=True), \
             mock.patch.object(tool_planner, "_client", return_value=broken):
            plan = tool_planner.plan_tool_calls(STATE)
        self.assertEqual({e["requested_by"] for e in plan.values()}, {"workflow"})
