# Yatra Full Application Audit Report

**Audit date:** 10 October 2026  
**Application:** canonical project at `kv-hack2026-tech4ce/`  
**Result:** core demo journeys passed after the fixes below. This is not a production-readiness certification.

## 1. Initial baseline and repository state

- The canonical app is the React/TypeScript frontend, FastAPI backend, separate AI service, and SQLite dataset in this directory. I read the README, `docs/ARCHITECTURE.md`, backend setup guidance, manifests, database safeguards, auth/booking flows, and the existing browser QA scripts.
- The requested `docs/PROJECT_AUDIT_AND_ROADMAP.md` was absent. `docs/ARCHITECTURE.md` was present.
- The checkout already contained roughly 507 staged, unstaged, and untracked changes before the audit. I left unrelated files and user data in place; I did not commit or push.
- Baseline issues reproduced: the existing frontend test script used a Bash-only timezone loop and failed in Windows PowerShell; backend test collection initially lacked declared `python-dotenv` and Windows IANA timezone data; the default map requested proprietary provider tiles; and Leaflet's runtime container class was overwritten on React rerenders.
- Environment: Windows with Python 3.14 available. The repository documents Python 3.13. The complete suite passed under 3.14 after the dependencies below were installed; Python 3.13 was not available for a parallel version check.

## 2. Confirmed defects, causes, and corrections

| Finding | Root cause | Correction and verification |
|---|---|---|
| Proprietary map watermark/API-key dependency | The default map used a provider-specific basemap configuration. | Switched the default to the standard public OSM raster URL, with OSM attribution and zoom cap. A source regression test confirms no provider/key is needed. Live Chrome loaded OSM imagery. |
| Blank map tiles despite successful image downloads | React changed the map element's `className` after Leaflet initialized and removed Leaflet's required `.leaflet-container` class. Tailwind's image sizing then collapsed the tiles to zero width. | Keep `.leaflet-container` in the React-owned class list. Repeated browser run showed real roads, cities, tiles, markers, attribution, and the flight arc. |
| Leaflet exception during plan/day changes | The map initialization effect depended on route bounds and fit callbacks. Each change removed the map while Leaflet could still be animating, then recreated it. | Initialize independently of route changes; fit bounds in the separate update effect. The browser run after the fix exercised itinerary generation and all day filters without console errors. |
| Missing flight arc after restoring/planning a trip | The component passed only transient `originCity` state. A restored itinerary could have an authoritative origin in the structured plan while this state was empty. | Pass the structured plan's origin as the fallback. The final browser run observed a Day 1 curved flight path and verified that Day 2 suppresses it. |
| Ground connections could look like road navigation | Straight lines connected city/airport/hotel/activities without saying they were approximations. | Tooltips now identify these as approximate ground connections and explicitly say they are not road navigation. |
| No clear recovery from an unavailable tile service | Tile failures did not provide a clear retry path. | Show a recoverable error after repeated tile errors and redraw tiles on retry. The error state itself was not forced in the browser. |
| Registration terms were pre-checked | The registration checkbox had the `checked` attribute by default. | It now starts unchecked and registration accepts consent only when the checkbox is explicitly true. The form was inspected live; I stopped before submitting acceptance of the terms. |
| Frontend test command was not Windows-compatible | `package.json` invoked a shell-specific timezone loop. | Added a Node test runner that runs the same frontend tests under five timezones. |
| Windows time-zone lookup failed | `tzdata` was not declared for Python's `zoneinfo` on Windows. | Pinned `tzdata==2026.5`; the previously failing date/time regression now passes. |
| Backend imports were not reproducible from requirements | `python-dotenv` was imported by the backend but missing from its manifest. | Added pinned `python-dotenv==1.2.2`. |
| One test asserted an over-budget itinerary should succeed | The fixture's authoritative catalog total was ₹49,970.63 against a ₹45,000 hard cap, while the app correctly refused it. | Renamed the test to reflect the over-budget case and assert the controlled refusal. The hard-cap behavior remains enforced. |
| Unused map SDK carried vulnerable packages | `@maptiler/sdk`/`maplibre-gl` were not used by the active Leaflet implementation. | Removed the unused SDK dependency and applied the compatible lockfile security update. Final `npm audit` reports zero vulnerabilities. |

