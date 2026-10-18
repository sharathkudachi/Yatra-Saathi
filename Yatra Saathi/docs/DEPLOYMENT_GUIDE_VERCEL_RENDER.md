# Yatra AI Travel Concierge — Production Deployment Guide
## GitHub + Vercel (Frontend) + Render (Backend & AI Service)

**Target Topology:** Multi-cloud decoupled deployment using platform subdomains (no custom domain purchase required).  
**Canonical Application Root:** `kv-hack2026-tech4ce/`  
**Date:** 2026-10-17  

---

## 1. Architectural Overview & Service Topology

```
┌────────────────────────────────────────────────────────┐
│                   Vercel Edge Network                  │
│       Frontend: https://yatra-frontend.vercel.app      │
│   (React + Vite SPA · vercel.json SPA Route Rewrites)  │
└───────────────────────────┬────────────────────────────┘
                            │ HTTPS API Calls (Bearer JWT)
                            ▼
┌────────────────────────────────────────────────────────┐
│                    Render Cloud                        │
│    Backend API: https://yatra-backend.onrender.com     │
│       (FastAPI · Authoritative Money & Bookings)       │
│                                                        │
│   Storage: Persistent Disk /var/data/aps01_working.db  │
│   Original Dataset: data/original/APS-01.db (read-only)│
└───────────────────────────┬────────────────────────────┘
                            │ HTTPS / Runs (X-Service-Key)
                            ▼
┌────────────────────────────────────────────────────────┐
│                    Render Cloud                        │
│      AI Service: https://yatra-ai.onrender.com         │
│         (LangGraph / Groq · Stateless Worker)          │
└────────────────────────────────────────────────────────┘
```

---

## 2. Platform Tiers, Limitations & Cost Transparency

### 2.1 Free Tier Capabilities
- **Vercel Hobby (Free):** 100% free. Provides unlimited deployments, global CDN distribution, automatic HTTPS certificates on `*.vercel.app`, and SPA routing.
- **Render Free Web Services:** $0/month.
  - **Cold Starts:** Free instances spin down after 15 minutes of inactivity. First request takes ~50 seconds to wake up.
  - **Ephemeral Disk Limitation:** Render Free tier web services **do not support persistent disks**.
  - **What happens on Free Tier:** On every container restart, sleep/wake cycle, or new deploy, the container filesystem is reset. `scripts/init_production_db.py` will automatically recreate the working database from the original `APS-01.db`, but any new user registrations, custom trips, or demo bookings created during that session will be cleared on container sleep.

### 2.2 Paid Requirements for Durable SQLite Persistence
- **Render Persistent Disks:** Require a **Starter instance type** ($7/month) + **Persistent Disk** ($0.25/GB/month, min 1GB = $0.25).
- **Total Minimum Cost for 100% Persistent Storage:** **$7.25/month** on Render for the backend service.
- **SQLite Concurrency Rule:** Render disks can only be mounted to **a single backend container** (`numInstances: 1`). SQLite does not support horizontal multi-server concurrent writing.

### 2.3 AI Service Networking
- **Render Private Services (Internal DNS):** Available on Render Starter plans ($7/month).
- **Free-Tier Safe Alternative:** Deploy the AI agent as a **Public Web Service** on the Free plan (`https://yatra-ai.onrender.com`), protected by the existing `X-Service-Key` header authentication (`AGENT_SERVICE_KEY`). The service rejects all unauthenticated external traffic with HTTP 401.

---

## 3. Step-by-Step Deployment Procedure

### STEP 1: GitHub Repository Preparation

1. **Verify `.gitignore` Safeguards:**
   Ensure secrets, virtual environments, caches, and local databases are excluded:
   ```bash
   git status --ignored
   ```
   Confirm that `data/original/APS-01.db` is tracked, while `backend/var/` and all `.env` files are ignored.

2. **Commit and Push to GitHub:**
   ```bash
   git add .
   git commit -m "chore: prepare repository for Vercel and Render deployment"
   git branch -M main
   git remote add origin https://github.com/<YOUR_GITHUB_USER>/yatra-travel-concierge.git
   git push -u origin main
   ```

---

### STEP 2: Deploy AI Agent Service on Render

