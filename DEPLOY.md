# Deploying CloudPilot (Render + Vercel)

Backend + Postgres on Render, frontend static build on Vercel. Both have a genuinely
free tier for this project's size; the only real cost of "free" is Render's backend
sleeping after ~15 minutes idle (30–50s cold start on the next request — the frontend
shows a "waking up the server" banner during this, see `frontend/src/components/
ColdStartBanner.tsx`).

## Table of contents

- [Deploy order](#deploy-order)
- [1. Render — backend + Postgres](#1-render--backend--postgres)
- [2. Vercel — frontend](#2-vercel--frontend)
- [3. Close the loop: CORS](#3-close-the-loop-cors)
- [Environment variables reference](#environment-variables-reference)
- [Troubleshooting](#troubleshooting)

## Deploy order

This matters — the frontend needs the backend's URL to build correctly, and the backend
needs the frontend's URL to accept its requests:

1. Deploy the **backend** on Render first. Copy its public URL.
2. Deploy the **frontend** on Vercel, using that URL for `VITE_API_BASE_URL`.
3. Copy the **Vercel** URL back into Render's `ALLOWED_ORIGINS`, then redeploy the
   backend so CORS actually allows it.

## 1. Render — backend + Postgres

### Option A — Blueprint (recommended)

1. Push this repo to GitHub (it already has a remote configured).
2. In the Render dashboard: **New → Blueprint**, connect the repo. Render reads
   [`render.yaml`](render.yaml) at the repo root and proposes a web service
   (`cloudpilot-backend`, Docker runtime, root dir `backend/`) plus a free Postgres
   database (`cloudpilot-db`).
3. Render will prompt for the one variable marked `sync: false` in `render.yaml`:
   `GEMINI_API_KEY`. Everything else (`DATABASE_URL`, `GEMINI_MODEL`,
   `USD_TO_INR_RATE`, `APP_ENV`) is already set from the Blueprint.
4. Apply. Render provisions the database, builds `backend/Dockerfile`, and runs its
   `CMD` — migrations run automatically on every start (`alembic upgrade head`).
5. Once it's live, seed reference pricing data once (Render's **Shell** tab on the
   service, or `render` CLI):
   ```bash
   python -m app.pricing.seed_data
   ```
6. Note the service's public URL, e.g. `https://cloudpilot-backend.onrender.com`.

Render's Blueprint YAML keys have changed between doc revisions in the past — if the
import fails or looks different in your dashboard, use Option B with the same settings.

### Option B — Manual setup

1. **New → Web Service** → connect the repo.
2. **Root Directory:** `backend`
3. **Runtime:** Docker (auto-detects `backend/Dockerfile`)
4. **Instance Type:** Free
5. **Health Check Path:** `/health`
6. **New → PostgreSQL** (separately) → Free plan → copy its **Internal Database URL**.
7. Back on the web service, add environment variables (see the
   [reference table](#environment-variables-reference) below) — paste the Postgres
   URL in as `DATABASE_URL`.
8. Deploy, then seed pricing as in step 5 above.

Render sets `$PORT` automatically; the Dockerfile's `CMD` already reads it
(`--port ${PORT:-8000}`), so no change is needed there.

## 2. Vercel — frontend

1. **Add New → Project**, import the same repo.
2. **Root Directory:** `frontend` (this is a monorepo — the backend lives in a sibling
   `backend/` directory, so this setting matters).
3. Framework preset: **Vite** (should auto-detect from `frontend/package.json`).
4. Environment variable: `VITE_API_BASE_URL` = `https://cloudpilot-backend.onrender.com/api`
   (your real Render URL from step 1, **with** the trailing `/api`).
5. Deploy.

`VITE_API_BASE_URL` is baked into the JS bundle at build time, not read at runtime — if
you set or change it after the first deploy, trigger a redeploy (**Deployments → ⋯ →
Redeploy**) so the new value actually takes effect.

`frontend/vercel.json` already adds a rewrite so client-side routes (e.g. refreshing on
`/optimization`) serve `index.html` instead of 404ing.

## 3. Close the loop: CORS

Once Vercel gives you its production URL (e.g. `https://cloudpilot.vercel.app`):

1. Render dashboard → `cloudpilot-backend` → Environment → set `ALLOWED_ORIGINS` to
   that exact URL (no trailing slash).
2. Redeploy the backend.

Vercel **preview** deployments (one per branch/PR, random `*.vercel.app` subdomains)
don't need to be added here — `app/main.py` allows any `https://*.vercel.app` origin
via `allow_origin_regex` regardless of `ALLOWED_ORIGINS`. Only your production/custom
domain needs to be listed explicitly.

## Environment variables reference

### Render (backend)

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | From the Render Postgres instance | `postgres://` URLs are normalized to `postgresql://` automatically (`app/config/settings.py`) |
| `GEMINI_API_KEY` | Your key | Secret — set manually, never committed |
| `GEMINI_MODEL` | `gemini-2.5-flash` | |
| `USD_TO_INR_RATE` | `83.0` | Display-only — never used in any calculation |
| `ALLOWED_ORIGINS` | Your Vercel production URL | Set after step 2, then redeploy |
| `APP_ENV` | `production` | |

### Vercel (frontend)

| Variable | Value | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | `https://<your-render-url>.onrender.com/api` | Build-time only — redeploy after changing |

## Troubleshooting

**CORS errors in the browser console** (`No 'Access-Control-Allow-Origin' header`)
— `ALLOWED_ORIGINS` on Render doesn't include your exact frontend origin (scheme +
host, no path, no trailing slash), or you changed it without redeploying. Preview
deployments should work automatically via the `*.vercel.app` regex — if one doesn't,
confirm its URL actually ends in `.vercel.app` (custom preview domains won't match).

**First request after a while takes 30–50s, or times out** — this is Render's free
tier waking up, not a bug. The frontend's `ColdStartBanner` should appear during the
retry; if a request fails outright instead, it exceeded the 55s retry timeout in
`frontend/src/api/client.ts` — retry manually, the backend is very likely awake now.

**Backend crashes or gets OOM-killed on Render's free tier (512MB RAM)** — the heaviest
dependency is `sentence-transformers` (pulls in PyTorch), used only by the RAG search
tool and lazily loaded on first use (`app/rag/embeddings.py::get_model()`), not at
startup. If memory is tight, the first optimization run (which triggers RAG) is the
most likely place to see this. There's no code-level fix that doesn't touch the RAG
implementation; the practical options are Render's paid tier (more RAM) or accepting
that the first RAG-triggering request per cold start may be slow.

**404 on refreshing a deep link** (e.g. `/optimization`) **on Vercel** — confirms
`frontend/vercel.json` didn't take effect; check it's present in the deployed build
(Vercel's Root Directory must be `frontend` for it to be picked up) and redeploy.

**`GET /health` returns 200 but the app is still broken** — `/health` is intentionally
DB-independent (Render's health check shouldn't flap if the database has a transient
hiccup). Check `GET /api/health` instead, which does check DB connectivity, or check
Render's logs directly.

**Migrations didn't run / `relation "usage_records" does not exist`** — the
Dockerfile's `CMD` runs `alembic upgrade head` before starting `uvicorn` on every
deploy, so this should be automatic. If it still happens, check the deploy logs for an
alembic error (most likely `DATABASE_URL` pointing at the wrong database, or a
migration conflict) rather than assuming it silently didn't run.
