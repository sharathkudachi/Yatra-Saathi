# Data model

**Source of truth:** the canonical shared data model for **APS-01 · Agentic AI Travel Concierge: Autonomous
Planning & Booking** (data model v1.1.0-rc2: 22 tables, 47,946 rows, shipped as `APS-01.db` / CSV /
`schema.sqlite.sql`). Every canonical table and column is used **unmodified**: nothing is renamed,
dropped or altered, and no column is added to a canonical table.

> The APS-01 data pack names its tables rather than numbering them D1–D9, so this document refers to
> each canonical table by its canonical name.

The original `APS-01.db` is never written to. The app only opens a **working copy** that is verified
against the original's SHA-256 and stamped (`PRAGMA application_id`). It can be rebuilt at any time:
`backend/scripts/make_working_copy.py`, or `demo_reset.py`. The safety tests are in
`tests/safety/test_original_protection.py`.

---

## 1. Canonical tables we use

| Canonical table | How the app uses it | Access | Where in code |
|---|---|---|---|
| `users` | Sign-in identity (ID + name + email), owner of sessions and trips | read · demo seed row | `backend/src/api/routes/human/auth.py`, `db/repositories/trips.py`, `scripts/seed_demo.py` |
| `trips` | Trip context (dates, party, destination); My Trips | read · demo seed row | `backend/src/db/repositories/trips.py` |
| `budgets` | Trip budget total, one input to the **hard spend cap** | read · demo seed row | `backend/src/services/budget_service.py` |
| `agent_sessions` | The agent session: `spend_cap`, status, `requires_confirmation`, replan count | read · column updates (status, committed spend, replan count, current step) | `backend/src/db/repositories/sessions.py` |
| `cities` · `airports` · `airlines` | Resolving city names; flight display; airport time zones | read | `backend/src/db/repositories/catalog.py` |
| `flights` · `flight_fares` | Flight search and offers | read | `catalog.py`, `services/search_service.py`, `services/offer_service.py` |
| `hotels` · `hotel_room_types` | Stay search, room occupancy checks | read | `catalog.py`, `offer_service.py` |
| `inventory_calendar` | Dated price and availability for every fare and room night; no-oversell | read · `held_units` changed when a hold is placed or released | `offer_service.py`, `db/repositories/holds.py` |
| `holds` | TTL reservation made at booking time | insert · status update | `services/booking_service.py` |
| `bookings` · `booking_items` · `payments` | The mock booking (idempotency key mandatory) | insert | `booking_service.py` |
| `currencies` | Supported currencies and minor-unit exponents | read | `core/fx.py`, `/api/v1/currencies` |
| `itineraries` · `itinerary_items` | My Trips history | read | `services/my_trips_service.py` |

Kept intact but not read directly: `countries` (reached through `cities`), `languages` (the app uses
the same BCP-47 tags, rule R6) and `eval_nl_search_set`.

**Writes to canonical tables are limited to** new rows in `holds`, `bookings`, `booking_items`,
`payments` during a mock booking; `held_units` on `inventory_calendar`; a few status/progress columns on
`agent_sessions`; and the demo seed rows in `users` / `trips` / `budgets`. No canonical row is ever
deleted.

---

## 2. What we added

### 2.1 New tables (7)

| Table | Migration | Why it exists |
|---|---|---|
| `agent_audit_events` | 0001 | Append-only, **hash-chained** audit trail: plan steps, tool calls, offers, budget checks, refusals, replans, confirmations, booking. Triggers forbid update/delete and enforce a gapless, linked chain. |
| `agent_carts` | 0001 | One active (`open`/`locked`) cart per session. Its currency must equal the session currency, and its status only moves forward. |
| `agent_cart_items` | 0001 | One row per inventory row (each hotel night / the flight fare), grouped by `item_group_id`, with the converted unit price. Items are immutable once added. |
| `agent_confirmations` | 0001 | The **human confirmation gate**: created only as `pending`, bound to a hash of the locked cart, approvable only by the owner, single use, with a TTL. |
| `agent_session_state` | 0001 | The agent's saved JSON state (versioned, checksummed, size-capped), so a session survives restarts. |
| `push_subscriptions` | 0004 | One row per device that allowed Web Push, with that device's notification preferences. |
| `notifications_sent` | 0004 | Every notification raised (plan ready, approval ready, booking confirmed, flight departing/landed). A unique `dedupe_key` guarantees each is sent once; the rows are also the in-app notification history. |

