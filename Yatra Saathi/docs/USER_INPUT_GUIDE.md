# Yatra User Input Guide

Welcome to Yatra! This guide explains how to communicate with Yatra's AI travel concierge and direct search tools, what queries are supported by the current system, and how Yatra safely handles availability and budget constraints based on the authoritative backend and database.

---

## 1. What can I ask Yatra?

The chat planner is an end-to-end autonomous travel concierge that plans a complete round trip:
- Origin and destination cities
- Departure / check-in date
- Return / check-out date
- Number of travellers
- Total trip budget and currency

When you ask Yatra to plan a trip, it checks both flight directions (outbound and return) and verified hotel rooms through the authoritative backend. The backend is the sole authority for inventory, pricing, spend caps, carts, confirmations, holds, and bookings.

For individual components:
- Use the dedicated **Flights** search form for one-way flight searches.
- Use the dedicated **Stays** search form for direct hotel searches.

The database contains 60 active cities, dated flight schedules and fares, hotel room inventory across 30 cities, and support for 25 currencies.

---

## 2. How to plan a trip

In the chat composer, describe your trip in simple, natural language:

> **Standard round-trip format:**
> "Plan a trip from [origin] to [destination] for [number] adults from [start date] to [end date] under [total budget]."
> *Example:* `Plan a trip from Mumbai to Lucknow for 2 adults from 16 to 19 November 2026 under ₹45000.`

> **Short trip format with duration:**
> "Plan a [N]-night trip from [origin] to [destination] on [start date] for [number] people under [total budget]."
> *Example:* `Plan a 3-night trip from Mumbai to Lucknow on 16 November 2026 for 3 adults under ₹90000.`

*Notes on durations:*
- A "3-night trip" starting on 16 November calculates the return date as 19 November (3 calendar days later).
- Always include the year (e.g., `2026`) so your travel dates are unambiguous.

---

## 3. How to search flights

Use the separate **Flights** search form on the page:
- Provide origin city, destination city, departure date, passenger count, and cabin class (e.g., Economy).
- Direct flight search is designed for one-way queries.
- If no flights are available on your selected date, the system lists nearby alternate dates with available inventory.

*Important:* The direct Flights search form does not filter by budget or accept a maximum price cap. For budget-constrained round-trip flights, use the AI Chat Planner.

---

## 4. How to search hotels

Use the **Stays** search form on the page:
- Provide destination city, check-in date, check-out date, number of travellers, and currency.
- Optionally enter a budget cap: this cap applies to the **entire stay**, not per night.

The backend verifies room capacity, required room units, minimum-stay rules, arrival restrictions, and total price. If no rooms are returned, no inventory in the database satisfied all criteria simultaneously.

---

## 5. How to specify a budget

The chat parser supports standard INR currency notations as well as major international currencies:
- Symbol prefix: `₹45000`, `₹45,000`, `$1200`, `€900`
- Keyword with amount: `under ₹50000`, `budget of ₹80000`, `max ₹35000`, `within ₹65000`, `up to ₹75000`
- Currency code suffix: `45000 INR`, `100000 INR`
- Bare numbers: if no currency symbol is provided, the budget defaults to the trip currency (e.g., INR).

All budgets are normalized to two decimal places (e.g., `50000.00`). The backend strictly enforces this total cap; the AI agent can only propose options at or below this budget.

---

## 6. How to specify travellers

Specify the party size in natural phrases:
- Numbers with qualifiers: `2 adults`, `5 people`, `3 travellers`, `4 guests`, `2 pax`
- Word numerals: `two adults`, `three people`, `five travellers`
- Solos and couples: `solo`, `just me`, `a couple`

The chat trip planner supports groups from 1 to 9 travellers. Direct flight search supports 1 to 9 passengers; direct hotel search supports 1 to 20 guests (subject to room capacity).

---

## 7. How to specify dates

The date parser supports flexible natural language formats:
- `12 to 16 October 2026`
- `12th to 16th October 2026`
- `12 Oct to 16 Oct 2026`
- `12 October 2026 to 16 October 2026`
- `from 16/11/2026 to 19/11/2026` (day/month/year numeric format)
- `2026-10-12 to 2026-10-16` (ISO format)

*Rules:*
- Dates must be today or in the future.
- Return / check-out date must be strictly after departure / check-in date.
- Always specify the year (`2026`) for accuracy.

---

## 8. How to combine requirements

You can state all requirements in a single complete request:
> "Plan a trip from Mumbai to Lucknow for 2 adults from 16 to 19 November 2026 under ₹45000."

Yatra synchronizes and locks your requirements (origin, destination, dates, party size, budget cap) into the trip brief and session state before dispatching the agent. The agent then searches database inventory to fulfill all constraints concurrently.

---

## 9. What happens when inventory is unavailable

If inventory is unavailable for any part of your request:
1. **No Hallucinations:** Yatra will NEVER invent flights, rooms, or seat availability.
2. **No Silent Mutations:** Yatra will NEVER silently alter your travel dates, decrease the traveller count, or increase your budget.
3. **Transparent Explanations & Database Alternatives:** The agent clearly explains which leg has no availability and offers database-backed alternative dates.
   - *Example:* For Mumbai → Kolkata (12–16 Oct 2026, 5 adults), outbound seats exist, but no return flight on 16 Oct has 5 seats. The agent explains this limitation and suggests real inventory dates (e.g., 4 Nov or 19 Nov) with interactive date chips.
4. **User Control:** You retain full control to select an alternative date or modify your parameters.

---

## 10. What Yatra cannot guarantee

