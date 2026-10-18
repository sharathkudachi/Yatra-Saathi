"""The agent's only way to reach the backend: one HTTP client wrapping every
`/internal/agent/v1/...` route (section 12). No database access, no shared
Python imports with `backend/` -- just the documented JSON wire contract, so
this stays a genuinely separate process (or a separate venv, or eventually a
different language) from the backend.

`http` is anything with `.get/.post/.put/.delete(path, json=, headers=)` that
returns an object with `.status_code` and `.json()` -- a real `httpx.Client`
in production, or FastAPI's `TestClient` in tests (same interface, no network).
"""
from __future__ import annotations

from typing import Any, Optional

AGENT_PREFIX = "/internal/agent/v1"


class BackendRefusal(Exception):
    """The backend refused the request. `code`/`message` mirror the envelope's `refusal`."""

    def __init__(self, code: str, message: str, status_code: int, details: Optional[dict] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class BackendClient:
    def __init__(self, http: Any, agent_token: str):
        self.http = http
        self.headers = {"Authorization": f"Bearer {agent_token}"}

    @staticmethod
    def _unwrap(response: Any) -> dict:
        body = response.json()
        if not body.get("ok"):
            refusal = body.get("refusal") or {}
            raise BackendRefusal(refusal.get("code", "UNKNOWN"), refusal.get("message", ""),
                                 response.status_code, refusal)
        return body.get("data") or {}

    def _get(self, path: str, **params) -> dict:
        clean = {k: v for k, v in params.items() if v is not None}
        return self._unwrap(self.http.get(f"{AGENT_PREFIX}{path}", params=clean, headers=self.headers))

    def _post(self, path: str, json: Optional[dict] = None) -> dict:
        return self._unwrap(self.http.post(f"{AGENT_PREFIX}{path}", json=json or {}, headers=self.headers))

    def _put(self, path: str, json: Optional[dict] = None, extra_headers: Optional[dict] = None) -> dict:
        headers = {**self.headers, **(extra_headers or {})}
        return self._unwrap(self.http.put(f"{AGENT_PREFIX}{path}", json=json or {}, headers=headers))

    def _delete(self, path: str) -> dict:
        return self._unwrap(self.http.delete(f"{AGENT_PREFIX}{path}", headers=self.headers))

    # --- context, plan, plan-step events ---

    def get_context(self, session_id: str) -> dict:
        return self._get(f"/sessions/{session_id}/context")

    def submit_plan(self, session_id: str, steps: list[dict], *, reason_code: Optional[str] = None,
                     caused_by_event_id: Optional[str] = None, reason: Optional[str] = None) -> dict:
        return self._put(f"/sessions/{session_id}/plan", {
            "steps": steps, "reason_code": reason_code, "caused_by_event_id": caused_by_event_id,
            "reason": reason,
        })

    def plan_step_event(self, session_id: str, step_id: str, event: str, note: Optional[str] = None) -> dict:
        return self._post(f"/sessions/{session_id}/plan/steps/{step_id}/events",
                          {"event": event, "note": note})

    # --- tool calls, catalog, results ---

    def tool_call(self, session_id: str, tool: str, arguments: dict) -> str:
        return self._post(f"/sessions/{session_id}/tool-calls",
                          {"tool": tool, "arguments": arguments})["tool_call_id"]

    def catalog_flights(self, session_id: str, *, origin_airport_id=None, dest_airport_id=None,
                         depart_date=None) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/flights", origin_airport_id=origin_airport_id,
                         dest_airport_id=dest_airport_id, depart_date=depart_date)["rows"]

    def catalog_fares(self, session_id: str, flight_id: str) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/fares", flight_id=flight_id)["rows"]

    def catalog_hotels(self, session_id: str, *, city_id=None) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/hotels", city_id=city_id)["rows"]

    def catalog_room_types(self, session_id: str, hotel_id: str) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/room-types", hotel_id=hotel_id)["rows"]

    def catalog_inventory(self, session_id: str, entity_type: str, entity_id: str, *,
                           start_date=None, end_date=None) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/inventory", entity_type=entity_type,
                         entity_id=entity_id, start_date=start_date, end_date=end_date)["rows"]

    def catalog_cities(self, session_id: str, *, name_like=None) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/cities", name_like=name_like)["rows"]

    def catalog_currencies(self, session_id: str) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/currencies")["rows"]

    def catalog_airports(self, session_id: str, *, city_id=None) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/airports", city_id=city_id)["rows"]

    def catalog_activities(self, session_id: str, *, city_id=None, city_name=None, currency=None) -> list[dict]:
        return self._get(f"/sessions/{session_id}/catalog/activities", city_id=city_id,
                         city_name=city_name, currency=currency)["rows"]


    def submit_results(self, session_id: str, tool_call_id: str, *, offers: Optional[list[dict]] = None,
                        activities: Optional[list[dict]] = None, error: Optional[str] = None) -> dict:
        return self._post(f"/sessions/{session_id}/tool-calls/{tool_call_id}/results", {
            "offers": offers or [], "activities": activities or [], "error": error,
        })

    # --- budget, cart, replan, clarification, booking ---

    def budget_check(self, session_id: str, offer_refs: list[str]) -> dict:
        return self._post(f"/sessions/{session_id}/budget-checks", {"offer_refs": offer_refs})

    def add_cart_items(self, session_id: str, offer_refs: list[str]) -> dict:
        return self._post(f"/sessions/{session_id}/cart/items", {"offer_refs": offer_refs})

    def remove_cart_item_group(self, session_id: str, item_group_id: str) -> dict:
        return self._delete(f"/sessions/{session_id}/cart/item-groups/{item_group_id}")

    def replan(self, session_id: str, reason_code: str, reason: str,
               caused_by_event_id: Optional[str] = None) -> dict:
        return self._post(f"/sessions/{session_id}/replans", {
            "reason_code": reason_code, "reason": reason, "caused_by_event_id": caused_by_event_id,
        })

    def clarification(self, session_id: str, question: str, options: Optional[list] = None,
                      suggestions: Optional[list] = None) -> dict:
        body = {"question": question, **({"options": options} if options else {}),
                **({"suggestions": suggestions} if suggestions else {})}
        return self._post(f"/sessions/{session_id}/clarifications", body)

    def request_booking(self, session_id: str) -> dict:
        return self._post(f"/sessions/{session_id}/booking-requests")

    # --- agent state, run outcome ---

    def get_state(self, session_id: str) -> dict:
        return self._get(f"/sessions/{session_id}/state")

    def put_state(self, session_id: str, state: dict, if_match_version: Optional[int]) -> dict:
        extra = {} if if_match_version is None else {"If-Match": str(if_match_version)}
        return self._put(f"/sessions/{session_id}/state", state, extra_headers=extra)

    def run_outcome(self, session_id: str, status: str, message: str = "") -> dict:
        return self._post(f"/sessions/{session_id}/run-outcome", {"status": status, "message": message})

    # --- Phase 3 comparison & budget optimization ---

    def compare_travel_options(self, session_id: str, payload: dict) -> dict:
        return self._post(f"/sessions/{session_id}/comparison/options", payload)

    def optimize_trip(self, session_id: str, payload: dict) -> dict:
        return self._post(f"/sessions/{session_id}/comparison/optimize", payload)

    # --- Phase 4 Preferences & Destination/Hotel Exploration ---

    def get_preferences(self, session_id: str) -> dict:
        return self._get(f"/sessions/{session_id}/preferences")

    def propose_preferences(self, session_id: str, payload: dict) -> dict:
        return self._post(f"/sessions/{session_id}/preferences/proposals", payload)

    def explore_destination(self, session_id: str, payload: dict) -> dict:
        return self._post(f"/sessions/{session_id}/destinations/explore", payload)

    def explore_hotels(self, session_id: str, payload: dict) -> dict:
        return self._post(f"/sessions/{session_id}/hotels/explore", payload)

    def add_itinerary_activity(self, session_id: str, itinerary_id: str, payload: dict) -> dict:
        return self._post(f"/sessions/{session_id}/itineraries/{itinerary_id}/activities/add", payload)

    def select_itinerary_hotel(self, session_id: str, itinerary_id: str, payload: dict) -> dict:
        return self._post(f"/sessions/{session_id}/itineraries/{itinerary_id}/hotel/select", payload)

