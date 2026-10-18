# Frontend/backend integration handoff

This is a **proposed frontend contract**, not an API contract already implemented by the backend team. Please compare it with the backend team's current route/schema plan before either side treats it as final.

## What the milestone 1 archive contains

`kv-hack2026-tech4ce-milestone1.zip` contains a Python/SQLite database foundation, approved migrations, and database protection scripts. Its README calls this milestone 1. It does **not** contain an HTTP server, API routes, OpenAPI spec, auth flow, or request/response schemas. The backend must open only its stamped `APS_DB_PATH` working copy; the browser must never connect to the SQLite file directly.

The migration adds these agent-state tables: `agent_audit_events`, `agent_carts`, `agent_cart_items`, `agent_confirmations`, and `agent_session_state`. The UI should call backend services over HTTP; the backend should read/write the database and map its rows into the UI DTOs below. Keep the original database and approved migration files unchanged.

## Frontend connection switch

The frontend already has a service boundary in `src/services/conciergeService.ts` and an HTTP wrapper in `src/services/apiClient.ts`.

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://localhost:8000
```

Keep `VITE_USE_MOCK_API=true` until the backend endpoints below (or the backend team's replacement contract) are running. Configure backend CORS for the Vite origin, normally `http://localhost:5173`. Login and account creation are currently UI previews and do not send credentials; the milestone 1 archive has no auth API.

## Proposed JSON conventions

- Request and response property names use the frontend's camelCase types (`startDate`, `inventoryIds`, `assistantMessage`). The backend may use snake_case internally.
- Dates use `YYYY-MM-DD`; timestamps use UTC ISO 8601.
- Money crossing the API is an exact decimal **string** with a currency code, such as `{ "amount": "12400.00", "currency": "INR" }`. The database stores minor units as integers (for example `unit_price_minor`, `total_minor`); convert at the backend boundary without floating-point arithmetic.
- IDs are opaque strings from the backend. Do not synthesize database IDs in the UI.
- The selected BCP-47 language tag is sent as `goalLanguage`. Localize generated, user-facing agent text on the backend; keep enum/status codes stable and let the frontend translate labels.
- Return user-safe errors with a stable `code` and localized `message`, for example `{ "code": "sold_out", "message": "…" }`.

## Operations currently called by the frontend

These routes are the frontend's proposed paths. Route paths and DTO names can be changed in one place (`conciergeService.ts`) after the backend team shares its actual contract.

### Search stays

```http
POST /api/search/hotels
```

Request body is the current `TripRequest`:

```json
{
  "destination": "Jaipur",
  "startDate": "2026-11-16",
  "endDate": "2026-11-20",
  "travellers": 2,
  "budget": "25000.00",
  "currency": "INR",
  "preferences": "A quiet heritage stay"
}
```

Return `HotelOption[]`. Each selectable option needs its `hotelId`, `roomTypeId`, and one `inventoryIds` entry per night, in stay-date order. Include display fields (`name`, `city`, `description`, `roomName`, `imageUrl`, `tags`), exact total `price`, `currency`, `nights`, `availableUnits`, and `maxOccupancy`. For properties where the shared data has no real room/area/menu photos or menu, omit those optional details rather than inventing them.

### Search flights

The hackathon data model also includes `airlines`, `airports`, `flights`, `flight_fares`, and flight rows in `inventory_calendar`. The frontend now proposes this route for the flight search panel:

```http
POST /api/search/flights
```

Request body:

```json
{
  "originCity": "Bengaluru",
  "destinationCity": "Lucknow",
  "departureDate": "2026-11-16",
  "passengers": 2,
  "cabinClass": "economy",
  "currency": "INR",
  "goalLanguage": "en-IN"
}
```

Return `FlightOption[]`. Each result should map one `flight_fares` row and its matching flight inventory row, with `flightId`, `fareId`, `inventoryId`, airline and flight number, origin/destination airport names and IATA codes, departure/arrival timestamps, duration, stops, cabin/fare class, total price and currency, baggage allowance, seats available, refund/change rules, and carbon estimate. Resolve origin/destination city names to airports in the backend; do not expose database IDs as user-entered values. The frontend preview mode does not fabricate live fares and will show a connection note until this API is available.

### Agent turn

```http
POST /api/agent/turn
```

Request body:

```json
{
  "message": "Plan a quiet Jaipur trip for two",
  "goalLanguage": "hi",
  "tripRequest": {
    "destination": "Jaipur",
    "startDate": "2026-11-16",
    "endDate": "2026-11-20",
    "travellers": 2,
    "budget": "25000.00",
    "currency": "INR",
    "preferences": ""
  }
}
```

Return `AgentTurnResponse`: `assistantMessage`, updated `tripRequest`, `toolSteps`, `hotels`, `budget`, and `itinerary`. Tool steps must reflect actual backend actions/results. Since the schema persists agent sessions and state, the team should also decide how the response returns a `sessionId` and how later turns resume it; the current frontend type can be extended once agreed.

### Budget and itinerary

The current UI requests these after a form search. They must receive the trip context; they currently use `POST` with `{ "tripRequest": <TripRequest> }`:

```http
POST /api/budget
POST /api/itinerary
```

Budget response: `{ "currency": "INR", "total": "25000.00", "committed": "0.00", "planned": "12400.00" }` or `null` when there is no plan. Itinerary response is `ItineraryStop[]` with `id`, `time`, `title`, `detail`, and `category` (`stay`, `food`, `culture`, or `nature`). If the backend uses session IDs instead of a trip request, align both sides before implementation.

### Hold / cart / confirmation

The current frontend preview has a single hold action, but the milestone 1 schema models carts, cart items, and explicit confirmations. A request containing only `hotelId` is insufficient for the schema: a cart item must be tied to a session, inventory row, date, source tool-result event, and offer index. The backend team should define the cart/session lifecycle and an explicit confirmation operation before the UI is switched to live booking.

At minimum, the UI/backend flow needs the chosen `hotelId`, `roomTypeId`, every night's `inventoryId` and `forDate`, requested units, currency, and an idempotency key. The backend must re-check live price/availability and return the authoritative state and expiry. The UI must show the separate confirmation step only after receiving the backend's confirmation request. Do not mark anything booked because a hold succeeded.

## Existing UI DTO source

The canonical frontend types are in `src/types/travel.ts`: `TripRequest`, `HotelOption`, `AgentTurnResponse`, `BudgetSummary`, `ItineraryStop`, and `HoldResult`. These are UI-facing types, not database row types. Keep DB column names and internal state JSON behind the backend API.

## Still needed from the backend teammate

1. Actual API routes and request/response examples (or an OpenAPI file).
2. How an agent session/cart is created, returned, and resumed.
3. The cart-item and explicit-confirmation endpoints and their statuses.
4. Auth/session expectations and login/account-creation routes, if authentication is in scope.
5. Local run command, API base URL, and CORS origin.
6. Error codes/messages and which endpoint owns itinerary/budget data.
7. If notification delivery is in scope, a user-scoped preferences endpoint and delivery channels/events. The frontend currently saves notification toggles in browser local storage only; it does not send or deliver notifications.

Once those are available, update only the frontend service adapter and DTO mappings, then turn off mock mode. The UI and backend can keep progressing independently while this contract is being agreed.
