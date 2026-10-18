# Yatra AI Travel Concierge — Production Deployment Guide
## GitHub + Vercel (Frontend) + Render (Backend & AI Service)

**Target Topology:** Multi-cloud decoupled deployment using platform subdomains (no custom domain purchase required).  
**Canonical Application Root:** `Yatra Saathi/`  
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

## 2.4 Free Persistent Database Setup (Neon Serverless PostgreSQL)

Render's free tier web services have ephemeral disks (they reset on restart/spin-down). To achieve **100% free, permanent database persistence** without paying for a Render Starter plan or disk:

### STEP A: Create a Free Neon PostgreSQL Database
1. Go to **[https://neon.tech](https://neon.tech)** and sign up for the **Free Plan** (no credit card required).
2. Click **Create Project**:
   - **Project Name:** `yatra-saathi`
   - **Postgres Version:** `16` (or latest)
   - **Region:** Choose the region closest to your Render service (e.g., `US East (Ohio)` or `Frankfurt`).
3. Under the **Dashboard** -> **Connection Details**:
   - Select **Pooled connection** (recommended for serverless/free apps) or standard connection.
   - Copy the connection string. It has this format:
     ```
     postgresql://neondb_owner:YOUR_PASSWORD@ep-sample-123456-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require
     ```

### STEP B: Configure Backend on Render
1. In your **Render Dashboard** -> Go to your `yatra-backend` Web Service.
2. Navigate to **Environment Variables** -> Click **Add Environment Variable**:
   - **Key:** `DATABASE_URL`
   - **Value:** *(Paste your Neon connection string)*
3. When the backend starts up on Render, `run_production.py` will:
   - Detect `DATABASE_URL`.
   - Idempotently apply all PostgreSQL schemas, indexes, and triggers via `init_postgres_schema()`.
   - Seed the initial demo user `usr_demo0001`.
   - Validate connectivity without printing your password or full connection string to logs.

### STEP C: (Optional) Seed Reference Catalog into PostgreSQL
If you want the flight, hotel, airport, and city catalog data loaded directly into your remote Neon database:
1. Run the safe, audited catalog seeder from your local machine:
   ```bash
   $env:DATABASE_URL="your-neon-connection-string"
   python -m scripts.seed_postgres_catalog
   ```
   *Note: This script transfers only the 11 public catalog tables. It explicitly ignores and never transfers any private user, booking, or session data.*
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
   git remote add origin https://github.com/sharathkudachi/Yatra-Saathi.git
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
   - **Root Directory:** `Yatra Saathi/ai`
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
   - **Root Directory:** `Yatra Saathi/backend`
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
   | `APS_DB_ORIGINAL_PATH` | `/opt/render/project/src/Yatra Saathi/data/original/APS-01.db` |
   | `APS_DB_ORIGINAL_SHA256` | `ecc58821ccb7f7d19a23bac157e95ba84521238b40ba52ad568d7932675cae0a` |
   | `APS_DB_PATH` | `/var/data/aps01_working.db` *(or `/opt/render/project/src/Yatra Saathi/backend/var/aps01_working.db` if free tier)* |
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
3. Import your GitHub repository `Yatra-Saathi`.
4. Configure project settings:
   - **Project Name:** `yatra-frontend`
   - **Framework Preset:** `Vite`
   - **Root Directory:** Click Edit -> Select `Yatra Saathi/frontend`
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

1. **`Yatra Saathi/frontend/src/app/PrivacyPolicyPage.tsx` (Lines 209–211):**
   - [ ] Operating Entity: Replace `[Legal Entity Name to be specified prior to production launch]` with legal entity name.
   - [ ] Privacy Email: Replace `sharathkudachi30@gmail.com` with official privacy email.
   - [ ] Physical Address: Replace `[Registered business address to be specified prior to production launch]` with official postal address.

2. **`Yatra Saathi/frontend/src/app/TermsPage.tsx` (Lines 195–196):**
   - [ ] Jurisdiction: Replace `[Applicable state/national jurisdiction to be designated prior to launch]` (e.g. *State of Karnataka, India* or *Delaware, USA*).
   - [ ] Legal Email: Replace `sharathkudachi30@gmail.com` with official contact email.

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