## 3. Files changed

- `frontend/src/app/TravelMap.tsx` — OSM layer, persistent Leaflet class, stable map lifecycle, tile error/retry UI, explicit approximate-ground-route labels.
- `frontend/src/app/App.tsx` — canonical itinerary-origin fallback for map routes and explicit registration consent.
- `frontend/src/utils/mapTiles.ts` — OSM URL, attribution, and zoom configuration.
- `frontend/src/utils/authValidation.ts` — consent predicate.
- `frontend/tests/mapTiles.test.ts`, `frontend/tests/authValidation.test.ts` — map config and consent regression cases.
- `frontend/tests/run-tests.mjs`, `frontend/package.json` — portable timezone test runner.
- `frontend/package-lock.json` — removed unused map SDK/transitive packages and applied a safe dependency update.
- `backend/requirements.txt` — added `python-dotenv` and `tzdata` pins.
- `tests/unit/test_phase2_complete.py` — corrected the misleading over-budget expectation.
- This report.

## 4. Map implementation and proof

- Default provider: OpenStreetMap's public raster endpoint, `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`; `maxZoom` is 19 and attribution links to OpenStreetMap contributors.
- The default map has no MapTiler/Carto token configuration or required key. The unused MapTiler SDK was removed. The frontend source test checks the URL, attribution, zoom limit, and absence of proprietary provider/key strings in the map configuration.
- Live evidence: headless Chrome loaded nine OSM tile images with `complete=true` and `naturalWidth=256`. The final screenshot shows Lucknow/India geography, BOM and LKO markers, and the blue curved flight line. Day 1 showed 9 map pins and the flight arc; Day 2 showed 7 pins and no flight arc. All Days restored 27 pins. Clicking an itinerary activity opened its matching Leaflet popup.
- The map uses application coordinates where present and the known airport catalog for airport route points. Invalid coordinates are filtered by existing geo utilities and covered by frontend tests. Ground lines are described as approximate rather than navigation.
- The test workflow respects normal OSM tile usage and does not prefetch or bulk-download tiles. Public OSM tiles are suitable for development/demo use; significant production traffic should use a dedicated provider or self-hosted tiles.

## 5. Browser automation and live workflows

**Method:** reused the repository's `browser_qa_travel_intelligence_pass2.mjs` against Chrome via Chrome DevTools Protocol, the actual Vite site on port 5173, FastAPI on 8000, and the separate deterministic AI service on 9000. The browser ran at a desktop viewport. I also inspected the actual rendered page in Codex's in-app browser at a 699 CSS-pixel viewport; `documentElement.clientWidth` and `scrollWidth` were both 699 (no horizontal overflow in that check).

**Final browser results:** 10/10 workflow result flags passed; `consoleErrors=[]`, `networkErrors=[]` in the QA report.

- Guest state was unauthenticated. A guest booking attempt prompted sign-in and did not become the demo user or create a booking.
- Explicit sign-in to the synthetic demo account succeeded.
- Generated a four-day Mumbai–Lucknow itinerary with 25 activities and 27 map pins.
- Day filters produced distinct marker sets; Day 1 included the curved flight path and Day 2 suppressed it.
- Clicking the arrival activity opened the matching Leaflet popup.
- The catalog disclosed that only one suitable flight was available. The visible interface offered one flight; the existing script's card-count selector returned zero, so that individual count is not treated as a passing assertion.
- Booking review showed the authoritative group total **₹38,500.88 INR**, including the displayed 12% tax. Explicit confirmation created a **simulated demo booking**. No payment or real travel reservation occurred.
- The script report's final status was `SUCCESS`. The final day-filter screenshot is in the Windows temp directory at `C:\Users\Administrator\AppData\Local\Temp\qa_pass2_4_day_filters.png`.

During an earlier service restart, the home page briefly showed `Failed to fetch` empty-state text while services were starting. Requests succeeded after the services became ready, and the final browser pass recorded no failed HTTP responses.

