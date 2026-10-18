# Developer 2 — Travel agent: integration notes for Developer 1

The agent plans a trip up to **CONFIRMATION_REQUIRED** and stops. It never books, holds or pays,
and never writes to the database.

## What's in this package

| Path | Contents |
|---|---|
| `travel_agent/` | LangGraph workflow, nodes, tools, prompts, proposed contracts |
| `tests/developer2/` | 45 tests (`python -m pytest tests/developer2` or `python -m unittest discover -s tests/developer2`) |
| `requirements.txt` | Developer 2 dependencies; add yours in the marked section |
| `.gitignore` | Keeps `.env` and `data/APS-01.db` out of git |

Not included: `.env` (secret) and `data/APS-01.db` (use the organiser's copy, unchanged).

## Calling the agent

```python
from travel_agent.runner import run_agent

result = run_agent(
    goal_text,                 # the user's message
    session_id=session_id,     # your ID, echoed on every event (format: your decision)
    language=None,             # BCP-47, e.g. "hi"; auto-detected from script if None
    budget_cap=None,           # e.g. agent_sessions.spend_cap; can only LOWER the user's cap
    previous=None,             # the AgentResult of an earlier "awaiting_input" turn, to resume
)
payload = result.model_dump(mode="json")   # money is serialised as exact strings
```

`result.status` is one of the `agent_status` values from `data/enums.json`:

| Status | Meaning | Your next step |
|---|---|---|
| `awaiting_input` | Clarification needed (`clarification_question`, `missing_fields`) | Ask the user; call again with `previous=result` |
| `awaiting_confirmation` | `cart` ready, total ≤ cap, `confirmation_required = True` | Show cart; on explicit yes → hold/book/pay |
| `failed` | `error_code` (from `error_code` enum) + `failure_reason` | Show message |

The agent never returns `executing` or `completed`; those belong to your booking flow.

## Events (for your audit log)

`result.events` is an ordered list: `seq, type, step, message, timestamp (ISO-8601 + offset),
session_id, arguments, result, reason, error_code`. Types:
`REQUIREMENTS_EXTRACTED, PLAN_CREATED, PLAN_UPDATED, CLARIFICATION_REQUIRED, TOOL_CALL,
TOOL_RESULT, BUDGET_CHECK, ACTION_REFUSED, REPLAN, CART_CREATED, CONFIRMATION_REQUIRED, AGENT_FAILED`.

## Cart lines

Each `cart.lines[]` mirrors `booking_items`: `entity_type` (`flight_fare` / `room_type` / `poi`),
`entity_id`, `inventory_id`, `title`, `for_date`, `units`, `unit_price`, `line_total`, `currency`.
Hold and book against `inventory_id`. The agent checked prices and availability when it searched,
so re-check both at booking time.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `APS01_DB_PATH` | if the DB isn't at `<project root>/data/APS-01.db` | Opened **read-only** |
| `GROQ_API_KEY` | optional | Enables LLM extraction/explanations; without it the agent uses rule-based parsing |
| `TRAVEL_AGENT_LLM_MODEL` | optional | Default `openai/gpt-oss-120b` |
| `TRAVEL_AGENT_DISABLE_LLM` | optional | `1` forces rule-based mode (tests use this) |

The agent does not load `.env` when imported (only `python -m travel_agent.runner` does);
your app's configuration should provide these.

## Needs Developer 1 confirmation

1. `travel_agent/contracts.py` is a **proposal**. Agree on it, then move it to shared `backend/contracts/`.
2. Session ID format; whether `user_id` / `trip_id` are passed in.
3. Where the hard cap comes from: `agent_sessions.spend_cap` or `budgets.total_amount`.
4. Keep the agent's read-only SQLite reader, or swap in your repository.
5. Resume via `previous=` (current) or via your saved state.
6. Event IDs and persistence; cart ID and persistence.
7. Where `travel_agent/` lives in the merged repo (root or `backend/`); imports use `travel_agent.*`.

Demo: `python -m travel_agent.runner "Plan a 3-night trip from Mumbai to Lucknow on 16 Nov 2026 for 2 people under ₹40,000"`
(there are no Goa flights in the dataset).
