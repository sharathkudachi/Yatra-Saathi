# Frontend ↔ Backend mismatch report

Audit date: 2026-09-24. No code was changed while this audit was carried out.

## Sources of truth, in priority order

1. **Project requirements.** The problem statement lives in the hackathon app and is not in the repo. The written requirements available are `APS-01_AgenticConcierge/README.md` and `data/WORKING_WITH_THE_DATA.md` (R1–R8: money is a 2-decimal string, IDs are opaque, language is BCP-47, nothing is hard-deleted), plus the team's `docs/ARCHITECTURE.md`. The architecture doc says: *the backend is the final authority*; there is a hard spend cap, a human-only confirmation gate, and a hash-chained audit trail; and the agent is a separate process with **no DB access**.
2. **Database.** `APS-01.db` has 1,201 users in the working copy. 458 of them own trips, and every trip's budget currency matches the trip currency. The 5 agent tables come from migrations 0001 and 0002.
3. **Backend.** `kv-hack2026-tech4ce/backend`, a FastAPI app with 117 passing tests. Human routes live under `/api/v1`; agent routes under `/internal/agent/v1`.
4. **Frontend.** `…/frontend`. Its own `API_HANDOFF.md` says its routes are *"a proposed frontend contract, not an API contract already implemented by the backend team"*.
5. **Agent.** `backend-2/travel_agent` (Developer 2). Its `DEVELOPER2_INTEGRATION.md` lists 7 items that *"need Developer 1 confirmation"*.

## The flow the backend actually implements

```
POST /api/v1/auth/login                                  → token
POST /api/v1/sessions {goal_text, goal_language, constraints, spend_cap, currency, trip_id?}
POST /api/v1/sessions/{id}/messages {message}            → status "executing", dispatches the agent (async)
   agent (separate process) → /internal/agent/v1/...: plan, tool-calls, results, cart/items
                              (cap-checked), replans, clarifications, booking-requests
GET  /api/v1/sessions/{id}          (poll)  status: planning | executing | awaiting_input |
                                             awaiting_confirmation | paused | completed | failed
GET  /api/v1/sessions/{id}/audit            plan / tool calls / budget checks / refusals / re-plans
GET  /api/v1/sessions/{id}/cart
GET  /api/v1/sessions/{id}/confirmations/current   → snapshot_hash, totals, effective_cap, expires_at
POST /api/v1/sessions/{id}/confirmations/{cid}/approve {snapshot_hash} → mock booking
POST /api/v1/sessions/{id}/confirmations/{cid}/decline {note}
GET  /api/v1/sessions/{id}/booking,  GET …/audit/verify
```

The frontend instead expects one **synchronous** call per turn (`POST /api/agent/turn`), plus direct search, budget, itinerary and hold routes. None of those exist on the backend.

## Mismatch table

Correct side: **A** = adapt the frontend to the backend · **B** = fix the backend · **C** = both need to change · **D** = needs a human or Developer 1 decision.

