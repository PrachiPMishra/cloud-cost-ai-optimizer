# Running CloudPilot locally, end to end

A single, exact walkthrough: prerequisites → configuration → data → forecast → cost →
optimization → a critic-approved plan → tests. Every command below was run against this
repo to write this doc — none are approximate.

## 1. Prerequisites

| Tool | Version used in this repo | Notes |
|---|---|---|
| Docker + Docker Compose | 28.x / Compose v5.x | Any recent Docker Desktop (or Engine + Compose plugin) works |
| Python | 3.12 (backend `Dockerfile` pins `python:3.12-slim`) | 3.12 exactly, for local (non-Docker) backend dev — `xgboost`/`faiss-cpu`/`sentence-transformers` wheels are version-sensitive |
| Node.js | 20+ (LTS) | Vite 8 requires Node ≥20.19 or ≥22.12; this repo was built against Node 26 |
| npm | bundled with Node | — |

You do **not** need a local Postgres install if you use Docker Compose (recommended).
You do **not** need any local LLM runtime — Gemini is a hosted API call.

## 2. Get a `GEMINI_API_KEY`

1. Go to [Google AI Studio](https://aistudio.google.com/apikey) and create an API key
   (free tier is enough for this project's usage pattern — a handful of short text
   completions per optimization run).
2. You do **not** strictly need one to run the app. Every agent falls back to a
   deterministic template narrative if the key is missing or invalid (see §9) — all the
   *numbers* are identical either way, since agents never compute numbers themselves.
   Get a key only if you want natural-language narration instead of templated text.

## 3. Configure environment files

CloudPilot has **two separate `.env` files** — this is the single most common setup
mistake, so do both even if you only plan to use Docker:

```bash
cd cloudpilot

# Used by `docker compose up` (docker-compose.yml has `env_file: - .env` at repo root)
cp .env.example .env

# Used by the backend when run directly (not via Docker) — Pydantic Settings loads
# `.env` relative to the CWD, which is `backend/` in that case, NOT the repo root.
cp .env.example backend/.env
```

Edit **both** files and replace `GEMINI_API_KEY=your_api_key` with your real key (or
leave it as-is to run in template-fallback mode). If you edit `backend/.env`, also fix
`DATABASE_URL` to point at wherever Postgres actually is for your chosen path (Docker's
internal hostname `postgres` won't resolve from your host machine — see §4).

```bash
cp frontend/.env.example frontend/.env   # already correct by default: http://localhost:8000/api
```

## 4. Start Postgres + backend

**Recommended path — Docker Compose for both:**

```bash
docker compose up --build
```

This builds the backend image (`backend/Dockerfile`), starts Postgres, waits for its
healthcheck, then runs the backend — whose container `CMD` already does
`alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000`, so migrations
run automatically (pricing does **not** get seeded automatically — that's §5). Skip to
§5 once this is up.

**Alternative — Postgres in Docker, backend on your host** (needed if you're iterating
on backend code without rebuilding the image each time):

```bash
docker compose up -d postgres
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# backend/.env's DATABASE_URL must say `localhost`, not `postgres`, here:
#   postgresql+psycopg2://cloudpilot:cloudpilot@localhost:5432/cloudpilot
alembic upgrade head
uvicorn app.main:app --reload
```

**Verify it's actually up before doing anything else:**

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

If this hangs or refuses the connection, Postgres isn't reachable yet or the backend
crashed on startup — check `docker compose logs backend` before proceeding to §5.

> **macOS port-5432 gotcha:** if you already run a native Postgres on your host, it
> silently intercepts `localhost:5432`, so the Docker container's Postgres becomes
> unreachable even though `docker ps` shows it healthy. Either stop the native instance,
> or remap the container's host port (e.g. `"55432:5432"` in `docker-compose.yml`) and
> update `DATABASE_URL` in `backend/.env` to match.

**From here on**, §5's and §6's Python commands need `pandas`/`numpy`/SQLAlchemy
available. If your backend is running via Docker Compose, run them with
`docker compose exec backend ...` (shown below) — no separate host venv needed. If you
took the host-venv alternative above, keep that venv active for the rest of this guide;
§6's CSV upload always happens via `curl` from your host either way.

## 5. Seed reference pricing data

**Do this before touching cost or optimization endpoints — it's the #1 cause of
"everything returns an error" on a fresh setup.** The pricing engine has no hardcoded
rates; without this step, every `calculate_cost()` call raises `PricingNotFoundError`.

`app/pricing/seed_data.py`'s CLI (`python -m app.pricing.seed_data`) seeds under
`provider="aws"` by default — but the usage data you're about to upload in §6 gets
tagged `provider="synthetic"` by the ingestion endpoint's own default (the standard CSV
schema has no `provider` column at all, so there's no CLI flag to override this on the
generator side). Seed under the provider that will actually match, using a one-line
Python snippet instead of the bare CLI command:

**If you started the backend via Docker Compose:**
```bash
docker compose exec backend python3 -c "
from app.models.base import SessionLocal
from app.pricing.seed_data import seed_pricing
db = SessionLocal()
inserted = seed_pricing(db, provider='synthetic')
print(f'Inserted {inserted} pricing rows under provider=synthetic')
db.close()
"
```

**If you're running the backend on your host:**
```bash
cd backend
source .venv/bin/activate
python3 -c "
from app.models.base import SessionLocal
from app.pricing.seed_data import seed_pricing
db = SessionLocal()
inserted = seed_pricing(db, provider='synthetic')
print(f'Inserted {inserted} pricing rows under provider=synthetic')
db.close()
"
```

This inserts the same ~112 reference rate rows across 4 regions (`us-east-1`,
`us-west-2`, `eu-west-1`, `ap-southeast-1`), just tagged `provider="synthetic"` instead
of the module's own default. It's idempotent — running it twice does nothing the second
time (see §9, pitfall 1, for why this provider match matters and what it looks like when
it doesn't).

## 6. Generate and load sample usage data

**If your backend is running via Docker Compose** (the container has no volume mount
for `datasets/`, so copy the file out afterward — note the path is `/datasets/...` at
the container's filesystem root, **not** `/app/datasets/...`: the generator locates the
output directory relative to its own source file, and the container's build only copies
`backend/`'s contents into `/app`, one directory level shallower than on the host, so
the same relative-path math lands one level higher inside the container):
```bash
docker compose exec backend python -m app.services.synthetic_data --days 120 --format csv
docker compose cp backend:/datasets/synthetic_usage.csv ./datasets/synthetic_usage.csv
```

**If you're running the backend on your host:**
```bash
cd backend
source .venv/bin/activate   # if not already active
python -m app.services.synthetic_data --days 120 --format csv
cd ..
```

Either way this writes `datasets/synthetic_usage.csv` — 120 days of hourly usage across
16 resources (4 each of Compute/Database/Object Storage/Serverless), with realistic
seasonality, growth, idle periods, and anomalies baked in. 120 days comfortably clears
the forecasting engine's minimum of 45 days of history per (resource, usage_type); if
you regenerate with fewer days than that, forecasting will fail (§9, pitfall 3). The
generator has no `--provider` flag and the CSV schema has no `provider` column — every
row ingested from it gets tagged `provider="synthetic"` by the ingestion endpoint's own
default, which is exactly what §5 seeded pricing under.

Load it into the running backend (run from the repo root, i.e. `cloudpilot/`):

```bash
curl -F "file=@datasets/synthetic_usage.csv;type=text/csv" \
  http://localhost:8000/api/data/upload
```

Expect a response like:

```json
{"rows_received": 46080, "rows_valid": 46080, "rows_failed": 0,
 "usage_records_inserted": 299520, "resources_created": 16, "resources_updated": 0,
 "errors": []}
```

`rows_failed` should be `0` and `errors` should be `[]`. If `resources_created` is `0`
on a fresh database, something's wrong — check the response body's `errors` list, which
names the exact row and reason for every rejected row.

Pick one resource to use for the rest of this walkthrough — this guide uses
`compute-i-0001`:

```bash
curl "http://localhost:8000/api/resources?provider=synthetic" | python3 -m json.tool
```

## 7. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open the printed URL (`http://localhost:5173` unless something else is already using
that port, in which case Vite prints the next free one — check the terminal output, it
will **not** always be 5173). The sidebar's **Provider** field (bottom-left) defaults to
`aws` — change it to `synthetic` to match what you seeded pricing and uploaded data
under in §5–6, or none of the resources or costs below will show up.

## 8. The exact sequence: raw data → validated, critic-approved optimization

Everything below can be done either through the UI or via `curl`; both are given so you
can verify the UI is doing what you expect.

### 8a. Forecast usage

**UI:** Forecast page → select `compute-i-0001` → usage type `requests` → horizon
`week` → **Generate forecast**. Expect a chart with history, a forecast tail, and a
confidence band; the header shows which model won (`xgboost` or
`baseline_seasonal_naive`) and its MAE/RMSE.

**API:**
```bash
curl -X POST http://localhost:8000/api/forecast \
  -H "Content-Type: application/json" \
  -d '{"resource_id":"compute-i-0001","usage_type":"requests","horizon":"week"}'
```
Look for `"status":"completed"` and a non-null `metrics` object with both models'
MAE/RMSE/MAPE. Note the returned `"id"` — `GET /api/forecast/{id}` re-fetches it later.

### 8b. Predict next period's bill

**UI:** Dashboard page → select the same resource → **Generate next-month prediction**.

**API:**
```bash
curl -X POST http://localhost:8000/api/cost/predict \
  -H "Content-Type: application/json" \
  -d '{"provider":"synthetic","horizon":"week","resource_id":"compute-i-0001"}'
```
Expect `"total_cost"` > 0 and a non-empty `"line_items"` array, each with
`predicted_cost`, `lower_bound`, `upper_bound`. A `"skipped"` array entry here (rather
than an error) means one usage type on this resource couldn't be forecast or priced —
that's the app being honest, not a bug, as long as it's not *every* line item.

### 8c. Run the deterministic optimizer (no LLM, no critic)

**UI:** What-If Simulator page (or Optimization page — see 8d for the version with the
LLM/critic layer) → set Budget/Max latency/Min availability → **Optimize**.

**API:**
```bash
curl -X POST http://localhost:8000/api/optimization/run \
  -H "Content-Type: application/json" \
  -d '{"provider":"synthetic","resource_id":"compute-i-0001","horizon":"week","max_latency_ms":100,"min_availability":0.99,"budget":1000}'
```
Expect exactly 6 `"scenarios"` (`current`, `autoscaling`, `reserved`, `right_sizing`,
`storage_optimization`, `combined`), a `"chosen_scenario_id"`, and `"fully_feasible"`.
**This endpoint has no critic** — `fully_feasible` is purely the OR-Tools/constraint
verdict. For a critic-reviewed recommendation, use 8d.

### 8d. Run the full agent pipeline and get a critic-approved plan

This is the one that answers "is this recommendation actually trustworthy" — it runs
Planner → Forecast → Cost Analysis → Optimization → **Critic** → Report.

**UI (easiest):** Optimization page → fill in the same constraints → **Optimize**. Watch
the "Live progress" step tracker and the live tool-call log update in real time. When it
finishes, the **Confidence** card says either "High" (critic approved) or "Low —
rejected" with the specific rejection reason quoted underneath. The "Why this
recommendation" section cites the RAG knowledge-base source(s) used.

**API:** `POST /api/agent/run` is a Server-Sent Events stream, not a plain JSON
response — each line is one completed LangGraph node's partial state update, so you
need to accumulate them to see the final verdict. This script does that and prints
exactly what the UI shows:

```bash
python3 - <<'EOF'
import json, urllib.request

body = json.dumps({
    "user_query": "Optimize cost for compute-i-0001",
    "provider": "synthetic",
    "resource_id": "compute-i-0001",
    "usage_type": "requests",
    "horizon": "week",
    "max_latency_ms": 100,
    "min_availability": 0.99,
    "budget": 1000,
}).encode()

req = urllib.request.Request(
    "http://localhost:8000/api/agent/run", data=body,
    headers={"Content-Type": "application/json"},
)

state = {}
with urllib.request.urlopen(req) as resp:
    for line in resp:
        line = line.decode().strip()
        if not line.startswith("data:"):
            continue
        chunk = json.loads(line[5:].strip())
        if "_meta" in chunk:
            continue
        for node_update in chunk.values():
            state.update(node_update)

opt = state.get("optimization_data", {})
print("approved:       ", opt.get("approved"))
print("candidate plan: ", (opt.get("candidate") or {}).get("name"))
print("rejection note: ", state.get("critic_verdict", {}).get("rejection_reason"))
print()
print("--- final report ---")
print(state.get("final_report"))
EOF
```

**Important nuance:** the critic's verdict is a graph-state field, not a logged tool
call — it will **never** show up in `GET /api/agent/events` or the Agent Trace page's
tool-call list. The script above (or the frontend, which does the same accumulation) is
the only way to see `approved`/`rejection_reason` directly; `GET /api/agent-trace/{id}`
and the Agent Trace page show you every *tool call* that fed into that verdict, which is
useful for auditing but won't itself say "approved: true".

If rejected, the pipeline retries up to 3 candidates total before giving up and
reporting honestly that no scenario passed — that is correct, documented behavior
(a deliberately impossible budget will always end this way), not a bug to work around.

## 9. Diagnosing misconfiguration

`GET /api/settings` is your first stop for anything that feels off:

```bash
curl http://localhost:8000/api/settings | python3 -m json.tool
```

```json
{"app_name": "CloudPilot", "gemini_model": "gemini-2.5-flash",
 "gemini_configured": true, "database_connected": true}
```

- **`database_connected: false`** → the backend can reach its process but not its
  Postgres. Check `DATABASE_URL` in whichever `.env` the running backend actually
  loaded (§3), and that migrations ran (`alembic current` inside `backend/` should show
  a real revision id, not blank).
- **`gemini_configured: true` does NOT mean the key works** — it only checks the env var
  is non-empty. `.env.example` ships with the literal placeholder
  `GEMINI_API_KEY=your_api_key`, which is non-empty and therefore reports `true` while
  being completely invalid. The real tell: run an agent pipeline (§8d) and check whether
  `state["plan"]["reasoning"]` is the exact literal string
  `"Default plan (LLM unavailable): run every analysis step."` — if so, Gemini is not
  actually being called, key or no key. A genuinely bad key fails fast (no retries — an
  auth error isn't in the retryable set) and every narrative silently falls back to a
  template; the numbers are still correct, but the prose reads like boilerplate instead
  of natural language.

### Pitfall 1 — provider mismatch (the most common silent failure)

Every pricing lookup and usage query filters on an exact string match: the `provider`
you pass to `/cost/*` and `/optimization/*` must equal both the `provider` column on the
`pricing` rows (set by whoever ran `seed_data.py`) **and** on the `usage_records` rows
(set by whoever ingested them). These are two independent defaults that don't agree out
of the box:

- `app.pricing.seed_data.PROVIDER` (used by the bare `python -m app.pricing.seed_data`
  CLI) defaults to `"aws"`.
- `app.services.data_ingestion.UsageRowIngest.provider` defaults to `"synthetic"` — the
  standard CSV schema from the generator (`app/services/synthetic_data.py`) has no
  `provider` column at all and the generator has no flag to add one, so every upload
  through `/api/data/upload` gets tagged `provider="synthetic"` unless you add a
  `"provider"` field to each JSON record yourself.

These disagree out of the box, which is exactly why §5 above seeds pricing with
`seed_pricing(db, provider='synthetic')` instead of running the bare CLI command —
running `python -m app.pricing.seed_data` unmodified would seed `"aws"` pricing against
`"synthetic"` usage data, and every cost/optimization call would then fail with a
`PricingNotFoundError`-shaped 422, e.g.
`No pricing found for provider='synthetic' region='us-west-2' ...`, even though the
resource clearly exists. If you ever see that error, a provider mismatch — not a broken
pricing engine — is the first thing to check.

### Pitfall 2 — DB not migrated

Symptom: `sqlalchemy.exc.ProgrammingError: relation "usage_records" does not exist` (or
similar) on the very first API call. Fix: `alembic upgrade head` from `backend/` (the
Docker image does this automatically in its `CMD`; a host-run backend does not).
Confirm with `alembic current` — it should print a revision hash, not nothing.

### Pitfall 3 — insufficient history for forecasting

Symptom: `POST /api/forecast` returns 404/422 with a message like `Need at least 45 days
of history for resource=... usage_type=...` or `No usage_records found for resource=...`.
Fix: regenerate the synthetic dataset with `--days` ≥ 45 (the default is 120, so this
only bites if you've customized it or are ingesting your own real data with a shorter
window), or pick a usage_type the resource actually has data for
(`GET /api/usage/history?resource_id=...&usage_type=...` to check first).

### Pitfall 4 — stale/partial day at the edges of ingestion

If you ingest data mid-day (a real cron job doing incremental uploads, not this guide's
one-shot CSV load), the first and last calendar day of history can have fewer than 24
hourly rows. The forecasting pipeline already trims these automatically
(`app/forecasting/data.py::load_daily_series`) — but if you're inspecting raw
`usage_records` counts yourself and a day's total looks low, that's very likely why, not
missing data.

### Pitfall 5 — port 5173/8000 already in use

Vite auto-selects the next free port and prints it — read the terminal output, don't
assume 5173. For the backend, `uvicorn`/`docker compose` will fail loudly if 8000 is
taken (`[Errno 48] Address already in use`); free it or change the port mapping in
`docker-compose.yml` and `frontend/.env`'s `VITE_API_BASE_URL` to match.

### Pitfall 6 — pytest-cov not installed

`pytest -q --cov=app ...` fails with `unrecognized arguments: --cov` if you only ran
`pip install -r requirements.txt` — `pytest-cov` isn't a pinned dependency (coverage
measurement is a dev-time convenience, not a runtime need). Fix: `pip install
pytest-cov` once, or just run plain `pytest` without the coverage flags.

## 10. Running the test suite

```bash
docker compose up -d postgres    # tests need a real Postgres, same as the app
cd backend
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.pricing.seed_data  # most tests assume reference pricing already exists
pytest                            # 215 tests, no GEMINI_API_KEY required — every
                                   # LLM-touching test either mocks Gemini or verifies
                                   # the deterministic fallback path
```

For coverage: `pip install pytest-cov && pytest -q --cov=app --cov-report=term-missing`
(97% as of Phase 11 — see `docs/definition-of-done.md` for what the remaining 3% is).

Tests create and tear down their own uniquely-named resources per test (`uuid`-suffixed
external ids), so it's safe to run the suite against a Postgres that already has the
sample dataset from §6 loaded — nothing here will collide with or delete it.