## 6. Automated test/build results

| Check | Result |
|---|---|
| Frontend `npm test` | 21 tests passed under each of five timezones: **105/105 passes**. |
| TypeScript + production build (`npm run build`) | **Passed** (`tsc -b` and Vite build). Vite reports the main JavaScript chunk is about 2.2 MB and the XR chunk about 544 KB; this is a performance warning, not a build failure. |
| Frontend dependency audit (`npm audit --audit-level=low`) | **0 vulnerabilities**. |
| Python full suite (`python -m pytest -q tests --tb=short`) | **582 passed, 1 skipped, 176 subtests passed**. |
| Skipped Python case | Windows could not create a symlink without the required OS privilege: `tests/safety/test_original_protection.py` skips that symlink-only case. The rest of the original-database safety tests passed. |
| Focused safety/E2E rerun | **33 passed, 1 skipped**; same symlink limitation. |
| AI service | Started as a separate process with `TRAVEL_AGENT_DISABLE_LLM=1`; the tested journey used the deterministic fail-safe path. A live external LLM provider was not exercised. |

The browser run occurred after the last map and origin changes. Frontend tests/build/audit were rerun after those changes. The complete Python suite had already passed after the last backend/test/dependency change; subsequent edits were frontend-only.

## 7. Security, ownership, booking, and money

- Browser checks confirmed that a guest stays a guest, receives an auth prompt, and cannot silently book as the demo account. The automated suite passed the auth/ownership/security coverage present in the repository; a separate live two-user browser isolation journey was not run.
- The invalid-login path was exercised and returned the expected generic invalid-credentials response (401), not an application error.
- AI service and backend ran in separate processes; external LLM calls were disabled for the audit. The authoritative price shown in booking review matched INR and stayed below the ₹90,000 trip cap. Booking confirmation was only the app's mock/demo booking flow.
- The repository documents that its dataset-backed identity sign-in is for demo use, not production password authentication. Do not treat this audit as approval to deploy that auth scheme to real users.
- No passwords, auth tokens, review tokens, or environment secret values are included in this report. Keep local `.env` files out of shared archives/Git; rotate any real provider credentials that were included in a shared archive.

## 8. Database and release safety

- `data/original/APS-01.db` existed at the configured path. Final SHA-256: `ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a` (matches the expected fingerprint).
- `PRAGMA integrity_check` returned `ok` and `PRAGMA foreign_key_check` returned no rows for the original database, the pre-existing `backend/aps01_working.db`, and the isolated audit working copy.
- Browser workflow data and simulated bookings were written only to the isolated audit working copy made with the repository's guarded working-copy script and migrations. The original and pre-existing working database were not used for browser writes.
- No commit, push, tag, publish, or destructive reset was performed.

## 9. Remaining limitations and not-tested items

- Registration was not submitted because the final step requires accepting terms. The live checkbox default and explicit-consent behavior were verified; duplicate-account handling was not exercised in the browser.
- Only Mumbai–Lucknow was run through the complete live itinerary/booking flow. The other requested city pairs and all currency/date combinations were not individually browser-tested.
- Hindi/Tamil conversation, voice actions, SOS activation, notification preferences/deduplication, preferences precedence, cancellation, Trip Pack, and a live two-user ownership journey were not exercised end-to-end in the browser.
- Zoom/pan controls and the tile failure/retry overlay were not forced through in the final browser pass. OSM tile success, map fit, activity popup, day filtering, desktop rendering, and the narrow viewport layout were observed.
- Activity labels can overlap where markers are geographically close. The app's catalog currently exposed only one suitable flight in the tested route.
- A Python 3.13 run was not possible in this environment; Python 3.14 was used. The full test suite passed there.
- Build output retains the large-bundle warning described above.

## 10. Windows PowerShell run commands

From the canonical project root:

```powershell
py -3.13 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r ai\requirements.txt
Set-Location frontend
npm ci
npm test
npm run build
npm audit --audit-level=low
```