| # | Area | Frontend currently does | Backend currently does | Expected behavior | Correct side | Required change | Confidence |
|---|---|---|---|---|---|---|---|
| 1 | Auth / user info | *(fixed earlier)* Logs in with user_id, name and email; stores a bearer token | `POST /auth/login`, `GET /auth/me`, CORS for :5173 | Every session route needs a human bearer token | — | Already done; agent calls must also send the token | High |
| 2 | User goal (agent turn) | `POST /api/agent/turn` `{message, goalLanguage, tripRequest}` and waits for `AgentTurnResponse` | Async: `POST /sessions` then `POST /sessions/{id}/messages`; the result is read by polling | The backend's session model is the contract; the agent runs asynchronously | A | Frontend creates a session, sends messages and polls. Remove `/api/agent/turn` in live mode | High |
| 3 | Constraints | camelCase `TripRequest` (`destination, startDate, endDate, travellers, budget, preferences`) | `constraints` is a free-form dict passed to the agent through `/context` | Keys the agent understands. Its only documented schema is `TripRequirements`: `destination_name, start_date, end_date, travellers, currency, language` | A | Map TripRequest onto those snake_case keys. Developer 2 should confirm (item 1 of their list) | Medium |
| 4 | Spend-cap input | Free-text budget such as `25000`, `25,000` or `25000.555`, sent unchecked | `spend_cap` parsed with a strict 2-decimal regex. **Malformed input causes an unhandled `MoneyError`, so HTTP 500** | Invalid input gets a 4xx validation error, never a 500 | C | Backend: validate in the request schema (422). Frontend: normalize to 2 decimals, validate before sending, and show the error | High |
| 5 | Currency | Picks from 10 codes (all exist in `currencies`) | An unknown currency hits the FK constraint (**500**); a format check is also missing | 4xx refusal | B | Validate `^[A-Z]{3}$` and check the currency exists (`MALFORMED_ITEM`, the same code `create_session` already uses for bad input) | High |
| 6 | Transparent plan | Shows `toolSteps: string[]` from the synchronous response | The plan is stored in `plan_steps_json` and audit `PLAN_CREATED`. The **human** session view omits `plan`; only the agent's `/context` returns it | The user can see the plan | C | Backend: add `plan` to the human session view (additive, already computed for `/context`). Frontend: render the plan steps | High |
| 7 | Search / tool calls | Shows the tool steps it gets back | `TOOL_CALL` / `TOOL_RESULT` audit events via `GET /audit` | Tool calls shown from the audit trail | A | Frontend renders a timeline from `GET /audit` | High |
| 8 | Direct hotel search | `POST /api/search/hotels` (in mock mode it reads a static extract of the DB) | **No human search route.** The catalog is only available to the agent token | Unclear: is search agent-only (the architecture says the agent proposes) or can users also search? | **D** | Decide whether to add human catalog routes. Until then, live mode gets a 404 on this panel | — |
| 9 | Flight search | `POST /api/search/flights` | Not on the human side | Same as #8 | **D** | Same as #8 | — |
| 10 | Explore page | Uses `searchHotels` and the static catalog | None | Same as #8 | **D** | Same as #8 | — |
| 11 | Budget check / display | `POST /api/budget {tripRequest}` returns `{total, committed, planned}` | No such route. The session view has `spend_cap` (not the *effective* cap) and the raw `spend_committed` column. The effective cap, remaining amount and cap source are **only** in the agent's `/context` | The user sees the cap that is actually enforced: `MIN(created cap, live cap, trip budget)`, plus committed, cart total with tax, and remaining | C | Backend: add `effective_cap, cap_source, committed, cart_total, remaining` to the session view, using the `/context` logic. Frontend: build the budget card from the session | High |
| 12 | Itinerary | `POST /api/itinerary` returns `ItineraryStop[]` (time, title, category) | No itinerary route. The backend never writes `itineraries` or `itinerary_items`; the cart is the plan's output | Unclear whether a timed day-plan is in MVP scope | **D** (timed itinerary) / A (show the cart) | Frontend shows the cart as the plan result; the itinerary card shows an empty state in live mode | Medium |
| 13 | Cart contents | `HotelOption` cards with names | `GET /cart` items have only `entity_type` and `entity_id` (opaque IDs), with **no display name**. The agent's own `CartLine` contract *does* have `title` | A readable line per cart group | B | Add a read-only `title` to each human cart item (hotel + room name, or airline + flight number) | Medium-high |
| 14 | Cart / confirmation response shape | — | Empty: `{"cart": null, "items": []}`. Present: flat `{cart_id, …}`. `confirmations/current` behaves the same way | Consistent shapes would be better, but tests depend on the current ones | A | The frontend handles both shapes; the backend is left alone | High |
| 15 | Spend-cap enforcement | Mock mode filters by budget; nothing is enforced | `cart/items` refuses with `SPEND_CAP_EXCEEDED` (cap applies to committed + cart *with 12% tax*), audited as `BUDGET_CHECK` then `ACTION_REFUSED` | The user sees that an option was refused and why | A | Frontend shows refusals from the audit trail | High |
| 16 | Human confirmation | `POST /api/holds {hotelId}`, a user-initiated hold | No human hold route. The agent requests a booking, which creates a *pending* confirmation. The human reads `confirmations/current` and approves `{snapshot_hash}` or declines `{note}`. The confirmation has an `expires_at` | The backend's gate is the requirement ("a human, never the agent, approves a hash-locked snapshot") | A | Frontend adds a confirmation panel (totals, cap, expiry, Approve/Decline) and stops using `/api/holds` in live mode | High |
| 17 | Mocked booking | "Preview only" message | Approve returns `{booking_id, booking_reference, total_amount}`; `GET /booking` also works | Show the booking reference | A | Frontend shows the booking result | High |
| 18 | Failure detection | One generic error string | `status=failed`, `last_error_code` (`over_budget, sold_out, hold_expired, confirmation_declined, booking_failed, replan_limit`), `BOOKING_REFUSED` / `BOOKING_FAILED` events, and approve refusals such as `PRICE_CHANGED`, `SOLD_OUT`, `CONFIRMATION_STALE` / `EXPIRED` | Show the specific failure | A | Frontend maps codes to messages | High |
| 19 | Re-planning | Nothing | `replan_count` in the session view, `REPLAN` events, `replan_limit` only in `/context` | The user sees re-plans and the limit | C | Backend: add `replan_limit` to the session view. Frontend: show re-plans | High |
| 20 | Clarification | Only `assistantMessage` | `status=awaiting_input`; the question is only in the audit event `CLARIFICATION_REQUESTED.input.question`. The user answers with `POST /messages` | Show the question; the user's answer resumes the run | A | Frontend reads the latest question from the audit trail | High |
| 21 | Agent's final message | Expects `assistantMessage` | `POST /internal/…/run-outcome {message}` is **discarded**, never stored, although the code comment says it is "for the frontend". The audit event vocabulary has no slot for it, and adding one needs a migration | Unclear how agent narration should be stored | **D** | Decide how to persist it (the migration and `ck_audit_type` are checksum-locked) | — |
| 22 | **Agent ↔ backend bridge** | — | The backend POSTs to `AGENT_SERVICE_URL/runs` and expects the agent to drive `/internal/agent/v1`. **The Developer 2 agent has neither**: it is an in-process function `run_agent()` that reads SQLite directly (the architecture says "no DB access"). Its event names differ (`REQUIREMENTS_EXTRACTED`, `PLAN_UPDATED`, `CLARIFICATION_REQUIRED`, `AGENT_FAILED` are not in the backend's `EVENT_TYPES`). It ignores the 12% tax, emits `poi` lines the backend won't accept into a cart, and uses per-night `CartLine`s instead of grouped offers | One working bridge | **D** (blocker) | This is exactly Developer 2's list of 7 "needs Developer 1 confirmation" items. Until it's resolved, **no real AI runs end to end** | High that it is missing |
| 23 | Agent dispatch config | — | `.env.backend` has no `AGENT_TOKEN_SECRET`, so `POST /messages` raises a `RuntimeError` (500). With `AGENT_SERVICE_URL` unset, dispatch does nothing and the session stays in `executing` forever | Messages accepted; a missing agent is visible | B (config) + A | Add `AGENT_TOKEN_SECRET` to the local env. The frontend reports when no agent responds within its polling window | High |
| 24 | Loading / status states | One `loading` flag; READY / WORKING | 7 session statuses; `POST /messages` while `executing` returns `INVALID_STATE` | The composer is disabled while executing; each status is labeled | A | Frontend maps the statuses | High |
| 25 | Money types | Decimal strings | Decimal strings (from minor units at the edge) | Strings on both sides (R3) | — | None | High |
| 26 | Language | `goalLanguage` (BCP-47) | `goal_language` stored and passed to the agent | Same | A | Rename the field when mapping | High |
| 27 | Timestamps | — | Session times are `+05:30` local (existing-table style); confirmation times are UTC `Z` | Both are valid ISO-8601 with an offset (R4) | A | Frontend parses both with `Date` | High |
| 28 | My trips | Empty list (demo data deliberately removed) | No route to list a user's trips, though `POST /sessions` accepts a `trip_id` that switches on the budget-based cap | Unclear: should sessions attach to existing trips? | **D** | Decide, then add `GET /api/v1/trips` if yes. Sessions use `trip_id: null` for now | — |
| 29 | Notifications | localStorage toggles | None | Out of MVP scope as far as the repo shows | **D** | None | — |
| 30 | Audit verification | Nothing | `GET /audit/verify` | Optional transparency feature | A | Frontend shows the verify result with the timeline | Medium |

### Found during implementation and E2E (added after the audit)

| # | Area | Frontend currently does | Backend currently does | Expected behavior | Correct side | Required change | Confidence |
|---|---|---|---|---|---|---|---|
| 31 | Concurrent requests | Loads the session, cart, audit, confirmation and booking in parallel | `get_conn` opens the SQLite connection on one worker thread, and FastAPI runs the endpoint on another. Under real uvicorn this raises `sqlite3.ProgrammingError`, so the request **500s**, and the missing CORS header on the 500 hides the cause from the browser. `TestClient` tests don't hit it | The backend serves a real browser's concurrent requests | B | The per-request connection now uses `check_same_thread=False` (it is still used by one request at a time); regression test added | High |
| 32 | Plan shape | — | `plan_steps_json` is `[]` before any plan and `{"version", "steps"}` afterwards, two shapes in one field | One shape for clients | B (human view only) | The human view exposes `plan_version` and `plan_steps` separately; the stored value is unchanged | High |

## Status after implementation

- **Resolved:** 1–7, 11, 13–20, 23–27, 30, 31, 32, and the "show the cart" part of 12. **Also now resolved: #22** -- the real Developer 2 agent (`ai/travel_agent`) is wired live to the backend over HTTP via `ai/backend_client.py` (no more scripted stand-in; see `tests/ai/test_agent_integration.py` and `docs/AGENT_INTEGRATION_PROPOSAL.md`'s superseded-notice for what changed).
- **Still open (D):** 8, 9, 10, 12 (timed itinerary), 21, 28, 29. Live mode shows an honest "not available yet" message for direct search.
- **Backend tests:** 168 passing (120 from this audit's implementation + 45 from Developer 2's agent unit tests + 3 new: 2 advisory-budget-check tests, 1 real-agent-through-real-backend integration test).
- **Browser E2E (headless Chrome, 17/17, run twice):** a real frontend in live mode, talking to the real backend (uvicorn) on an isolated working copy of the DB. It covers: unauthenticated guard, login mismatch and success, budget validation, clarification, plan, tool call and results, cap refusal including tax, re-plan, titled cart with tax, enforced-cap budget card, the confirmation gate with expiry, approval leading to a mock booking, audit verification, and a decline leaving nothing booked. The DB afterwards has 1 booking (₹7,413.22 + ₹889.59 tax = ₹8,302.81, 4 items, 1 payment) and 1 declined confirmation. The original DB's SHA-256 is unchanged.
- **E2E caveat (historical):** at the time this audit ran, the agent side of the browser E2E was a scripted stand-in, because #22 was still open. #22 is now resolved (see above); a fresh browser E2E run with the real agent driving it has not yet been re-recorded in this document.

## Changes that will be made (A, B, C only)

**Backend (additive; no schema, migration or CSV changes; no validation removed)**
- #4, #5: validate the `CreateSessionRequest` money and currency format (422), and check the currency exists (400 `MALFORMED_ITEM`).
- #6, #11, #19: the human session view gains `plan, effective_cap, cap_source, committed, cart_total, remaining, replan_limit`.
- #13: human cart items gain a read-only `title`.
- #23: local `.env.backend` gets `AGENT_TOKEN_SECRET`.

**Frontend (live mode only; mock mode is untouched)**
- #2, #3, #20, #24: session-based chat (create, message, poll), with constraint mapping, clarification questions and status labels.
- #6, #7, #15, #19, #30: plan and audit timeline (tool calls, budget checks, refusals, re-plans, verify).
- #11: budget card from the session view.
- #12 (A part), #13, #14: cart panel.
- #16, #17, #18: confirmation gate panel (approve/decline with snapshot hash and expiry), booking result, failure messages.
- #4: normalize and validate the budget before sending.

## Not changed: needs a decision (D)

- ~~**#22 (blocker):** the agent ↔ backend bridge~~ **resolved** -- see the note at the top of "Status after implementation."
- **#8, #9, #10:** whether users can search the catalog directly.
- **#12:** whether a timed itinerary is in scope.
- **#21:** where the agent's final message is stored.
- **#28:** whether sessions attach to existing trips.
- **#29:** notifications.
