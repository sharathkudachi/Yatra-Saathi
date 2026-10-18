# Architecture

```
Frontend -> FastAPI (human routes, /api/v1)     -> Services -> Repositories -> Working-copy SQLite
Agent service (separate process, ai/) -> HTTP  -> FastAPI (internal agent routes,
                                                    /internal/agent/v1)         -> Services
```

The backend (`backend/`) is the final authority: it owns the database, the spend cap, tax,
pricing, the confirmation gate, and the audit trail. The agent (`ai/`, Developer 2, a
separate process -- a LangGraph workflow wrapped in a small FastAPI service, `ai/service.py`)
**proposes** a plan and offers; the backend **decides** whether they're valid, affordable, and
eventually booked. The agent has no database access and no signing secrets -- it authenticates
to the backend with a short-lived, session-scoped token, and reaches it only through
`ai/backend_client.py`, which wraps the full `/internal/agent/v1/...` contract. There is no
shared Python import between `ai/` and `backend/` at runtime -- see `ai/README.md` for how to
run the agent as its own process, and `tests/ai/test_agent_integration.py` for the real
end-to-end proof (agent -> HTTP -> real backend services -> real cart/confirmation).

## Backend layers (`backend/src/`)

```
api/            FastAPI routes (human + internal-agent), dependencies, error mapping
services/       audit, session, plan, pricing, budget, offer, cart, inventory,
                confirmation, booking, catalog, agent-state services; mock booking provider
db/             connection/transaction plumbing, migrations, one repository per table group
core/           settings, money, clock, ids, hashing, tokens, enums, errors
contracts/      shared envelope/refusal-code definitions -- the only thing `ai/` may import
schemas/        pydantic request models for the human API
middleware/     request id, actor context, request logging
```

## Core invariants

* **Original database protection.** The app only ever opens a stamped, restorable working
  copy; the original `APS-01.db` is verified byte-identical before and after every test run
  and every migration.
* **Hard spend cap.** `MIN(session-created cap, live spend_cap, live budget total)`, checked
  against `committed + cart_total_with_tax` at every mutating step. Every cap check that
  fails writes its own audit trail entry (a failing `BUDGET_CHECK` followed by a refusal) in
  an isolated transaction, so nothing else about the attempted change is ever persisted.
* **Confirmation gate.** A cart can only be booked after a human (never the agent) approves
  a hash-locked snapshot of it, through a token only humans can hold.
* **Audit trail.** Every plan step, tool call, offer, budget check, refusal, re-plan,
  confirmation and booking event is written to a single hash-chained, append-only table and
  can be replayed and verified (`GET /sessions/{id}/audit/verify`).

See `backend/README_BACKEND.md` for setup/run instructions and `data-model/DATA_MODEL.md`
for the schema this is built on.