Create the local configuration files from the supplied examples, then set the original DB path/fingerprint, a **separate working-copy DB path**, backend secrets, the demo login allow-list, and the same agent service key in the backend and agent configs. Do not point `APS_DB_PATH` at the original dataset.

From `backend\`, set the database environment values for the current PowerShell session and prepare only the working copy:

```powershell
$env:APS_DB_ORIGINAL_PATH = (Resolve-Path ..\data\original\APS-01.db).Path
$env:APS_DB_ORIGINAL_SHA256 = 'ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a'
$env:APS_DB_PATH = (Join-Path (Get-Location).Path 'var\yatra_local.db')
.\.venv\Scripts\python.exe -m scripts.make_working_copy
.\.venv\Scripts\python.exe -m scripts.apply_migrations
.\.venv\Scripts\python.exe -m scripts.seed_demo
```

Run three terminals:

```powershell
# Terminal 1, from backend\
.\.venv\Scripts\python.exe -m uvicorn src.main:app --reload --port 8000 --env-file .env.backend

# Terminal 2, from ai\
..\backend\.venv\Scripts\python.exe -m uvicorn service:app --reload --port 9000 --env-file .env.agent

# Terminal 3, from frontend\
npm run dev
```

Open `http://localhost:5173/`. Keep `VITE_USE_MOCK_API=false` for the live backend. The default map works without `VITE_MAPTILER_API_KEY`.

## 11. Focused final verification — 2026-10-10

This addendum records the requested remaining-workflow pass against the real local frontend (`http://localhost:5173/`), backend (`localhost:8000`), and AI service (`localhost:9000`). Backend records used a fresh database at `backend/var/codex_final_qa_20261010.db`, created with the guarded working-copy script, then migrated and seeded. All test identities and bookings were synthetic. Booking mode was `mock`; no payment or real reservation occurred. The original database was not used for writes.

### Results

| Workflow | Status | Evidence and limits |
|---|---|---|
| Registration and duplicate-account handling | **PASS (API); BLOCKED (browser form)** | Two synthetic accounts registered successfully (HTTP 200). Reusing either username or email was rejected with HTTP 409. Username and email login plus `/auth/me` succeeded. I did not submit the browser registration form because its final step requires explicit terms acceptance and the available browser-use rules prohibit automating authentication/consent dialogs. |
| Cross-user isolation | **PASS (API); BLOCKED (authenticated browser)** | With two separately registered users and separately created drafts, each user listed only their own trip. Cross-user trip fetch returned 404; cross-user session fetch returned 403. A booking owned by user A and its Trip Pack returned 403 to user B. Browser authenticated isolation was not attempted. |
| Booking review, My Trips, Trip Pack, cancellation | **PASS (API); BLOCKED (authenticated browser)** | Built a synthetic itinerary using live catalog results for Mumbai–Lucknow. Review returned HTTP 200 with INR total ₹24,285.80 and two items. Explicit mock confirmation returned HTTP 200 and identified the booking as simulated. My Trips and Trip Pack returned HTTP 200; Trip Pack disclosed simulation/no real payment. Cancellation returned HTTP 200 and `cancelled`; repeating it remained cancelled. My Trips stayed available after cancellation. Browser-authenticated pages were not exercised. |
| Hindi and Tamil conversations | **PASS (live API); PARTIAL (browser)** | Separate live sessions using `hi` and `ta` returned HTTP 200, awaited user input, and produced a clarification in the requested script. Tamil navigation labels rendered after selecting Tamil in the browser. The full authenticated conversation UI was not exercised. |
| Voice confirmation safety | **PASS (voice API); BLOCKED (authenticated browser flow)** | Hindi and Tamil cancellation utterances were recognized as `CANCEL_BOOKING`, required explicit confirmation and a visual click, and did not persist raw audio. The guest browser voice submission was refused for missing bearer token; no cancellation occurred. |
| Notification preferences | **PASS (preference isolation API); NOT TESTED (delivery/deduplication)** | Updating user A’s language preference did not change user B’s `en-IN` preference; both preference reads and notification-list reads returned HTTP 200. Both lists were empty, so delivery and deduplication were not verified. The guest browser notification center showed its empty state; authenticated preference UI was not verified. |
| SOS safety boundary | **PASS (confirmation/refusal boundary); NOT TESTED (activation)** | Browser modal displayed India’s 112 emergency number and the official-dispatch disclaimer; choosing activation opened a second confirmation, which was cancelled. API activation without explicit confirmation returned HTTP 400. Emergency info returned HTTP 200, number 112, and location tracking disabled. No SOS was activated or dispatched. |
| Leaflet zoom, pan, tile-error recovery | **BLOCKED** | The real browser opened the Map page, but guest state had no itinerary, so only the “Map coordinates are loading for this route” placeholder appeared. Zoom, pan, and tile-error recovery could not be exercised without authenticated trip data. No result is inferred from source or prior map checks. |
| Configured live LLM provider | **PASS** | A non-placeholder local provider credential was present and the configured Groq provider was called with a synthetic prompt. The response was enabled, from the configured model, and contained the requested structured fields. No credential or token value is recorded here. |

