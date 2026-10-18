# Yatra — Workspace Structure and Local Startup Run Guide

## 1. Canonical Project Root

The single canonical Yatra application root is:

```
kv-hack2026-tech4ce/
```

All active runtime code, backend APIs, autonomous AI agent services, frontend UI components, tests, migrations, and database assets reside strictly within this directory. The outer workspace contains project orchestrators, developer/agent tooling, and historical archives.

---

## 2. Retained Top-Level Workspace Structure

| Directory / File | Category | Purpose & Description |
|---|---|---|
| `kv-hack2026-tech4ce/` | **A. Runtime** | The canonical full-stack application (FastAPI backend, LangGraph AI agent service, React/TypeScript frontend, migrations, tests, dataset). |
| `start_all.ps1` | **A. Runtime** | Master startup orchestrator for Windows PowerShell. Performs zero-exposure config verification, port availability checks, service startup, separate log capture, and health polling. |
| `stop_all.ps1` | **A. Runtime** | Master shutdown script. Identifies tracked PIDs from `.logs/pids.json` and cleanly stops Yatra processes without terminating unrelated system processes. |
| `.logs/` | **A. Runtime** | Output log directory containing `backend.log`, `ai.log`, `frontend.log`, and process tracking state `pids.json`. |
| `.env` | **A. Runtime** | Workspace-level environment file containing top-level tool variables (e.g. `GROQ_API_KEY`). Preserved untouched. |
| `archive/` | **C. Historical** | Safe archive preserving previous prototype code, Developer 2 historical handoff package, and presentation decks. |
| `adapters/` | **B. Development** | Model adapter reference documentation (`CLAUDE.md`, `GEMINI.md`, `GPT_OSS.md`) referenced in `PROJECT_RULES.md`. |
| `scripts/` | **B. Development** | Repository search and agent validation scripts (`validate-all.ps1`, `setup_search.ps1`, etc.). |
| `.agent/`, `.agents/` | **B. Development** | Active Antigravity / Gemini agentic IDE workflows and skill packages. |
| `.gemini/`, `.gsd/` | **B. Development** | Agent IDE rules (`GEMINI.md`) and Get-Shit-Done (GSD) templates. |
| `README.md`, `HACKATHON.md`, `PROJECT_RULES.md`, `API_HANDOFF.md`, `GSD-STYLE.md`, `VERSION`, `model_capabilities.yaml` | **C. Reference** | Canonical hackathon instructions, rulebooks, and handoff documentation. Preserved intact. |

---

## 3. Workspace Cleanup & Archival Record

### A. Confirmed Disposable Artifacts Removed
- **Outer `node_modules/`**: Obsolete 36-package dependency directory belonging to the abandoned outer prototype. Removed to reclaim disk space and prevent module resolution ambiguity.
- **Root `.DS_Store` & `backend-2/.DS_Store`**: Disposable macOS metadata files. Removed.
- **Root `/package-lock.json`**: Moved into `archive/outer_prototype/package-lock.json`.

### B. Historical Materials Safely Archived
- **`backend-2/` -> `archive/backend-2/`**: Developer 2's historical LangGraph travel agent package (`DEVELOPER2_INTEGRATION.md`, `developer2_travel_agent.zip`, tests, requirements). The active agent was previously integrated into `kv-hack2026-tech4ce/ai/`.
- **Outer Prototype -> `archive/outer_prototype/`**: Early frontend prototype snapshot (`src/` [17 files], `package.json`, `index.html`, `vite.config.ts`, `tsconfig.json`, `tsconfig.app.json`, `package-lock.json`).
- **Presentations -> `archive/presentations/`**: Evaluator pitch deck (`Yatra_Evaluator_Pitch_Ready.pptx`) and architecture specification (`Tech4ce AI Autonomous Travel Agent.pdf`).
- **Scratch Scripts & Debug Dumps -> `archive/scratch_debug/`**: Archived ad-hoc verification scripts (`scratch_*.py`, `scratch_*.mjs`, `scratch_prompt.txt`, `check_dom.py`, `rendered.html`, `out_test20.txt`, `find_overflow.mjs`) to maintain a clean canonical application root.

