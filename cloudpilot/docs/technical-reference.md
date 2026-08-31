# Technical Reference

Module-by-module implementation notes: what each package does, why it's built the way
it is, and what's been verified. The [README](../README.md) covers setup and usage; this
doc is for understanding or extending the system itself.

## Table of contents

- [Synthetic dataset](#synthetic-dataset)
- [Data ingestion](#data-ingestion)
- [Pricing engine](#pricing-engine)
- [Forecasting](#forecasting)
- [Cost prediction](#cost-prediction-forecast--pricing-combined)
- [Optimization (OR-Tools)](#optimization-or-tools)
- [Agents (LangGraph + Gemini)](#agents-langgraph--gemini)
- [RAG knowledge base](#rag-knowledge-base)
- [Live agent trace streaming](#live-agent-trace-streaming)
- [Currency (display only)](#currency-display-only)
- [Frontend pages](#frontend-pages)

## Synthetic dataset

`app/services/synthetic_data.py` generates a synthetic usage/billing time series across
four service categories (Compute, Database, Object Storage, Serverless), with daily and
weekly seasonality, per-resource growth trends, idle periods, traffic spikes, and sparse
anomalies:

```bash
cd backend
python -m app.services.synthetic_data --days 120 --format csv
```

Output is written to `datasets/synthetic_usage.csv` by default. Columns: `timestamp,
service, resource, region, cpu_utilization, memory_utilization, requests, storage_gb,
network_gb, hours_used, current_cost`.

The per-service unit rates used to derive `current_cost` in this generator are
illustrative and only used to keep the synthetic dataset internally consistent — they
are independent of the platform's real pricing engine (`app/pricing/`).

## Data ingestion

`POST /api/data/upload` accepts a CSV or JSON file matching the schema above (multipart
form field `file`), validates each row, and stores it into `usage_records` — one row per
metric present per source row (plus one `cost` row when `current_cost` is given).
Invalid rows are skipped and reported back rather than failing the whole upload.

## Pricing engine

`app/pricing/` prices usage for the four services using data from the `pricing` table —
never hardcoded rates.

- **`repository.py`** — the only module that queries `pricing`. Rows are versioned by
  `effective_date`; the newest applicable version for a given
  (provider, region, resource_type, sku, pricing_model[, commitment_term]) is used.
  Graduated/tiered SKUs are multiple rows sharing one `effective_date` with
  non-overlapping `[tier_min_unit, tier_max_unit)` ranges.
- **`calculator.py`** — `calculate_cost(request, db)`, typed and validated via Pydantic
  (`CostCalculationRequest` / `CostCalculationResult`). Supports `on_demand` and
  `reserved` (with a commitment term) pricing models, and two ways of supplying the
  billable quantity: `flat` (a single pre-resolved number) or `autoscaling` (a series of
  `(quantity, duration_hours)` samples — e.g. an autoscaling group's instance count over
  time — that the engine time-weights into one quantity). Raises `PricingNotFoundError`
  rather than guessing when no matching rate exists.
- **`aggregation.py`** — pure functions over a list of results: `aggregate_total`,
  `aggregate_by_service`, `aggregate_by_resource`, `aggregate_by_usage_unit`.
- **`skus.py`** — the catalog mapping an ingested usage metric (e.g. `hours_used`) to a
  SKU/unit per service. `cpu_utilization`/`memory_utilization` are deliberately excluded
  — no cloud bills raw utilization; they're rightsizing signals, not billable
  quantities. Compute's `requests`/`storage_gb` and Object Storage's `hours_used` are
  also unmapped by design (incidental/non-billed metrics in this schema) —
  `app/services/cost_calculation.py` reports these as `skipped` with a reason rather
  than pricing them or dropping them silently.
- **`seed_data.py`** — illustrative reference rates (`provider="aws"` by default) across
  4 regions, covering on-demand + reserved compute/database rates and tiered
  storage/network-egress pricing. Run `python -m app.pricing.seed_data` to load them
  (idempotent).

Adding a real provider, or a second provider, is purely a data change — insert more
`pricing` rows with a different `provider` value. Nothing in `calculator.py` or
`repository.py` branches on provider.

`app/services/cost_calculation.py` bridges ingested `usage_records` to the engine:
`price_usage_records(db, provider=...)` groups raw rows by (resource, usage_type), turns
flow metrics (hours/requests/network) into sums and gauge metrics (storage) into
time-weighted GB-hours, prices each group, and returns line items plus anything skipped.

## Forecasting

`app/forecasting/` forecasts a `usage_records` metric (`requests`, `hours_used`,
`storage_gb`, or `network_gb`) for one resource over the next day/week/month. Which
real-world quantity that means (e.g. "compute hours" vs "DB usage") falls out of which
resource you ask about — `hours_used` on a Compute resource and `hours_used` on a
Database resource are both forecast the same way.

- **`data.py`** — aggregates hourly `usage_records` into a daily series (sum for flow
  metrics, mean for the `storage_gb` gauge), trimming any leading/trailing partial day
  (ingestion mid-day, or a day that hasn't fully elapsed yet) so the model never trains
  on an artificially low boundary day.
- **`baseline.py`** — a seasonal-naive model (day *t* = day *t*−7), recursively extended.
- **`ml_model.py`** — an XGBoost regressor on lag(1/7/14) + rolling-mean/std + calendar
  features, applied recursively for multi-step forecasts.
- **`engine.py`** — chronologically splits the series (last ~7–14 days held out), fits
  both models on the training portion, scores each on the real held-out data via
  MAE/RMSE/MAPE (`evaluation.py` — always computed from actual vs. predicted arrays,
  never a stored/fabricated number), picks the lower-RMSE model, refits it on the full
  series, and forecasts forward. 90% confidence intervals come from the chosen model's
  held-out residual std, widening with `sqrt(horizon step)`; they're omitted (`null`)
  when residual std is ~0 (a perfectly deterministic series has no meaningful band).
- Needs ≥45 days of history per (resource, usage_type); raises a clear error otherwise
  rather than forecasting off too little data.

`POST /api/forecast` (body: `resource_id`, `usage_type`, `horizon`: `day`/`week`/`month`)
runs this pipeline and stores the run in `forecasts` (model, metrics for both models,
training window) with its points in `cost_predictions` (`predicted_usage`,
`lower_bound`/`upper_bound`). `GET /api/forecast/{id}` retrieves it — and first backfills
`actual_usage` for any predicted date that has since fully elapsed and been ingested
(comparing full day vs. full day only), closing the loop between a forecast and what
actually happened.

## Cost prediction (forecast + pricing combined)

`app/services/cost_prediction.py` combines forecasting and pricing into a predicted
next-period bill. For each resource in scope, and each usage_type that resource's
service has a SKU for (via `app.pricing.skus.SKU_CATALOG`, so forecasting and pricing
never disagree about what's billable):

1. Forecast that (resource, usage_type) over the requested horizon.
2. Sum the horizon's daily point estimates into one billing-period quantity, and — when
   the forecast has bounds — separately sum the daily lower/upper bounds into a
   period-total lower/upper quantity. (Bounds are summed rather than combined via
   sqrt-sum-of-squares: daily cloud usage is autocorrelated within a billing period, so
   treating each day's error as independent would understate total uncertainty.)
3. Price the point, lower, and upper quantities through `calculate_cost()` — three real
   pricing-engine calls, not a linear scaling of the point cost — so a forecast that
   crosses a tier boundary still prices correctly at each bound.

Line items are aggregated with the pricing engine's own `aggregate_by_service` /
`aggregate_by_resource` / `aggregate_by_usage_unit` / `aggregate_total` — no separate
aggregation logic to keep in sync. A resource/usage_type that can't be forecast (too
little history) or priced (no matching rate) is reported in `skipped` rather than
silently dropped or estimated.

- `POST /api/cost/predict` — body: `provider`, `horizon`, `pricing_model` (default
  `on_demand`), optional `commitment_term_months`, and either `resource_id` (single
  resource) or `service` (all resources of that service) or neither (every resource for
  that provider). Runs the pipeline above and returns + stores the bill.
- `GET /api/cost/breakdown?forecast_id=...` — rereads a stored bill from
  `cost_predictions`/`forecasts` (defaults to the most recently generated one).

No LLM involved — this is pure forecasting + pricing composition.

## Optimization (OR-Tools)

`app/optimization/` answers: minimize cost subject to capacity ≥ predicted demand,
latency ≤ max_latency, availability ≥ min_availability, and cost ≤ budget — for one
resource, across 6 scenarios.

- **`generate_scenarios()`** returns the fixed, service-agnostic scenario set:
  `current`, `autoscaling`, `reserved`, `right_sizing`, `storage_optimization`,
  `combined`. Each spec just says which decision axis is "open"; a service that has no
  concept of an axis (e.g. Object Storage has no instance tier) simply no-ops it rather
  than faking a difference.
- **`simulate_scenario()`** prices one scenario for one resource:
  - **Compute/Database** (instance-fleet sizing): tier (small/medium/large) and pricing
    model (on-demand/reserved 12mo/36mo) are enumerated; for each combination,
    `app.optimization.solver.solve_instance_schedule` — a real OR-Tools CP-SAT model —
    finds the minimum-cost daily instance-count schedule that meets capacity (constant
    across days unless the scenario allows autoscaling, in which case a day-to-day
    change-rate limit keeps it realistic). Latency and availability targets are folded
    into capacity/instance-count *lower bounds* before solving (see `heuristics.py`), so
    the schedule satisfies them by construction; only budget is a direct solver
    constraint, and it's re-solved without it (flagged as violated) if infeasible rather
    than failing outright.
  - **Object Storage** (storage tier only) / **Serverless** (memory tier only): small
    enumerations with no scheduling sub-problem, so no solver call — picking the
    cheapest option that satisfies latency/availability, falling back to cheapest
    overall (violation flagged) only if none do.
  - Every candidate's cost comes from the real `calculate_cost()` — tiers only ever
    scale the quantity or select the pricing model fed into it (documented in
    `catalog.py`), never invent a price of their own.
- **`heuristics.py`** — documented, deterministic (no ML, no LLM) latency/availability
  formulas: latency blows up as utilization approaches capacity
  (`base / (1 - utilization)`); availability follows an N-instance independent-failure
  redundancy model (`1 - failure_rate ** N`). Both are invertible, which is what lets
  latency/availability become linear bounds before solving.
- **`check_constraints()`** compares a simulated scenario's actual capacity/latency/
  availability/cost against the request's targets and flags each independently — it
  does no solving or pricing itself.

`app/services/optimization_service.py` orchestrates a run: forecasts demand once per
resource (reused across all 6 scenarios so they're compared on identical data),
simulates every scenario, persists one `scenarios` row + 4 `constraints` rows per
scenario, and picks the lowest-cost scenario among those that satisfy every constraint
— or, if none do, the lowest-cost scenario overall, explicitly marked
`fully_feasible: false` rather than silently presented as a clean win.

No LLM anywhere in this layer's math — scenario selection is `min()` over computed
numbers, not a model's judgment call.

## Agents (LangGraph + Gemini)

`app/tools/` wraps every deterministic module above as a typed, validated, logged
callable — this is the only way an agent is allowed to get a number:

- `get_usage_history`, `get_current_resources`
- `forecast_usage`
- `get_pricing`, `calculate_current_cost`, `calculate_forecasted_cost`
- `identify_cost_drivers` — generic (label, cost) ranking utility
  (`app/services/cost_drivers.py`) over either current or forecasted line items
- `generate_scenarios`, `simulate_scenario`, `check_constraints`, `compare_scenarios`
- `search_optimization_knowledge` — semantic search over a markdown knowledge base via
  local embeddings + FAISS (see [RAG knowledge base](#rag-knowledge-base)). No external
  API call, no LLM involved in retrieval.

Every tool call — success or error — is logged to `agent_events` via
`app/tools/base.py::run_tool()`: agent name, tool name, typed input, typed output (with
a `status` field), latency, and timestamp. This is the audit trail behind the
platform's core rule: agents call tools for every number; the LLM only narrates or
plans. See [`agent-workflow.md`](agent-workflow.md) for the full pipeline diagram and
node-by-node breakdown.

**Gemini integration** (`app/agents/llm_client.py`): uses the `google-genai` SDK
(`genai.Client(api_key=...)`, model from `GEMINI_MODEL`). Retries transient failures
(HTTP 429/500/502/503/504, or rate-limit/timeout messages) with exponential backoff up
to 4 attempts; non-retryable errors (e.g. bad request) fail immediately. Structured
output (the Planner's `Plan`) uses Gemini's JSON mode with a Pydantic `response_schema`,
falling back to manual `json.loads` if the SDK's `.parsed` field isn't populated. If no
`GEMINI_API_KEY` is configured, the key is invalid, or every retry is exhausted, every
agent falls back to a deterministic template that cites the same already-computed
numbers in plain text instead of LLM prose — the pipeline degrades gracefully rather
than failing. See [`definition-of-done.md`](definition-of-done.md) for what's been
verified about this path.

This retry/backoff logic is verified with mocked Gemini responses (rate-limit-then-
succeed, non-retryable-fails-immediately, retries-exhausted). The rest of the agent
layer — tool orchestration, state flow, fallback narratives, full end-to-end pipeline —
is verified for real (no mocking) against a live Postgres and the actual synthetic
dataset: every agent correctly falls back, and the final report's numbers trace exactly
to the logged `agent_events` tool calls (e.g. a real run against a resource produced
"current cost is $1712.46 ... top cost driver is objstorage-network-egress at 84.8%" —
both pulled verbatim from `calculate_current_cost`/`identify_cost_drivers`, not
generated text).

## RAG knowledge base

Five markdown guides — right-sizing, autoscaling, storage optimization, reserved
capacity, and utilization monitoring best practices (`app/rag/documents/*.md`) —
general FinOps/cloud-cost-optimization guidance written for this project, not
fabricated statistics attributed to fake studies. Any illustrative numbers in them are
framed as typical/common guidance, never as a specific measured result.

- **`loader.py`** — splits each doc into one chunk per `##` section (24 chunks total
  across the 5 docs), tagged with the doc title and section heading as its citation.
- **`embeddings.py`** — local embeddings via `sentence-transformers` (`all-MiniLM-L6-v2`,
  downloaded once and cached, no per-query network call, no `GEMINI_API_KEY` involved)
  — deliberately separate from the Gemini-backed agents, since retrieval here is a
  deterministic vector search, not an LLM call.
- **`index.py`** — a FAISS flat inner-product index (cosine similarity, since embeddings
  are L2-normalized) built once per process — the doc set is small enough (~24 chunks)
  that rebuilding it costs a couple of seconds and needs no disk persistence.
- **`retriever.search_knowledge(query, top_k)`** — the real implementation behind the
  `search_optimization_knowledge` tool.

Verified: each of 5 test queries targeting a different topic retrieves chunks from the
correct source document with sensible similarity scores (0.5–0.8) — genuine semantic
search, not keyword matching. A live end-to-end run under a deliberately impossible
budget walked all 3 retry attempts with real, distinct rejection reasons per candidate
before honestly reporting no scenario passed validation, while still citing sources for
the last-tried candidate.

## Live agent trace streaming

`GET /api/agent-trace/{session_id}` (`app/api/agent_trace.py`) tails the `agent_events`
table for one session: this process has no message broker, so "live" is short-interval
polling (300ms) of the row a writer just committed — simple, correct for a
single-process app, and cheap at this event volume. Connecting immediately drains
whatever rows already exist (a completed session's full history arrives in one fast
burst), then keeps polling for more; if none arrive for ~30s (`MAX_IDLE_POLLS`) it sends
an `idle_timeout` event and closes.

The frontend (`useAgentTraceStream`) uses a manual `fetch` + `ReadableStream` reader
rather than the native `EventSource` API deliberately: `EventSource` auto-reconnects on
any connection close, including the server's own idle-timeout close, which would
silently restart the stream (and re-drain full history) forever. A plain reader treats
stream-end as done and stops, matching what "watching one run" should actually do.

Both the Optimization page (a live tool-call log beneath the step tracker) and the
Agent Trace page (its main detail view) subscribe to this same endpoint. The polling
parameters are injectable (`poll_interval_seconds`, `max_idle_polls`) so tests don't
wait out a real 30-second timeout; a dedicated test spins up a background thread that
inserts a new `agent_events` row on a separate DB connection mid-stream and asserts the
generator yields it — proving the tail genuinely reacts to new commits, not just
replaying what existed at connection time.

## Currency (display only)

Every persisted and computed monetary value in this system — `pricing` rates,
`forecasts`/`cost_predictions`, `optimization_runs`/`scenarios`, and every number an
agent tool returns or logs to `agent_events` — is USD, always. `app/services/
currency.py` is the one place a USD→INR rate exists (`USD_TO_INR_RATE` env var, default
`83.0`), exposed only via `GET /api/settings`'s `usd_to_inr_rate` field — nothing else
in the backend imports it.

- `tests/test_currency_boundary.py` enforces this mechanically: it parses every file
  under `app/forecasting`, `app/pricing`, `app/optimization`, `app/agents`, `app/tools`,
  `app/models`, and `app/services` (besides `currency.py` itself), and fails if any of
  them import it.
- `tests/test_currency_invariants.py` proves it behaviorally, by setting the rate to an
  absurd value and asserting `calculate_cost()`, `predict_bill()`, and
  `run_optimization()` all return identical results either way.

The frontend fetches that rate once (`CurrencyContext`, on mount) and a sidebar toggle
(default **INR**, persisted in `localStorage`) reformats every already-fetched USD
figure client-side — toggling never re-queries the backend. Agent-generated report text
is left untouched by the toggle: narratives are USD prose from the tool layer, same as
everywhere else in this system, not a value the presentation layer reformats.

## Frontend pages

A sidebar-nav dashboard (not chat-style), all fetching real data from the backend
above — no mock data anywhere:

- **Dashboard** — current cost (all-time, on-demand), predicted cost (on demand, via
  `POST /api/cost/predict`), optimized cost + savings (from the latest optimization run
  for the selected resource), and forecast accuracy (MAE/RMSE/MAPE across backfilled
  actuals) — with an honest empty state rather than a fabricated number when none exist
  yet.
- **Forecast** — history + forecast + confidence interval + backfilled actual-vs-
  predicted on one chart, plus small per-metric charts for the resource's other usage
  types.
- **Cost Analysis** — cost breakdown by usage-unit (SKU) and ranked top cost drivers.
- **Optimization** — the budget/latency/availability/horizon form, an Optimize button
  that streams live step progress via Server-Sent Events (`POST /api/agent/run`), a
  live tool-call log sourced from the agent-trace stream, and the result: plan,
  cost/savings, availability/latency, confidence (critic approval + forecast
  uncertainty), the why-explanation with cited RAG sources, and the full scenario
  comparison table.
- **What-If Simulator** — adjust budget/latency/availability/horizon and re-run the real
  solver (`POST /api/optimization/run`, no agent layer, no LLM) to see how the 6
  scenarios and the winner change; each simulation is a real, persisted optimization
  run.
- **Agent Trace** — every tool call any agent made (agent, tool, input, output, latency,
  status), browsable by session, streamed live — a completed session's events drain in
  immediately, an in-progress session's events append in real time.
- **Settings** — real system status (Gemini model/configured, DB connectivity, current
  USD→INR rate) and the CSV/JSON usage upload widget.

The shared scenario comparison table (Plan/Cost/Savings/Capacity/Latency/Availability/
Risk) is used by both Optimization and What-If — Risk is derived client-side from
`constraints_satisfied` (Low if all four constraints pass, High with a tooltip listing
which failed otherwise), not a separately computed number.