1. Log into [Render Dashboard](https://dashboard.render.com).
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository.
4. Configure service details:
   - **Name:** `yatra-ai`
   - **Region:** Choose closest region to users (e.g. `Frankfurt` or `Oregon`).
   - **Root Directory:** `kv-hack2026-tech4ce/ai`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python run_production.py` *(or `uvicorn service:app --host 0.0.0.0 --port $PORT`)*
   - **Instance Type:** `Free` (or `Starter` if private service preferred).
5. **Add Environment Variables:**
   | Variable | Value | Purpose |
   |---|---|---|
   | `BACKEND_URL` | `https://yatra-backend.onrender.com` | Target URL for AI agent to call backend tools |
   | `AGENT_SERVICE_KEY` | *(Generate a 32+ character random string)* | Shared auth token matching backend |
   | `GROQ_API_KEY` | *(Your Groq API Key)* | LLM execution provider |
   | `TRAVEL_AGENT_LLM_MODEL` | `openai/gpt-oss-120b` | Model identifier |
   | `TRAVEL_AGENT_DISABLE_LLM` | `0` | Enable live AI model (set `1` for deterministic fallback) |
6. Click **Create Web Service**.
7. Note your public AI service URL: `https://yatra-ai.onrender.com`.

---

### STEP 3: Deploy Backend API on Render

1. Click **New +** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure service details:
   - **Name:** `yatra-backend`
   - **Region:** Same region as AI agent (e.g. `Frankfurt`).
   - **Root Directory:** `kv-hack2026-tech4ce/backend`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python -m scripts.run_production`
   - **Instance Type:**
     - For Free/Demo mode: `Free`
     - For Persistent SQLite: `Starter` ($7/mo)
4. **If using Render Starter Plan (Persistent Disk):**
   - Scroll to **Disks** -> Click **Add Disk**.
   - **Name:** `yatra-data`
   - **Mount Path:** `/var/data`
   - **Size:** `1 GB`
5. **Add Environment Variables:**
   | Variable | Value (Description) |
   |---|---|
   | `APS_DB_ORIGINAL_PATH` | `/opt/render/project/src/kv-hack2026-tech4ce/data/original/APS-01.db` |
   | `APS_DB_ORIGINAL_SHA256` | `ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a` |
   | `APS_DB_PATH` | `/var/data/aps01_working.db` *(or `/opt/render/project/src/kv-hack2026-tech4ce/backend/var/aps01_working.db` if free tier)* |
   | `BOOKING_MODE` | `mock` |
   | `TAX_RATE_BP` | `1200` |
   | `REPLAN_LIMIT` | `3` |
   | `CONFIRMATION_TTL_SECONDS` | `900` |
   | `HUMAN_TOKEN_SECRET` | *(Generate 64-char hex secret: `python -c "import secrets; print(secrets.token_hex(32))"`)* |
   | `AGENT_TOKEN_SECRET` | *(Generate different 64-char hex secret)* |
   | `AGENT_SERVICE_KEY` | *(Must exactly match `AGENT_SERVICE_KEY` from AI service)* |
   | `AGENT_SERVICE_URL` | `https://yatra-ai.onrender.com` |
   | `DEMO_LOGIN_USER_IDS` | `usr_demo0001` |
   | `CORS_ALLOW_ORIGINS` | `https://yatra-frontend.vercel.app` *(update after Step 4)* |
6. **Health Check Path:** `/api/v1/health`
7. Click **Create Web Service**.
8. Note your public backend URL: `https://yatra-backend.onrender.com`.

---

### STEP 4: Deploy Frontend on Vercel

1. Log into [Vercel](https://vercel.com).
2. Click **Add New...** -> **Project**.
3. Import your GitHub repository `yatra-travel-concierge`.
4. Configure project settings:
   - **Project Name:** `yatra-frontend`
   - **Framework Preset:** `Vite`
   - **Root Directory:** Click Edit -> Select `kv-hack2026-tech4ce/frontend`
   - **Build Command:** `npm run build`
   - **Output Directory:** `dist`
   - **Install Command:** `npm install`
5. **Add Environment Variables:**
   | Variable | Value |
   |---|---|
   | `VITE_API_BASE_URL` | `https://yatra-backend.onrender.com` |
   | `VITE_USE_MOCK_API` | `false` |
6. Click **Deploy**.
7. Note your public frontend URL: `https://yatra-frontend.vercel.app`.
8. **Final CORS Alignment:** Return to Render Dashboard -> `yatra-backend` -> Environment Variables, and set `CORS_ALLOW_ORIGINS=https://yatra-frontend.vercel.app`.

---

## 4. Legal Pages Action Checklist (Owner Required Details)

Before declaring production ready, replace the placeholders in:

1. **`kv-hack2026-tech4ce/frontend/src/app/PrivacyPolicyPage.tsx` (Lines 209–211):**
   - [ ] Operating Entity: Replace `[Legal Entity Name to be specified prior to production launch]` with legal entity name.
   - [ ] Privacy Email: Replace `privacy@example.com` with official privacy email.
   - [ ] Physical Address: Replace `[Registered business address to be specified prior to production launch]` with official postal address.

2. **`kv-hack2026-tech4ce/frontend/src/app/TermsPage.tsx` (Lines 195–196):**
   - [ ] Jurisdiction: Replace `[Applicable state/national jurisdiction to be designated prior to launch]` (e.g. *State of Karnataka, India* or *Delaware, USA*).
   - [ ] Legal Email: Replace `legal@example.com` with official contact email.

---

## 5. Post-Deployment Smoke Test Protocol

Run these verification checks immediately after deployment:

1. **Backend Health Check:**
   ```bash
   curl -i https://yatra-backend.onrender.com/api/v1/health
   # Expected: HTTP 200 {"ok":true,"status":"ok","data":{"status":"ok"},"refusal":null}
   ```
2. **AI Service Health Check:**
   ```bash
   curl -i https://yatra-ai.onrender.com/health
   # Expected: HTTP 200 {"ok":true}
   ```
3. **Frontend SPA Navigation Check:**
   - Open `https://yatra-frontend.vercel.app/`
   - Directly navigate to `https://yatra-frontend.vercel.app/privacy` (verify no 404 from Vercel)
   - Directly navigate to `https://yatra-frontend.vercel.app/terms`
4. **End-to-End Live Workflow Smoke Test:**
   - On the homepage, sign in using demo user: `usr_demo0001` / `DemoPass1234!`
   - Plan a 3-night trip (e.g. Mumbai to Goa).
   - Verify Leaflet OpenStreetMap tiles render with blue geodesic flight arc.
   - Click "Review & Reserve Demo Booking".
   - Confirm booking and verify confirmation reference (e.g. `YTR-DEMO-...`).
   - Check "My Trips" to confirm reservation displays in active trips list.
