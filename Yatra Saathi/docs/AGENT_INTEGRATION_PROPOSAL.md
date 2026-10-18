# Real-agent ↔ backend integration: findings and proposal

**Superseded.** The bridge described here (a post-run "replay adapter" keeping the agent's
read-only DB access as a temporary exception) was not built. Instead, `travel_agent/` was moved
into `ai/`, wired live to the backend's `/internal/agent/v1/...` routes via `ai/backend_client.py`
(every search, offer, budget check and cart mutation goes through a real backend call as it
happens, not replayed afterward), and the agent's local SQLite reader was removed from that path
entirely -- see `ai/README.md` and `docs/ARCHITECTURE.md`. This resolves the F3/F4 DB-access
exception (item 1 of §8) that this document flagged as needing Developer 1's approval, by making
it unnecessary. `tests/ai/test_agent_integration.py` is the real end-to-end proof.
The findings in §2 (F1-F19) remain accurate background on the two systems' original assumptions
and are kept for reference; the implementation plan in §5 was not followed.

Status (original, kept for context): **proposal only; awaiting approval.** No source code, schema or CSV data was changed to produce this document.
Date: 2026-09-24. Scope: connect the real Developer 2 agent (`backend-2/travel_agent`) to the existing backend (`kv-hack2026-tech4ce/backend`) without disturbing the working frontend ↔ backend flow.

## 1. Executive summary

The backend already defines a complete, tested contract for an agent that runs as a separate process: `POST {AGENT_SERVICE_URL}/runs`, then the agent drives the `/internal/agent/v1/*` routes with a session-scoped token. The real agent is a **synchronous Python function** (`run_agent`) that reads a copy of the original SQLite file directly. It has no HTTP service, token handling or backend calls. The two were built to different assumptions, but both are close to complete. The agent's own tests pass (44 passed, 1 skipped), and the agent produced a real plan → 8 tool calls → refusal → re-plan → cart on a sample goal.

**The smallest safe bridge is a thin adapter service in the agent's package.** It receives `/runs`, calls `run_agent`, and translates the result into the backend's existing internal routes. It needs:

- about three small agent API additions (Developer 2-owned);
- **two small additive backend changes** (Developer 1 approval);
- **one policy decision:** whether the agent may keep read-only access to the original DB for the MVP. The architecture forbids it, and a backend safety test enforces the rule.

Tax consistency is solved without touching either tax implementation. The adapter gives the agent a *pre-tax* cap computed with the backend's exact 12% half-up rule. The backend stays the only authority.

## 2. Confirmed findings, each verified in source