### 2.2 Changes to existing tables

| Change | Migration | Why |
|---|---|---|
| Index `ix_flights_route_departs` on `flights (origin_airport_id, dest_airport_id, departs_at)` | 0002 | Route + date flight search |
| Index `ix_flight_fares_flight` on `flight_fares (flight_id)` | 0002 | Fare lookup per flight |

No canonical column, constraint or row definition is changed.

### 2.3 Later adjustment to our own tables

| Change | Migration | Why |
|---|---|---|
| Drop trigger `trg_items_currency_match` (on our `agent_cart_items`) | 0003 | Trips are priced and capped in the session currency, and foreign-currency inventory (AED, THB, JPY …) is converted per unit at the demo rates in `core/fx.py`. The rule moved to the application: `offer_service` refuses any currency without a rate, and `pricing_service` re-prices with the same conversion. `trg_carts_currency_session` still ties the cart to the session currency. |

Full DDL: [`schema.sql`](schema.sql), the concatenation of `backend/src/db/migrations/0001`–`0004`.
Each migration is **SHA-256-locked** by `backend/src/db/migrations/runner.py` and refuses to run on
an unstamped database, including the original.

---

## 3. Boundary rules and where they are enforced

| Rule (APS-01) | Enforced in backend code | Also in the DB | Test |
|---|---|---|---|
| `spend_cap` is a hard gate: `MIN(session cap, agent_sessions.spend_cap, budgets.total)` vs committed + cart incl. tax | `services/budget_service.py`, on every mutating call | cart total ≤ cap trigger | `tests/integration/test_agent_flow.py`, `tests/safety/test_schema_triggers.py`, `tests/ai/unit/test_replanning.py` |
| `requires_confirmation` cannot be bypassed | `services/confirmation_service.py` (hash-locked snapshot, human token only, TTL, single use) | `agent_confirmations` triggers | `tests/e2e/test_http_flow.py` (`test_rogue_agent_cannot_approve_confirmation`), `test_agent_flow.py` |
| Capacity / no oversell | `offer_service.py` (free units, closed-to-arrival, min stay, room occupancy) | canonical `inventory_calendar` CHECK | `test_schema_triggers.py`, `tests/e2e/test_search.py` |
| Currency is ISO-4217 and convertible | `schemas/human.py`, `core/fx.py`, `offer_service.py` | `trg_carts_currency_session` | `tests/integration/test_currency_conversion.py` |
| Money is exact (never float) | `core/money.py` | integer minor units in new tables | `tests/unit/test_money.py` |
| Tax is computed server-side (12%) | `services/pricing_service.py` (`TAX_RATE_BP`) | — | `test_money.py`, `test_agent_flow.py` |
| Trip dates: `YYYY-MM-DD`, not in the past, end after start (1–30 nights); flights compared by exact time | `core/dates.py`, `schemas/human.py`, search & session routes, `offer_service.py` | — | `tests/unit/test_dates.py`, `test_search.py`, `test_http_flow.py` |
| Original data never modified | `db/working_copy_guard.py` (stamped copy, `mode=rw`) | — | `tests/safety/test_original_protection.py` |

---

## 4. Conventions

* Canonical tables keep their formats: money as 2-decimal text (for example `'13907.20'`), timestamps in
  `+05:30` local time.
* New tables use integer minor units (paise) for money and UTC `YYYY-MM-DDTHH:MM:SS.mmmZ` timestamps
  (`core/money.py`, `core/clock.py`).
* IDs are opaque and never parsed; languages are BCP-47 tags.

## 5. Seed data

The demo values live in [`seed/demo_seed.json`](seed/demo_seed.json). `backend/scripts/seed_demo.py`
loads them and inserts the rows through the live schema and its triggers. See [`seed/README.md`](seed/README.md). `python -m scripts.demo_reset` (from `backend/`)
rebuilds the working copy, applies migrations 0001–0004 and seeds:

* user `usr_demo0001` ("[DEMO] Traveller", `demo.traveller@example.invalid`)
* trip `trp_demo0001` ("[DEMO] Ahmedabad → Jaipur", 2 adults)
* budget `bud_demo0001` (₹20,000)