### C. Items Intentionally Retained (Purpose Uncertain / Safe Safeguards)
- **0-Byte Database Touch Files**: `kv-hack2026-tech4ce/aps01_working.db`, `kv-hack2026-tech4ce/yatra.db`, `kv-hack2026-tech4ce/backend/aps01_working.db`, `kv-hack2026-tech4ce/backend/var/primary.db`, `kv-hack2026-tech4ce/backend/var/yatra.db`, `kv-hack2026-tech4ce/data/APS-01.db`, `kv-hack2026-tech4ce/data/aps01_working.db`, `kv-hack2026-tech4ce/data/travel.db`. In compliance with Non-Negotiable Rule 5 ("Do not reset or recreate the working database"), these files were left completely untouched.

---

## 4. Software Requirements

- **Operating System:** Microsoft Windows 10/11 (64-bit)
- **PowerShell:** Windows PowerShell 5.1 or PowerShell 7+
- **Python:** Python 3.13 or 3.14 (64-bit) with `venv`
- **Node.js:** Node.js v20.x or v22.x LTS
- **Package Manager:** `npm` v10.x+
- **Browser:** Google Chrome (for manual interaction or CDP-based automated browser QA)

---

## 5. Environment Configurations & Secrets

Local configuration files must NEVER be committed to Git. Templates with dummy values are tracked as `.env.example`.

### A. Backend: `kv-hack2026-tech4ce/backend/.env.backend`
```env
APS_DB_ORIGINAL_PATH=C:/Users/Administrator/OneDrive/Desktop/kv-hack2026-tech4ce-main/kv-hack2026-tech4ce/data/original/APS-01.db
APS_DB_ORIGINAL_SHA256=ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a
APS_DB_PATH=C:/Users/Administrator/OneDrive/Desktop/kv-hack2026-tech4ce-main/kv-hack2026-tech4ce/backend/var/aps01_working.db
BOOKING_MODE=mock
TAX_RATE_BP=1200
REPLAN_LIMIT=3
CONFIRMATION_TTL_SECONDS=900
AGENT_STATE_MAX_BYTES=65536
DB_BUSY_TIMEOUT_MS=5000
HUMAN_TOKEN_SECRET=<generated_hex_secret>
AGENT_TOKEN_SECRET=<generated_hex_secret>
AGENT_SERVICE_KEY=9f1d7a9f4e4a4d0e8a9d16a1b7d5c2e4
AGENT_SERVICE_URL=http://localhost:9000
DEMO_LOGIN_USER_IDS=usr_demo0001
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### B. AI Agent: `kv-hack2026-tech4ce/ai/.env.agent`
```env
BACKEND_URL=http://localhost:8000
AGENT_SERVICE_KEY=9f1d7a9f4e4a4d0e8a9d16a1b7d5c2e4
GROQ_API_KEY=<your_groq_api_key>
TRAVEL_AGENT_LLM_MODEL=openai/gpt-oss-120b
TRAVEL_AGENT_DISABLE_LLM=0
```

### C. Frontend: `kv-hack2026-tech4ce/frontend/.env.local`
```env
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8000
```
> **Security Rule:** Frontend `.env.local` contains ONLY `VITE_*` public variables and NEVER database secrets, token signing keys, or private API keys. The map renders via public OpenStreetMap raster tiles without requiring a proprietary MapTiler key.

---

## 6. Database Verification & Safeguards

### Canonical Original Database
- **Path:** `kv-hack2026-tech4ce/data/original/APS-01.db`
- **Expected SHA-256:** `ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a`
- **Integrity Status:** `PRAGMA integrity_check` -> `ok` (Read-only, strictly protected by code guards and test triggers).

### Working Database
- **Path:** `kv-hack2026-tech4ce/backend/var/aps01_working.db`
- **Integrity Status:** `PRAGMA integrity_check` -> `ok`, `PRAGMA foreign_key_check` -> 0 violations.
- **Migrations Applied:** 0001 through 0007 (including Phase 5 booking lifecycle, Phase 6 multimodal intelligence, and secure user authentication with Argon2id).

---

## 7. Starting and Stopping the Application

From the root workspace directory (`kv-hack2026-tech4ce-main`):

### To Start All Services
```powershell
.\start_all.ps1
```
Or to run in persistent monitoring/daemon mode:
```powershell
.\start_all.ps1 -Wait
```

The script will:
1. Verify configuration files and virtual environments without exposing secrets.
2. Check ports 8000, 9000, and 5173, safely terminating any stale processes.
3. Launch Backend, AI Agent, and Frontend services in isolated background sessions.
4. Capture stdout and stderr separately in `.logs/backend.log`, `.logs/ai.log`, and `.logs/frontend.log`.
5. Actively probe real HTTP health endpoints until all three report healthy.
6. Record listening PIDs in `.logs/pids.json` and display a clean status table.

### To Stop All Services
```powershell
.\stop_all.ps1
```
The script will cleanly stop the tracked PIDs recorded in `.logs/pids.json` and confirm all ports are released.

---

## 8. Service Endpoints and Port Reference

| Service | Port | Endpoint URL | Registered Health URL |
|---|---|---|---|
| **Frontend UI** | `5173` | `http://localhost:5173/` | `http://127.0.0.1:5173/` (HTTP 200) |
| **Backend API** | `8000` | `http://localhost:8000/` | `http://127.0.0.1:8000/api/v1/health` (`{"status":"ok"}`) |
| **AI Agent Service** | `9000` | `http://localhost:9000/` | `http://127.0.0.1:9000/health` (`{"ok":true}`) |

