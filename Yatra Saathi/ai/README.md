# Agent (Developer 2, integrated via Option A)

A LangGraph-based travel-planning agent (`travel_agent/`), wrapped in a small
FastAPI service (`service.py`) so it runs as a genuinely separate process from
the backend, talking to it only over HTTP.

## Running it

```bash
cd ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.agent.example .env.agent && set -a; . ./.env.agent; set +a

uvicorn service:app --port 9000
```

Point the backend's `AGENT_SERVICE_URL` at this (`http://localhost:9000`) and
give both processes the same `AGENT_SERVICE_KEY`.

## How it fits together

* Backend → agent: `POST /runs` (`X-Service-Key` header) — replies `202` and
  runs the workflow in the background.
* Agent → backend: every call goes through `backend_client.BackendClient`,
  which wraps the full `/internal/agent/v1/...` contract (context, plan,
  tool-calls, catalog, results, budget-checks, cart, replans, clarifications,
  booking-requests, state, run-outcome), authenticated with the session-scoped
  agent token the backend handed it in the `/runs` call. This is the *only*
  way the agent reaches the backend -- there is no shared Python import across
  the process boundary, and this process **never opens a database connection**.
* `travel_agent/tools/*.py` has two paths: when a `BackendClient` is present in
  the graph's state (the real, integrated run), every search goes through the
  backend's catalog routes; when it's absent (standalone CLI demo, or
  `tests/ai/unit/`, Developer 2's own 45 tests), it falls back to a local,
  read-only SQLite copy exactly as originally built. Both paths are exercised
  by the test suite (`tests/ai/unit/` for the local path,
  `tests/ai/test_agent_integration.py` for the real backend path).
* Cart, pricing, tax, the hard spend cap, and the confirmation gate are never
  decided by the agent. It proposes offers (`POST /tool-calls/{id}/results`)
  and asks advisory questions (`POST /budget-checks`); only the backend's own
  `offer_service`/`pricing_service`/`budget_service`/`confirmation_service`
  ever write a cart row, apply tax, or gate a booking. Activity (POI) lines are
  informational only and are never sent to the backend as bookable items --
  the backend's schema doesn't accept them (`NOT_BOOKABLE`), and there's no
  backend catalog route for them at all (no approved activities dataset).

See `docs/ARCHITECTURE.md` for the full picture and
`tests/safety/test_agent_isolation.py` for the enforced import boundary
(this code may only reach the backend over HTTP, never by importing
`backend/src/*`).

## Known simplifications (flagged, not hidden)

* No backend catalog route exists for activities/POIs (matches the approved
  "no activities dataset" decision) -- the integrated path always reports zero
  activities found; this never blocks a booking since activities were already
  optional.
* The backend's catalog routes return raw IDs (airline_id, airport_id) rather
  than display names/IATA codes, since there's no `/catalog/airlines` route --
  cosmetic only, doesn't affect pricing or booking correctness.
* City resolution in `intake` currently trusts an `{"INR"}`-only currency set
  when running through the backend (no `/catalog/currencies` route exists);
  fine for every approved demo scenario, which is INR-only.
