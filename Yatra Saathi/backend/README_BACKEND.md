# Tech4ce backend (Developer 1)

Standard library + FastAPI/pydantic/httpx (Python 3.13, SQLite 3.45). Tests use `unittest`
and also run under pytest.

* Milestone 1: foundation, original-database protection, the approved schema.
* Milestone 2: repositories and services (audit trail, budget/cap enforcement, cart,
  confirmation gate, mock booking) -- no HTTP yet.
* Milestone 3: the FastAPI HTTP layer (human + internal-agent routes), tokens, a fake
  agent-service test fixture.
* Milestone 4: demo data + the end-to-end demo story test.

## Setup (from `backend/`)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.backend.example .env.backend        # edit the two absolute paths, and set the three secrets below
set -a; . ./.env.backend; set +a

python -m scripts.make_working_copy          # verify original fingerprint, copy, stamp the copy
python -m scripts.apply_migrations           # approved migrations 0001–0004, working copy only
python -m scripts.verify_db                  # fingerprint, marker, schema, integrity, existing tables unchanged
```

`.env.backend` also needs, for milestone 3+ (generate with e.g. `python -c "import secrets; print(secrets.token_hex(32))"`):

```bash
HUMAN_TOKEN_SECRET=...
AGENT_TOKEN_SECRET=...
AGENT_SERVICE_KEY=...          # shared secret the backend sends to the agent process
AGENT_SERVICE_URL=http://localhost:9000   # Developer 2's agent process; omit if not running one
DEMO_LOGIN_USER_IDS=usr_demo0001          # comma-separated allow-list for /auth/demo-login
```

Restore the working copy at any time: `python -m scripts.make_working_copy --overwrite`
(only ever overwrites a stamped working copy, never the original).

## Running the backend

```bash
uvicorn src.main:app --reload
```

Startup refuses to run unless `APS_DB_PATH` is a stamped, migrated working copy (never the
original). Human routes are under `/api/v1`, internal agent routes under `/internal/agent/v1`.

For the fingerprinted source snapshot that contains the older `agent_carts` and
`agent_confirmations` tables, migration 0001 preserves those rows under
`legacy_agent_*_pre_migration` names before creating the current tables. The rename is part of
the migration transaction; no source-database changes are made.

### Frontend sign-in

* `POST /api/v1/auth/login {"user_id", "display_name", "email"}` -> `{token, user}`. All three
  must match one active row in `users` (name and email compare case-insensitively). Any
  mismatch returns `401 LOGIN_MISMATCH`, whichever field was wrong. Works for every user in the table.
* `GET /api/v1/auth/me` (Bearer token) -> `{user}`; the frontend uses it to restore a session.
* CORS: `CORS_ALLOW_ORIGINS` (defaults to the Vite dev server on port 5173).

The dataset has no passwords, so this matches identity details only. It is fine for the demo
but is not real authentication.

## Demo

```bash
python -m scripts.demo_reset     # fresh working copy + migrations + seeded demo trip/budget/user
uvicorn src.main:app --reload
```

Then, from another shell (or a script/frontend):

1. `POST /api/v1/auth/demo-login {"user_id": "usr_demo0001"}` -> human token.
2. `POST /api/v1/sessions` with `trip_id: trp_demo0001`, `spend_cap: 25000.00`, `currency: INR`
   -> effective cap is `20000.00` (from the seeded budget).
3. `POST /api/v1/sessions/{sid}/messages` to dispatch the agent (needs `AGENT_SERVICE_URL`
   pointing at Developer 2's process, or drive the `/internal/agent/v1/...` routes directly
   the way `tests/fixtures/fake_agent_service.py` does, for a backend-only demo).
4. Approve/decline via `POST /api/v1/sessions/{sid}/confirmations/{cid}/approve|decline`.
5. Inspect `GET /api/v1/sessions/{sid}/audit` and `.../audit/verify`.

`tests/e2e/test_demo_story.py` runs this exact story end-to-end, including a simulated
backend restart between the confirmation request and the approval.

## Agent process (Developer 2)

Implemented, in `ai/` -- a LangGraph agent wrapped in its own small FastAPI service
(`ai/service.py`), run as a genuinely separate process with **no database access and no
backend secrets**. See `ai/README.md` to run it. It only ever talks to
`/internal/agent/v1/...` over HTTP with the session-scoped agent token this backend hands it
when dispatching a run (`AGENT_SERVICE_URL` below); there is no shared Python import between
`ai/` and `backend/`, enforced by `tests/safety/test_agent_isolation.py`.

## Tests

Tests live in `tests/` at the **repo root** (not under `backend/`), so `backend/src` is
importable as `src` from there via `tests/__init__.py` / `tests/conftest.py`. Run from
the repo root:

```bash
export APS_DB_ORIGINAL_PATH=/absolute/path/to/APS-01.db
python -m unittest discover -s tests -t . -v
# or: pytest tests
```

Database tests copy the original into a temporary directory and never write to it.
Every database test module checks the original fingerprint before and after it runs.

## Protection rules

* The application only opens `APS_DB_PATH`, which must be a working copy stamped with
  `PRAGMA application_id = 0x54345743` and must not resolve to `APS_DB_ORIGINAL_PATH`.
* Connections use `mode=rw`, so SQLite can never create a new, empty database by accident.
* Migrations verify the original fingerprint before and after, refuse unstamped targets,
  and refuse any migration file whose SHA-256 differs from the approved one.
* The hard spend cap can never be bypassed: every mutating flow validates as pure reads
  first, then gates on the budget check -- a failing check writes nothing else and persists
  its own refusal audit event in an isolated transaction (see `src/services/budget_service.py`).