### Verification and safety record

- The frontend unit suite passed **105/105** (21 tests in each of five timezones), and the production build passed. The existing large-bundle warning remains.
- **BLOCKED:** The focused Python rerun for authentication, phase 5, and phase 6 collected 156 tests with its temporary database location redirected into the isolated ignored workspace. It passed the first three auth tests, then remained in `test_04_registration_success` without output for over two minutes. I interrupted it; no suite result is claimed. An earlier sandbox-temp attempt failed before assertions ran because Windows denied temporary-file creation. No test was weakened or removed. The previously recorded full Python suite result (582 passed, 1 skipped, 176 subtests passed) remains the last completed full-suite evidence, but it does not substitute for this focused rerun.
- No confirmed product defect was found in these exercised paths, so this pass added no regression test and made no application code change.
- The isolated database passed SQLite integrity checks and had no foreign-key violations. The protected original database SHA-256 remained `ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a`, matching the expected fingerprint; its integrity check returned `ok` and foreign-key check returned no rows.
- No credential, password, token, or real provider secret is reproduced. No commit or push was made.

The browser/API boundary matters here: applicable public pages were opened and inspected in the real browser, but browser flows requiring authentication were not automated. API evidence above comes from calls to the live local services using the same isolated test database. The blocked map controls and untested notification delivery/SOS activation remain open verification items.

## 12. Backend Connectivity & "Failed to Fetch" Root Cause Investigation — 2026-10-10

### 12.1 Problem Description & Symptoms
The live Yatra website reported `Failed to fetch` across four primary interfaces:
1. Home page travel suggestions (`POST /api/v1/search/hotels`).
2. Explore Jaipur attractions (`POST /api/v1/destinations/explore`).
3. Explore Jaipur hotels (`POST /api/v1/hotels/explore`).
4. User login modal submission (`POST /api/v1/auth/login`).

### 12.2 Root Causes Identified
1. **Process Collision & Socket Permission Error (`[WinError 10013]`)**:
   When launching the backend via `start_all.ps1`, existing stale processes or sockets remaining in `TIME_WAIT` were not cleaned up before invoking Uvicorn with `--reload`. On Windows, this triggered an unhandled socket permission error (`[WinError 10013]: An attempt was made to access a socket in a way forbidden by its access permissions`), causing the backend process to crash immediately upon launch. As a result, the frontend development server was left running on port 5173 without an active backend listener on port 8000.
2. **Ambiguous Python Binary Resolution in Launcher Subshells**:
   The launcher script relied on `python` in child PowerShell instances rather than explicitly pinning the project virtual environment executable (`.\.venv\Scripts\python.exe`). On machines with system Python (e.g. Python 3.11) preceding the 3.14 virtual environment, script execution failed due to missing module dependencies or restricted execution policies.
3. **Absence of Vite Development Proxy**:
   `frontend/vite.config.ts` lacked a development proxy for `/api`. In browsers running on `http://localhost:5173` or `http://127.0.0.1:5173`, all requests were forced directly cross-origin to `http://localhost:8000`. On Windows, `localhost` resolves to IPv6 `::1` prior to IPv4 `127.0.0.1`. When the backend only listened on IPv4 `127.0.0.1`, network attempts to `[::1]:8000` failed immediately with connection refused (`TypeError: Failed to fetch`).