| # | Finding | Evidence |
|---|---|---|
| F1 | The backend invokes the agent with `POST {AGENT_SERVICE_URL}/runs`, header `X-Service-Key`, and body `{session_id, trigger: "start"\|"resume", reason, agent_run_id, agent_token}`. It uses a 5-second timeout and expects an immediate reply, with work continuing asynchronously. If `AGENT_SERVICE_URL` is unset, it silently does nothing. | `backend/src/services/agent_dispatch.py` |
| F2 | The agent has no HTTP entry point. `run_agent(goal, *, session_id, language, budget_cap, previous, today) -> AgentResult` is synchronous and stateless except through `previous`. | `travel_agent/runner.py` |
| F3 | The agent reads SQLite directly (`APS01_DB_PATH`, default `backend-2/data/APS-01.db`, byte-identical to the protected original). It **cannot see bookings or holds the backend writes to its working copy.** | `tools/db.py`; SHA-256 `98e7a525…` |
| F4 | The architecture says "the agent has no DB access". `tests/safety/test_agent_isolation.py` enforces an import rule for `ai/` and `backend/src/agent\|tools`, and requires that `.env.agent.example` has **no DB path**. The agent lives in `backend-2/`, which that test does not scan. | `docs/ARCHITECTURE.md`, the isolation test |
| F5 | The agent's workflow always runs intake → plan → **outbound + return flight search** → hotel search → activity search → budget check → cart. `origin` is a **required** field, so hotel-only trips always produce a clarification. | `graph.py`, `nodes/intake.py` (`_REQUIRED`) |
| F6 | The agent reads only the goal *text*, plus requirements carried over from `previous`. It ignores the session `constraints` (the frontend's destination, dates and travellers). It has **no currency parameter**: currency comes from the text or defaults to INR. | `runner.py`, `nodes/intake.py` |
| F7 | **The agent never applies tax.** It compares pre-tax totals (including activity costs) with the cap. The backend enforces `committed + subtotal + round_half_up(12% × subtotal) ≤ MIN(created cap, live cap, trip budget)` at `cart_add`, `lock` and `final`. | `tools/budget_tools.py`; backend `core/money.py`, `services/budget_service.py` |
| F8 | The agent puts activities (POIs, which have **no inventory ID**) in its cart and budget. The backend rejects `kind: activity` offers as `NOT_BOOKABLE`; activities are informational only. | `nodes/cart.py`; `services/offer_service.py` |
| F9 | The backend accepts only `flight` offers (exactly 1 inventory row) and `hotel_stay` offers (consecutive nights with equal units). The agent emits one `CartLine` per flight leg and **one per night**, with `units = rooms = ceil(travellers / max_adults)`. | both files above |
| F10 | **The agent cannot end a run as `failed`.** The backend state machine forbids `executing → failed`. The only exits are `/clarifications` (`awaiting_input`) and `/booking-requests` (`awaiting_confirmation`). `run-outcome` is informational and changes nothing. | `session_service.ALLOWED_TRANSITIONS`, routes |
| F11 | After `PRICE_CHANGED`, a cap breach at the final check, or a confirmation expiring, the backend reopens the cart and sets `executing`, but **does not dispatch the agent**. Only `/messages` and `/resume` dispatch. `/messages` would then return `INVALID_STATE`, while `/resume` works. | `booking_service.py`, `confirmation_service.py`, `routes/human/sessions.py` |
| F12 | `POST /cart/items` returns only `{cart_id, version, *_minor totals}`, **not `item_group_id`s**, and `/context` does not list cart items. The agent therefore **cannot remove its previous items** from a reopened cart, even though `DELETE /cart/item-groups/{id}` exists. | `services/cart_service.py`, `context.py` |
| F13 | Re-plans are counted per session (`REPLAN_LIMIT=3`, refusal `REPLAN_LIMIT_REACHED`) by the backend, but per run (`MAX_REPLANS=3`) by the agent. | `plan_service.py`, `state.py` |
| F14 | Agent events with no backend route: `REQUIREMENTS_EXTRACTED`, `PLAN_UPDATED`, `CLARIFICATION_REQUIRED`, `AGENT_FAILED`, and the agent-side `BUDGET_CHECK` / `ACTION_REFUSED` / `CART_CREATED` / `CONFIRMATION_REQUIRED`. The backend writes its own versions of the last four when the matching route is called. Agents can never write audit rows directly; the rogue tests enforce this. | `events.py`; backend `EVENT_TYPES` |
| F15 | `/context` exposes `effective_cap`, `committed`, `remaining`, `cart`, `plan`, `replan_count`, `replan_limit`, `constraints` and `goal_language`, but **not `tax_rate_bp`**. | `context.py` |
| F16 | Dispatch happens *after* the session is committed to `executing`. If the agent service is unreachable, `httpx` raises, the request returns 500, and the session stays in `executing`. | `routes/human/sessions.py` |
| F17 | The agent's virtualenv (`backend-2/aps`) is a **Windows** venv and cannot run on this Mac. `langgraph` and `groq` are not installed anywhere locally, so today the agent runs on its built-in `FallbackWorkflow` with the LLM off. `GROQ_API_KEY` sits in both `backend-2/.env` and `backend/.env.backend`; the backend never uses it. | `aps/pyvenv.cfg`, import checks |
| F18 | The spend cap never comes from the LLM: it is parsed deterministically, and a caller cap can only lower it. The LLM fails safe (returns `None`) and falls back to rules. | `nodes/intake.py`, `llm.py` |
| F19 | Agent tokens last 30 minutes and are bound to one session and run. | `core/agent_tokens.py` |

**Measured on a real agent run** (LLM off; goal "Mumbai→Lucknow 16 Nov, 3 nights, 2 people, under ₹40,000"):
- **Agent:** 25 events and 1 re-plan. The agent's cart is ₹35,975.79 pre-tax, which includes ₹1,600 of non-bookable POIs.
- **Backend:** would charge ₹34,375.79 + ₹4,125.09 tax = ₹38,500.88.
- **Why it matters:** here it passes, but with a ₹36,000 cap the agent would say "within budget" and the backend would refuse. That is F7 in practice.

## 3. Contract mismatch table

Classification key: **CM** confirmed implementation mismatch · **MI** missing implementation · **BUG** bug · **UR** unclear requirement · **ADR** architectural decision requiring Developer 1 · **OOS** out of MVP scope.

| Component | Actual backend contract | Actual agent behavior | Mismatch | Risk | Recommended resolution | Approval needed |
|---|---|---|---|---|---|---|
| Agent invocation | `POST /runs` (key header, 5 s timeout, async work) | In-process synchronous `run_agent()` | **MI:** no service | High (blocker) | Adapter service replies 202, then runs `run_agent` on a worker thread | Developer 1: confirm location, port and process (the architecture already intends a separate process) |
| Request / response format | JSON envelope `{ok, data, refusal}`; snake_case; money as strings | Returns a pydantic `AgentResult`; money as `Decimal` | **CM** | Low | Adapter maps between them; money stays exact strings | No |
| Session IDs | `agt_…`, assigned by the backend | Opaque pass-through | None | — | Pass `session_id` straight through | No |
| Authentication | Bearer agent token (30 min, session- and run-bound); `X-Service-Key` on `/runs` | None | **MI** | Medium | Adapter verifies the key (constant-time compare) and sends the token on every call | No |
| Inputs / constraints | `/context`: `goal_text`, `constraints{}`, `currency`, `goal_language`, `effective_cap`, `remaining` | Uses goal text only; no currency parameter (F6) | **CM** | Medium: the agent re-asks for known facts; currency drift causes `CURRENCY_MISMATCH` | Agent: add `currency=` and `requirements=` (seed) parameters, reusing the existing carry-over logic | No (Developer 2); confirm constraint key names with Developer 1 |
| Required origin / flights | Hotel-only offers are valid | Origin mandatory, flights always searched (F5) | **UR** | Medium: every hotel-only request becomes a clarification | MVP: accept (the clarification asks for the departure city). P1: add an origin field to the frontend brief | Team decision: are hotel-only trips in scope? |
| Search tools / data access | Catalog over internal HTTP; no `currencies` or activities routes; `cities` capped at 50 rows | Direct read-only SQLite on an **original-DB copy** (F3) | **ADR** (violates F4) | High: stale availability or prices, since backend bookings are invisible | MVP: temporary, documented exception (the backend re-validates every offer). P2: swap `tools/db.py` for an HTTP catalog client | **Developer 1: yes** |
| Tool-call audit | `POST /tool-calls` returns an id; `POST …/results {offers, activities}` is validated and returns `offer_ref`s | Tool calls run internally; events come out afterwards | **CM** | Medium: audit entries happen after the run finishes, not live | Adapter replays each `TOOL_CALL` / `TOOL_RESULT` pair in order and attaches bookable offers to the searches whose selection ended in the cart | **Developer 1:** is post-run replay acceptable audit semantics? |
| Offer shape | `flight` (1 row) / `hotel_stay` (grouped nights) + `claimed_total` | Per-leg and per-night `CartLine`s, plus POIs (F9) | **CM** | Low | Adapter groups the lines; sends POIs as `activities`; sends `claimed_total` so the backend flags `price_mismatch` | No |
| Budget check | Backend `BUDGET_CHECK` at `cart_add` / `lock` / `final`, tax included; refusal writes `ACTION_REFUSED` | Agent-side check, pre-tax, no route to record it | **CM** | Medium | The backend's check stays authoritative; the agent's own check is kept in agent state | No |
| **Tax** | 12% on the cart subtotal, rounded half-up in minor units (`TAX_RATE_BP`) | None (F7) | **CM** | **High**: carts the agent calls "within budget" get refused | Adapter passes `budget_cap` = the largest pre-tax subtotal S with `S + tax(S) ≤ remaining` (exact integer maths, mirroring `money.tax_minor`). Needs `tax_rate_bp` in `/context` | **Developer 1:** add `tax_rate_bp` to `/context` (additive) |
| Activities | `kind: activity` rejected as `NOT_BOOKABLE`; informational only | Budgeted and carted; re-plan levels 2–3 act on them (F8) | **UR** | Medium: pointless re-plans and a total that doesn't match what's charged | Send as `activities`. Recommend excluding them from the agent's budget in integrated mode (a flag) | Team decision |
| Progress events | Human UI polls the session and `/audit` | Events are only available when the run ends | **CM** | Medium: nothing visible until the end. With the LLM on, a run may take 20–60 s, and the frontend shows "stalled" at 60 s | MVP: accept, and raise the frontend stall threshold. P1: an `on_event` callback in `EventLog` for live streaming | No (P1 is Developer 2 plus a frontend change) |
| Plan | `PUT /plan {steps[], reason_code?}`; `{version, steps}` stored | `PLAN_CREATED` v1 / `PLAN_UPDATED` vN, steps `{index, key, description, status}` | Compatible | Low | Adapter sends `PUT` on each plan event (the re-plan version is sent with `reason_code`) | No |
| Clarification | `POST /clarifications {question}` sets `awaiting_input` | Returns `awaiting_input` + `clarification_question` | Compatible | Low | Adapter posts the question | No |
| Resume after clarification | Backend has no memory of the agent's requirements; `/state` stores versioned JSON (≤1 MB, `If-Match`) | Needs `previous=AgentResult` | **MI** | Medium | Adapter keeps `{previous, item_group_ids}` in `/state` (measured result size: 2–17 KB) | No |
| Failure handling | `executing → failed` not allowed; `run-outcome` is informational (F10) | `status: failed` + `error_code` + reason | **CM / ADR** | High if left unmapped (session stuck) | MVP: adapter posts the failure reason via `/clarifications` (sets `awaiting_input`, which matches the backend's own design). The agent's error code can't be stored | **Developer 1:** allow an optional `error_code` on clarifications → `last_error_code`? |
| Adapter crash / timeout | No watchdog; the session stays `executing` | — | **MI** | High | Adapter wraps each run in a catch-all → clarification "I hit a problem, please try again" | No |
| Dispatch failure | Session committed to `executing` before dispatch; exception returns 500 (F16) | — | **BUG** | Medium | Backend: dispatch before committing, or roll back and refuse, on dispatch errors | **Developer 1: yes** (P1) |
| Re-planning | `/replans` counts per session, limit 3 → `REPLAN_LIMIT_REACHED` | Counts per run, max 3 (F13) | **CM** | Medium: a second run can exceed the backend limit | Agent: `max_replans=` parameter; adapter passes `replan_limit − replan_count`; a refused re-plan ends the run with a clarification | No |
| Re-plan after booking-time failure | `PRICE_CHANGED`, final cap breach or expiry reopen the cart and set `executing`, with **no dispatch** (F11) | — | **MI** | High: stuck session | MVP: frontend calls the existing `POST /resume` when it sees these outcomes; adapter treats `trigger: "resume"` as a re-plan using the stored requirements | **Developer 1:** frontend `/resume` or backend auto-dispatch? |
| Cart creation | `POST /cart/items {offer_refs}` (cap-checked, audited); reopened carts keep their old items | Builds its cart internally | **CM** | Medium | Adapter adds offer refs from the final tool results | No |
| **Cart reuse** | Add response has no `item_group_id`s; `/context` has no items (F12) | — | **MI** | **High**: re-planning after a decline or price change stacks items or hits `DUPLICATE_ITEM` | Backend: return `item_group_ids` from `POST /cart/items` (additive). Adapter deletes stale groups before adding | **Developer 1: yes** |
| Human confirmation | `POST /booking-requests` locks the cart, creates holds and a pending hash-locked confirmation (TTL 900 s); approval is human-only | Stops at `awaiting_confirmation`; never books | Compatible | Low | Adapter calls `/booking-requests` after a successful cart add | No |
| Booking | Mock provider after approval; final re-price and cap check | None, by design | Compatible | — | — | No |
| Audit events | Hash-chained; the backend writes events only through routes | 12 event types, 4 without a route (F14) | **CM** | Low–medium | Mapping in §4.3; unmapped events are kept in agent state | **Developer 1:** should `REQUIREMENTS_EXTRACTED` be audited? |
| Error handling | Refusal codes in the envelope; `TOOL_RESULT` lists rejected offers with codes | Agent error codes (`constraint_infeasible`, `invalid_id`, `low_confidence`, …), several not in `LAST_ERROR_CODES` | **CM** | Low | Adapter maps them to user text in the clarification; backend refusals are logged and end the run safely | See the failure-handling row |
| State persistence | `/state` GET/PUT, versioned, checksummed | `previous` object | **MI** (not wired) | Low | As in the resume row | No |
| LLM / config | Backend never uses an LLM | Groq `openai/gpt-oss-120b`, optional, fail-safe (F17, F18) | Environment gap | Medium | New macOS venv from `backend-2/requirements.txt`; move `GROQ_API_KEY` out of `.env.backend` | Approval to install packages; Developer 1 for their env file |
| Environment | — | Windows venv; langgraph missing, so `FallbackWorkflow` runs | **MI** | Medium: the demo would not run the real LangGraph engine | Create a local venv with the pinned requirements | Your approval |

## 4. Recommended minimum architecture

### 4.1 Options supported by the existing code

| Option | Summary | Verdict |
|---|---|---|
| **A. Adapter service (recommended for MVP)** | New `travel_agent/service.py` (standard-library `ThreadingHTTPServer`, no new framework) implements `/runs`. It runs `run_agent` and replays the result through the existing internal routes. The agent keeps read-only SQLite search on the original DB under a documented, temporary exception. | Smallest change. Uses routes the backend already tests. The backend stays the authority, re-validating every offer, price, unit count, currency and the cap, and computing tax. |
| B. Agent tools over HTTP | Replace `tools/db.py` with a client for `/internal/agent/v1/catalog/*`. | The architecturally correct end state, but it needs backend catalog additions (all cities, currencies, activities) and about 7 N+1 call patterns. **P2.** |
| C. Backend imports the agent in-process | — | Rejected: violates the separate-process design and the isolation tests, and a synchronous LLM call would block a request. |

### 4.2 Run sequence (option A)

```
Backend /messages or /resume ──POST /runs (X-Service-Key)──▶ Adapter: 202 immediately, then on a worker thread:
 1. GET  /context, GET /state                          (goal, constraints, currency, remaining, replans, previous)
 2. DELETE /cart/item-groups/{id} for stale ids         (from state; needs F12 fix)
 3. cap = pre_tax_cap(remaining, tax_rate_bp)           (exact integer maths, backend rounding)
 4. result = run_agent(goal, session_id, language=goal_language, budget_cap=cap, currency=ctx.currency,
                       requirements=seed(constraints), previous=state.previous, max_replans=limit-count)
 5. replay result.events in order (4.3)
 6. PUT  /state {previous: result, item_group_ids}      (If-Match version)
 7. POST /run-outcome {status, message}                 (informational)
 any exception at any step → POST /clarifications "I hit a problem…"  (never leave the session executing)
```

### 4.3 Event → route mapping

| Agent event | Adapter action | Backend writes |
|---|---|---|
| `PLAN_CREATED` | `PUT /plan {steps}` | `PLAN_CREATED` |
| `TOOL_CALL` | `POST /tool-calls {tool: step[:leg], arguments}` | `TOOL_CALL` |
| `TOOL_RESULT` | `POST …/results {offers: bookable selections that ended in the final cart, activities}` | `TOOL_RESULT` (validated, with `offer_ref`s) |
| `BUDGET_CHECK` / `ACTION_REFUSED` (agent) | Kept in agent state; the refusal text feeds the next `REPLAN` reason | *(the backend writes its own at `cart_add`)* |
| `REPLAN` | `POST /replans {reason_code: "SPEND_CAP_EXCEEDED", reason}` | `REPLAN` (+ `ACTION_REFUSED` on limit) |
| `PLAN_UPDATED` | `PUT /plan {steps, reason_code}` | `PLAN_CREATED` v n+1 + `REPLAN` |
| `CART_CREATED` | `POST /cart/items {offer_refs}` | `BUDGET_CHECK`, `CART_CREATED` or `ACTION_REFUSED` |
| `CONFIRMATION_REQUIRED` | `POST /booking-requests` | `CONFIRMATION_REQUIRED` (lock + holds) |
| `CLARIFICATION_REQUIRED` | `POST /clarifications {question}` | `CLARIFICATION_REQUESTED` |
| `AGENT_FAILED` | `POST /clarifications {question: localized failure + what to change}` | `CLARIFICATION_REQUESTED` |
| `REQUIREMENTS_EXTRACTED` | Kept in agent state (pending the Developer 1 decision) | — |

If the backend refuses the cart add despite the pre-tax cap (for example because live prices changed), the adapter ends the run with a clarification that states the backend's refusal. The backend's `ACTION_REFUSED` stays in the audit.

### 4.4 How the 13 requirements are met

| Requirement | Met by |
|---|---|
| 1. Natural-language goal and constraints | `goal_text` + seeded constraints → agent intake (rules, then LLM for gaps) |
| 2. Ordered plan before execution | `PUT /plan` is replayed before the first `TOOL_CALL` in audit order. Wall-clock ordering needs the P1 streaming hook |
| 3. At least 2 genuine tool calls | Real SQLite searches: 2 flight legs, hotel, activity (4 per round). The backend validates the resulting offers |
| 4. Clarification | Agent `awaiting_input` → `/clarifications`; resumed via `/state` |
| 5. Strict cap | Backend check at `cart_add`, `lock` and `final` (tax included), plus the agent's pre-tax cap |
| 6. Refuse or re-plan | Agent re-plan (`/replans` audited); backend `ACTION_REFUSED` if a cart still breaks the cap |
| 7. Cart proposal | `/cart/items` from validated offer refs |
| 8. Human confirmation | `/booking-requests`; human-only approve (existing, tested) |
| 9. Mock booking | Existing `MockBookingProvider` |
| 10. Failure detection + re-plan path | Agent failures → clarification. Booking-time failures → `/resume` → adapter re-plan |
| 11. Consistent tax | One implementation (the backend's); the adapter derives a pre-tax cap with identical rounding |
| 12. Consistent audit | Only backend routes write audit rows; the mapping is fixed in §4.3 |
| 13. No unauthorized DB access | **Not met under option A without Developer 1's exception.** Met by option B (P2) |

## 5. Implementation plan

### P0: required for real-agent MVP integration

| # | Item | Files | Change | Why | Contract | Tests | Risks | Developer 1 approval |
|---|---|---|---|---|---|---|---|---|
| P0-1 | Agent environment | `backend-2/` (new macOS venv, not committed) | `python3 -m venv .venv && pip install -r requirements.txt` | The Windows venv can't run; langgraph and groq are missing | — | Agent suite on the real LangGraph engine; one real LLM run | Network; package versions | No (your approval to install) |
| P0-2 | Return item-group IDs | `backend/src/services/cart_service.py` | Add `item_group_ids: [..]` to the `add_items` result (additive) | F12: the agent can't clear a reopened cart | `POST /cart/items` → `{…, item_group_ids}` | Backend: add → ids → `DELETE` works | Very low | **Yes** |
| P0-3 | Expose the tax rate | `backend/src/api/routes/internal_agent/context.py` | Add `tax_rate_bp` (additive) | Pre-tax cap without duplicating config | `/context` → `{…, tax_rate_bp: 1200}` | Backend context test | Very low | **Yes** |
| P0-4 | Agent API parameters | `travel_agent/runner.py`, `state.py`, `nodes/intake.py`, `nodes/budget_check.py`, `nodes/replan.py` | Optional `currency=`, `requirements=` (seed, via the existing carry-over path), `max_replans=`; currency is fixed when supplied | F6, F13 | Existing callers unchanged (all optional) | Unit tests for each parameter; the 44 existing tests still pass | Low | No (confirm constraint key names) |
| P0-5 | Adapter service | **new** `travel_agent/service.py`, `travel_agent/backend_client.py`, `travel_agent/bridge.py` (mapping + cap maths) | Implements §4.2 and §4.3 using standard-library HTTP (`http.server`, `urllib`); no new dependencies | F1, F2, F10, F14 | `POST /runs` → 202; all backend calls via the §4.3 routes | Unit: cap maths vs. backend rounding (boundary sweep), line→offer grouping, event mapping with a recording fake client, key check, catch-all | Post-run replay latency | **Yes**: new process location and port |
| P0-6 | DB-access exception | `backend-2/.env`, `docs/` note | Agent reads the **original** DB read-only via `APS01_DB_PATH` (never the working copy) | F3, F4 | — | — | Stale availability: the backend re-validates, and the adapter turns refusals into clarifications | **Yes** |
| P0-7 | Configuration | `backend/.env.backend` (`AGENT_SERVICE_URL`, `AGENT_SERVICE_KEY`); `backend-2/.env` (`BACKEND_URL`, same key) | Wire the two processes together | F1 | — | Startup smoke test | Secret handling | Developer 1 for their env |
| P0-8 | Real-agent integration test | **new** `backend-2/tests/integration/test_backend_bridge.py` | Starts the real backend app (uvicorn on a temporary working copy) plus the adapter, and drives human routes | Proves the bridge | — | See §6 | Cross-repo import path | No |
| P0-9 | Real-agent browser E2E | scratchpad `e2e.mjs` (updated); **retire the stand-in** | Mumbai→Lucknow scenario (hotel-only would only clarify) | Final proof | — | See §6 | LLM latency vs. the 60 s stall window | No |

### P1: important, not blocking

| # | Item | Files | Approval |
|---|---|---|---|
| P1-1 | Frontend: an "origin" field in the trip brief → `constraints.origin_name` | `frontend/src/app/App.tsx`, `services/sessionService.ts` | No |
| P1-2 | Frontend: call `POST /resume` after `PRICE_CHANGED`, a final cap breach or `CONFIRMATION_EXPIRED`; "Try again" when stalled; stall threshold raised to about 120 s | same | **Yes** (versus backend auto-dispatch, F11) |
| P1-3 | Backend: don't strand a session when dispatch fails (F16) | `backend/src/api/routes/human/sessions.py` | **Yes** |
| P1-4 | Backend: optional `error_code` on `/clarifications` → `last_error_code` (limited to existing `LAST_ERROR_CODES`) | `routes/internal_agent/clarifications.py` | **Yes** |
| P1-5 | Agent: `on_event` callback in `EventLog` for live progress (plan before tools, even in wall-clock time) | `travel_agent/events.py`, `runner.py`, adapter | No |
| P1-6 | Agent: flag to exclude non-bookable POIs from the budget | `nodes/budget_check.py`, `nodes/cart.py` | Team decision |
| P1-7 | Agent: include inventory IDs in `TOOL_RESULT` "selected", so the adapter can replay the over-cap attempt as a real backend refusal | `nodes/*_search.py` | No |

### P2: future decisions

- **P2-1:** Option B, agent tools over the HTTP catalog. Needs backend routes for currencies, activities and uncapped cities, and removes the P0-6 exception. **Developer 1.**
- **P2-2:** Move `travel_agent/` into the merged repo (`ai/`) so `test_agent_isolation.py` covers it. This is Developer 2's open question 7.
- **P2-3:** Hotel-only planning path in the agent graph (skip flights when there is no origin). Team scope decision.
- **P2-4:** Audit `REQUIREMENTS_EXTRACTED`, or add agent narration storage (a migration, which is checksum-locked). **Developer 1.**

## 6. Test strategy

1. **Regression, which must stay green:** the backend's 120 tests and the agent's 44 tests (on both the Fallback engine and real LangGraph).
2. **Adapter unit tests** (`backend-2/tests/developer2/`, no network):
   - `pre_tax_cap(R, 1200)`: for R across boundaries (0, 1, 112, 11200, 2500000, many random values), `S + tax(S) ≤ R < (S+1) + tax(S+1)`, with `tax` copied from the backend's rule and cross-checked against `src.core.money.tax_minor` in the integration test;
   - cart lines → offers (per-night grouping, units, POIs → activities, `claimed_total`);
   - event → route order, using a recording fake client;
   - catch-all: an exception at any step results in exactly one clarification call;
   - bad or missing `X-Service-Key` → 403, and no run starts.
3. **Real-agent integration** (real `run_agent`, LLM off for determinism; real backend on a temporary working copy; human routes as the frontend uses them):
   - a complete goal → `awaiting_confirmation` → approve → booking. The audit contains the plan, ≥2 tool calls, `BUDGET_CHECK` and `CONFIRMATION_REQUIRED`, and `/audit/verify` is ok;
   - a missing origin → clarification → reply → resumes with carried requirements (via `/state`);
   - Mumbai→Lucknow ₹40,000 → 1 re-plan; backend `replan_count = 1`;
   - a cap where the pre-tax total fits but the total with tax would not → the pre-tax cap prevents a backend refusal;
   - no flights (Goa) → failure surfaced as `awaiting_input` with a reason, never stuck in `executing`;
   - decline → new message → old groups deleted, with no `DUPLICATE_ITEM` and a single-selection cart;
   - an adapter exception → clarification;
   - `PRICE_CHANGED` (inventory price edited in the temporary DB) → `/resume` → re-plan.
4. **Browser E2E:** the existing `e2e.mjs` flow against the real agent, once with the LLM off and once with it on (Groq).

## 7. Risks and unresolved questions

- **Stale data (F3):** the agent can't see bookings made during the demo. The backend refuses unavailable inventory; the adapter explains it and the user retries. This is acceptable for the MVP only if Developer 1 approves the exception.
- **Latency:** with the LLM on, a run may take tens of seconds, and nothing is visible until it finishes (replay after the run). The frontend's 60 s "stalled" message could fire falsely. P1-2 and P1-5 address this.
- **Replay audit semantics:** `occurred_at` records when the event was replayed, not when the agent actually ran the step. The order is preserved.
- **Replan counters** across runs (F13): handled by P0-4, but the backend's limit is per session, so later user turns may be refused re-plans.
- **Hotel-only requests** always clarify (F5). The frontend brief invites them.
- **Secrets:** `GROQ_API_KEY` is present in `backend/.env.backend` (unneeded there) and `backend-2/.env`. Neither file should be committed.
- **Architecture drift:** option A keeps a known exception to "no DB access" until P2-1.

## 8. Items requiring Developer 1's approval

1. Temporary read-only DB access for the agent (original DB only), versus requiring option B before the MVP. (P0-6)
2. Additive: `item_group_ids` in the `POST /cart/items` response. (P0-2)
3. Additive: `tax_rate_bp` in `/context`. (P0-3)
4. The adapter as the agent service: its location (`backend-2/travel_agent/service.py`), port and shared key. (P0-5, P0-7)
5. Post-run event replay as acceptable audit semantics.
6. Failure semantics: clarification-as-failure (the current state machine), plus optional `error_code` → `last_error_code`. (P1-4)
7. Re-plan after booking-time failures: frontend `/resume` or backend auto-dispatch. (P1-2 / F11)
8. Dispatch-failure handling bug. (P1-3)
9. Whether to audit `REQUIREMENTS_EXTRACTED`; constraint key names; the location of `travel_agent/` in the merged repo.

## 9. Proposed implementation sequence

1. P0-1: agent venv, then verify the agent on real LangGraph (LLM off, then on).
2. Get Developer 1's decisions on §8 items 1–5.
3. P0-2 and P0-3: backend additive changes plus tests; the full backend suite stays green.
4. P0-4: agent parameters plus tests; the agent suite stays green.
5. P0-5: adapter, with unit tests first (cap maths, grouping, mapping, catch-all).
6. P0-7 and P0-8: wire configuration; real-agent integration tests.
7. P0-9: browser E2E with the real agent; delete the stand-in.
8. P1 items in the order 2, 3, 1, 5, 4, 6, 7.
