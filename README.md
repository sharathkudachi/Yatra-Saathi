
# kv-hack2026-tech4ce
KogniVera Hackathon 2026 — Tech4ce
=======
# Yatra frontend

A React + TypeScript + Vite + Tailwind prototype for the APS-01 travel concierge. It is the frontend portion of the team repository; backend, AI, shared data-model documentation and the team-level README belong at the repository root and are not included here.

## Run locally

Requires Node.js 20 or newer and npm.

```bash
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite. To make a production build, run `npm run build`.
If you launch commands from the repository root, use `cd frontend` first.

## Structure

```text
src/
  app/App.tsx                 Main responsive trip-planning experience
  mocks/hotelCatalog.json     Static catalog extracted from shared SQLite data
  mocks/demoData.ts           One clearly labelled sample itinerary/budget
  services/apiClient.ts       Shared fetch wrapper
  services/conciergeService.ts Mock/real API switch, chat preview and search
  i18n/                       UI translations and BCP-47 language context
  mocks/languages.json        Language metadata copied from the shared database
  styles/                      Global and interaction styling
  types/travel.ts             UI-facing request/response types
  utils/format.ts             Exact decimal-string money helpers
```

## Demo mode and backend handoff

The app defaults to demo mode. Copy `frontend/.env.example` to `frontend/.env.local`; leave `VITE_USE_MOCK_API=true` until the backend team supplies its API contract. The static catalogue fixture is extracted from the shared synthetic SQLite file and includes 60 cities, 300 hotels, 1,200 room types and 10,530 dated inventory rows. It can preview more than Jaipur, but it is not live inventory and does not create holds or bookings.

Before switching to real mode, agree on these items with the backend team:

- API base URL and CORS origins for the frontend dev server.
- Exact request/response JSON for hotel search, itinerary, budget and hold creation.
- Which backend endpoint requires the traveller's final explicit confirmation.
- The field names and identifiers returned for every selectable result.
- Error responses for over-budget, sold-out and expired-hold cases.
- Currency strings must remain exact decimal strings, not JSON floating-point numbers.

See [API_HANDOFF.md](./API_HANDOFF.md) for a draft of the frontend data needs. Its route examples are proposals, not a backend contract.

The chat panel has a deterministic preview parser so you can try natural-language requests while the AI endpoint is being built. It is labelled as a preview and is not the hackathon's live AI agent. In real mode, the UI calls the proposed `POST /api/agent/turn` route; align its response type with the backend team before switching `VITE_USE_MOCK_API=false`.

The language picker is populated from the shared database's language records. The selected BCP-47 tag is sent as `goalLanguage` with agent turns; the backend should use it for user-facing AI text. UI copy coverage is still being completed language by language, so some strings may currently fall back to English.

The sign-in screen is present as a UI preview. Its form intentionally does not transmit, store or authenticate credentials until the backend team supplies a secure auth flow.

The milestone 1 backend ZIP is a protected SQLite schema/migration foundation; it does not yet include an HTTP API server. The example `/api/...` paths in `conciergeService.ts` are frontend proposals, not routes taken from the ZIP. Use [API_HANDOFF.md](./API_HANDOFF.md) to agree on the DTO and session/cart/confirmation flow with the backend teammate, then adapt this service to the actual API before setting `VITE_USE_MOCK_API=false`.

## Current limitations

- Illustrative hotel and banner photography loads from Unsplash and therefore needs an internet connection; the photos do not depict the listed properties.
- Translation coverage varies by language; untranslated interface strings currently fall back to English.
- The XR card opens a browser-based scenic photo preview with zoom controls. It is not a headset VR/AR experience; the official device requirement and 360° media need confirmation from the APS-01 application page before implementing true XR.
- Natural-language preview matching is deterministic; no model is called until the agent API is connected.
- The sign-in modal is a UI only; it never submits or stores credentials.
- Only one seeded itinerary/budget is shown in preview mode. Other destinations can search the catalog, but their itinerary and budget summaries await the backend agent.
>>>>>>> a44fc3cff1321e6bb86a2ddb71d6496b15d3bd24