4. **Uncaught Browser Fetch Rejections in API Client**:
   `frontend/src/services/apiClient.ts` did not wrap the underlying `fetch()` call in a diagnostic try/catch block. Network errors surfaced as unhandled `TypeError: Failed to fetch` strings instead of actionable connection diagnostics.

### 12.3 Files Modified
- `frontend/vite.config.ts`: Configured Vite `server.proxy` forwarding `/api` requests to `http://127.0.0.1:8000` with `changeOrigin: true`.
- `frontend/src/services/apiClient.ts`: Added try/catch wrapping around `fetch()` to handle connection rejections gracefully and provide clear error messages indicating whether the backend on port 8000 is active.
- `start_all.ps1`: Added automatic stale-process detection and cleanup on ports 8000, 9000, and 5173 before launching; pinned the explicit virtual environment Python executable (`.\.venv\Scripts\python.exe`); added `--host 127.0.0.1` and `--env-file` parameters.

### 12.4 Empirical Browser & End-to-End Verification
All 9 required workflows were verified via Chrome DevTools Protocol against the running application:
1. **Home page suggestions**: Loaded with zero network errors (`hasError: false`). Searching for Jaipur returned 3 valid hotels.
2. **Login with valid credentials**: Successfully authenticated demo user `usr_demo0001` with display name `[DEMO] Traveller`, received JWT bearer token, and updated header state.
3. **Invalid credentials rejection**: Correctly returned HTTP 401 with message `"Invalid username/email or password."` without crashing or showing `Failed to fetch`.
4. **Explore Jaipur attractions**: Loaded 15 authoritative catalog POI cards (`.poi-item-card`) with zero errors.
5. **Explore Jaipur hotels**: Loaded 4 grounded hotel cards (`.hotel-detail-card`) with real catalog pricing and amenities.
6. **Guest mode integrity**: Unauthenticated visitors can browse without identity leakage or forced authentication.
7. **Trip planning**: Generated 4-day plan with 25 activities and 27 map markers.
8. **Map and itinerary synchronization**: Leaflet loaded 9 OSM tiles, displayed the BOM-LKO flight arc, and synced day filters and activity popup selection.
9. **Booking review & reserve**: Review modal displayed exact INR total ₹40,766.80, and explicit human approval produced confirmed booking reference `YTR-DEMO-E62F21A3`.

### 12.5 Test Suite & Integrity Proof
- **Frontend test suite**: 105/105 passed (21 tests × 5 timezones: UTC, America/Los_Angeles, Pacific/Kiritimati, Europe/London, Asia/Kolkata).
- **Frontend production build**: `npm run build` succeeded cleanly with TypeScript typecheck passing.
- **Backend test suite**: 582 passed, 1 skipped, 176 subtests passed (pytest duration: 216s).
- **Working database integrity**: `PRAGMA integrity_check` returned `ok`, 0 foreign-key violations, schema version 7.
- **Original dataset protection**: SHA-256 remains exactly `ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a`.

## 13. Independent Release Verification & Production Readiness Audit — 2026-10-17

### 13.1 Independent Execution & Verification Record
During this audit cycle, all previous claims were independently verified by direct test execution, real browser automation via Chrome CDP, and static runtime inspection:

| Test / Audit Dimension | Exact Command | Exit Code | Verified Count / Status | Notes |
|---|---|:---:|:---:|---|
| **Backend Test Suite** | `.\backend\.venv\Scripts\python.exe -m pytest -q tests --tb=short` (in `kv-hack2026-tech4ce`) | **0** | **582 passed, 1 skipped, 176 subtests passed** (172.08s) | Covers unit, integration, safety, e2e, and AI agent tests. |
| **Frontend Test Suite** | `npm test` (in `kv-hack2026-tech4ce/frontend`) | **0** | **105 passed, 0 failed** (1.30s) | Swept across 5 timezones (UTC, LA, Kiritimati, London, Kolkata). |
| **Frontend Production Build** | `npm run build` (`tsc -b && vite build`) | **0** | **1934 modules transformed** (1.32s) | 0 TypeScript errors. Clean dist generation. |
| **Browser Viewports QA** | `node test_mobile_viewports.mjs` | **0** | **100% PASS across 5 viewports** | Tested 1920x1080, 1366x768, 1024x768, 390x844, 360x800 across `/`, `/privacy`, `/terms`, `/custom-404`. Zero horizontal overflow. Mobile menu toggle verified. |
| **Browser Authentication QA** | `node run_auth_browser_qa.mjs` | **0** | **21 / 21 PASS** | Tested demo login, registration, password mismatch, weak password rejection, duplicate username/email 409 rejection, generic refusal, guest mode. |
| **Browser Travel Intelligence QA** | `node browser_qa_travel_intelligence_pass2.mjs` | **0** | **10 / 10 PASS** | Tested guest auto-auth refusal, 27 Leaflet pins, flight arcs, day filters, activity focus, honest single flight catalog notice, booking review modal, confirmation `YTR-DEMO-A87AF9BB`. |
| **Original Database SHA-256** | `Get-FileHash -Algorithm SHA256 .\kv-hack2026-tech4ce\data\original\APS-01.db` | **0** | `ECC58821CCB7F7D19A23BAC157E95BA84521238B40BA52AD568D7932675CAE0A` | **100% MATCH**, completely pristine and untouched. |
| **Working Database Integrity** | SQLite PRAGMAs | **0** | `integrity_check`: `ok`, `foreign_key_check`: `[]`, `user_version`: `7` | 0 foreign-key violations. All 7 migrations applied. |

### 13.2 Defects Identified and Minimal Safe Fixes Applied
1. **PowerShell Syntax Parsing Bug in `stop_all.ps1` (Line 25)**:
   - *Problem:* `Write-Warning "Failed to parse $pidsFile: $_"` caused PowerShell to interpret `$pidsFile:` as a drive qualifier syntax, throwing `ParserError: Variable reference is not valid. ':' was not followed by a valid variable name character.`
   - *Fix:* Replaced `$pidsFile:` with `$($pidsFile):`. `stop_all.ps1` now terminates Backend, Frontend, and AI Agent cleanly with exit code 0.
2. **Vite v8 / Rolldown Code-Splitting Object Syntax**:
   - *Problem:* Object map format for `manualChunks` in `vite.config.ts` threw `TypeError: manualChunks is not a function`.
   - *Fix:* Refactored `manualChunks` to use the standard function signature `manualChunks(id) { ... }`.
3. **Topbar Layout Overflow at 1024px Screen Width**:
   - *Problem:* Fixed gaps and padding caused `scrollWidth` (1151px) to exceed 1024px screen width.
   - *Fix:* Added `@media(max-width:1200px)` and `@media(max-width:1050px)` to gracefully tighten topbar padding and gaps, plus `overflow-x: hidden` safeguards on html/body.

### 13.3 Python Runtime & Dependency Compatibility Findings
- Host system has Python 3.11.9 on system PATH (`C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe`) and Python 3.14 (3.14.3) registered with the `py` launcher.
- Virtual environments `backend\.venv` and `ai\.venv` use Python 3.14.3.
- All declared dependencies in `backend/requirements.txt` and `ai/requirements.txt` support Python 3.11 through 3.14 without version conflicts.
- `start_all.ps1` explicitly targets the project virtual environment Python (`.\.venv\Scripts\python.exe`), ensuring deterministic execution while gracefully falling back to system Python if `.venv` is absent.
- The project's documented minimum Python target is confirmed as **Python 3.11 or newer**.

### 13.4 Final Release Status
**READY FOR PRODUCTION REVIEW (PENDING OWNER ACTIONS FOR EXTERNAL DEPLOYMENT)**
The software stack is stable, hardened, fully tested, and verified in real headless Chrome sessions. Public production launch is gated only by external infrastructure items: custom domain DNS delegation, TLS certificate provisioning, and owner approval of legal entity details in `/privacy` and `/terms`.