- **Inventory Longevity:** Database inventory represents live availability at search time; availability is only locked when a cart hold or booking confirmation occurs.
- **Arbitrary Routes / Dates:** Only routes, flight schedules, and hotel partner properties existing in the database can be booked.
- **Automatic Bookings:** The AI planner never finalizes a payment or booking without explicit human approval via the confirmation gate.
- **Exceeding Budget:** The agent cannot authorize or complete bookings that exceed the customer's spend cap.

---

## 11. Validated Example Prompts & Exactly 10 Beginner UI Suggestions

The following 10 prompts are permanently verified against the working database and exposed as clickable suggestion chips in the chat interface. Each prompt is beginner-friendly and tests real backend capabilities.

| # | Suggestion Chip Label | Full Prompt | Category | Validated Result | Inventory Status |
|---|---|---|---|---|---|
| 1 | `Mumbai → Lucknow · 2 adults` | `Plan a trip from Mumbai to Lucknow for 2 adults from 16 to 19 November 2026 under ₹45000.` | Complete trip planning | **PASS** (3 package options returned within cap) | Available |
| 2 | `Ahmedabad → Bengaluru` | `Plan a trip from Ahmedabad to Bengaluru for 2 adults from 14 October 2026 to 19 October 2026 under ₹100000.` | Complete trip planning | **PASS** (3 package options returned within cap) | Available |
| 3 | `Ahmedabad → Hyderabad` | `Plan a trip from Ahmedabad to Hyderabad for 2 adults from 15 to 18 October 2026 under ₹55000.` | Trip planning with budget | **PASS** (3 package options returned within cap) | Available |
| 4 | `Ahmedabad → Lucknow · 5 nights` | `Plan a trip from Ahmedabad to Lucknow for 2 adults from 7 to 12 November 2026 under ₹80000.` | Date-specific planning (5 nights) | **PASS** (3 package options returned within cap) | Available |
| 5 | `Bengaluru → Jaipur` | `Plan a trip from Bengaluru to Jaipur for 2 adults from 4 to 9 November 2026 under ₹75000.` | Complete trip planning | **PASS** (3 package options returned within cap) | Available |
| 6 | `Chennai → Pune` | `Plan a trip from Chennai to Pune for 2 adults from 3 Nov to 7 Nov 2026 under ₹65000.` | Date-specific planning (short month format) | **PASS** (1 package option returned within cap) | Available |
| 7 | `Ahmedabad → New Delhi` | `Plan a trip from Ahmedabad to New Delhi for 2 adults from 3 to 5 November 2026 under ₹45000.` | Weekend getaway planning (2 nights) | **PASS** (3 package options returned within cap) | Available |
| 8 | `Lucknow · 2 nights` | `Plan a trip from Ahmedabad to Lucknow for 2 adults from 10 to 12 November 2026 under ₹35000.` | Trip planning with tight budget | **PASS** (3 package options returned within cap) | Available |
| 9 | `Mumbai → Kolkata · 5 adults` | `Plan a trip from Mumbai to Kolkata for 5 adults from 12 to 16 October 2026 under ₹50000.` | Large group planning / regression case | **EXPECTED CLARIFICATION** (Outbound available; return on 16 Oct lacks 5 seats; offers alternate dates) | Clarification required |
| 10 | `Mumbai → Lucknow · 3 adults` | `Plan a 3-night trip from Mumbai to Lucknow on 16 November 2026 for 3 adults under ₹90000.` | Duration-based trip planning | **PASS** (3 package options returned within cap) | Available |

### Direct Flights & Direct Hotel Form Queries (Non-Chat Surfaces)

| # | Surface | Sample Query | Validated Outcome | Notes |
|---|---|---|---|---|
| 11 | Flights Form | Origin: Mumbai, Destination: Lucknow, Date: 16 Nov 2026, Passengers: 2 | **PASS** (1 fare returned) | Direct Flights form has no budget filter |
| 12 | Flights Form | Origin: Lucknow, Destination: Mumbai, Date: 19 Nov 2026, Passengers: 2 | **PASS** (2 fares returned) | Economy cabin |
| 13 | Flights Form | Origin: Ahmedabad, Destination: Bengaluru, Date: 14 Oct 2026, Passengers: 2 | **PASS** (2 fares returned) | Real schedule from database |
| 14 | Flights Form | Origin: Mumbai, Destination: Kolkata, Date: 12 Oct 2026, Passengers: 5 | **PASS** (2 fares returned with 5+ seats) | Outbound flight available |
| 15 | Flights Form | Origin: Kolkata, Destination: Mumbai, Date: 16 Oct 2026, Passengers: 5 | **EXPECTED NO RESULTS** (Zero fares for 5 passengers; suggested 4 Nov & 19 Nov) | Preserves date constraints |
| 16 | Stays Form | City: Lucknow, 16–19 Nov 2026, 2 adults, Budget: ₹40000 total | **PASS** (8 room options returned) | Budget is for entire stay |
| 17 | Stays Form | City: Bengaluru, 14–19 Oct 2026, 2 adults, Budget: ₹100000 total | **PASS** (1 room option returned) | 5-night stay |
| 18 | Stays Form | City: Hyderabad, 15–18 Oct 2026, 2 adults, Budget: ₹55000 total | **PASS** (1 room option returned) | Verified inventory |
| 19 | Stays Form | City: Jaipur, 4–9 Nov 2026, 2 adults, Budget: ₹75000 total | **PASS** (5 room options returned) | Multiple hotels |
| 20 | Stays Form | City: Kolkata, 12–16 Oct 2026, 5 adults, Budget: ₹100000 total | **EXPECTED NO RESULTS** (No rooms with capacity for 5 guests) | Never hallucinates rooms |

---
*Machine-readable catalog: [supported_input_examples.json](supported_input_examples.json)*