---

## 9. Running Automated Test Suites

### Frontend Tests (Multi-Timezone)
```powershell
cd kv-hack2026-tech4ce\frontend
npm test
```
*Executes 21 unit tests across 5 timezones (`Asia/Kolkata`, `UTC`, `America/Los_Angeles`, `Pacific/Kiritimati`, `Europe/London`), yielding 105/105 passed.*

### Frontend Production Build
```powershell
cd kv-hack2026-tech4ce\frontend
npm run build
```
*Validates TypeScript compilation (`tsc -b`) and Vite production bundle generation.*

### Python Full Test Suite
```powershell
cd kv-hack2026-tech4ce
.\backend\.venv\Scripts\python.exe -m pytest -q tests --tb=short
```
*Executes 582 passed tests, 1 skipped (symlink test requiring elevated Windows OS privilege), and 176 subtests.*

### Full Live Browser QA Automation (Chrome CDP)
With services running via `.\start_all.ps1`:
```powershell
cd kv-hack2026-tech4ce
node browser_qa_travel_intelligence_pass2.mjs
node run_auth_browser_qa.mjs
```

---

## 10. Known Limitations & Notes

1. **Windows Symlink Test Skip:** In `tests/safety/test_original_protection.py`, one test tests symlink resolution. On Windows, non-admin users lack `SeCreateSymbolicLinkPrivilege`, so Python skips this single test gracefully.
2. **Single Flight Route in Sample Catalog:** In the sample database catalog for Mumbai–Lucknow, exactly one flight meets the criteria. The UI accurately displays an authoritative catalog notice explaining this constraint.
3. **Vite Bundle Size Warning:** The production build reports main bundle size > 500 KB due to Leaflet and Three.js XR dependencies. This is a normal performance advisory, not a build error.
4. **Argon2id Hash Processing:** Password verification uses high-memory Argon2id encryption. In constrained virtual environments, auth requests may take 100–300ms to evaluate safely.

---

## 11. Troubleshooting Guide

- **Port in Use (8000, 9000, 5173):** Run `.\stop_all.ps1`. If an external application holds the port, inspect using `Get-NetTCPConnection -LocalPort <port>`.
- **Backend Fails to Start:** Inspect `.logs/backend.log`. Ensure `APS_DB_PATH` points to `var/aps01_working.db` and not the read-only `APS-01.db`.
- **Database Missing:** Ensure `kv-hack2026-tech4ce/data/original/APS-01.db` exists and has SHA-256 `ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a`.
- **Frontend Empty Cards / Failed to Fetch:** Ensure the backend is listening on port 8000 and `VITE_USE_MOCK_API=false` in `frontend/.env.local`.
