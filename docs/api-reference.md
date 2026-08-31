# API Reference

All routes are prefixed with `/api`. The backend is FastAPI, so interactive docs (via
Swagger UI) are also available at `http://localhost:8000/docs` whenever the backend is
running.

## Table of contents

- [Health](#health)
- [Data ingestion](#data-ingestion)
- [Resources & usage](#resources--usage)
- [Forecasting](#forecasting)
- [Cost](#cost)
- [Optimization](#optimization)
- [Agents](#agents)
- [Settings](#settings)

## Health

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness check. Returns `{"status": "ok"}`. |

## Data ingestion

| Method & path | Purpose |
|---|---|
| `POST /data/upload` | Upload a CSV/JSON usage file (multipart field `file`), validate, and persist to `usage_records`. Returns row counts and any per-row validation errors. |

## Resources & usage

| Method & path | Purpose |
|---|---|
| `GET /resources` | List known resources. Optional `provider`, `service` query filters. |
| `GET /usage/history` | Raw usage history for one `resource_id` + `usage_type`. |

## Forecasting

| Method & path | Purpose |
|---|---|
| `POST /forecast` | Run the forecasting pipeline. Body: `resource_id`, `usage_type`, `horizon` (`day`\|`week`\|`month`). |
| `GET /forecast/{id}` | Fetch a stored forecast, backfilling `actual_usage` for any predicted date that has since elapsed. |
| `GET /forecast/accuracy` | MAE/RMSE/MAPE across backfilled actual-vs-predicted points. Optional `resource_id` filter. |

## Cost

| Method & path | Purpose |
|---|---|
| `POST /cost/predict` | Forecast + price the next billing period. Body: `provider`, `horizon`, `pricing_model` (default `on_demand`), optional `commitment_term_months`, and `resource_id` or `service` (or neither, for every resource). |
| `GET /cost/breakdown` | Reread a stored bill. Optional `forecast_id` (defaults to the most recent). |
| `GET /cost/current` | Current-period cost, priced from actual (not forecasted) usage. |
| `GET /cost/drivers` | Ranked cost drivers. `source=current\|forecasted`; `horizon` required when `source=forecasted`. |

## Optimization

| Method & path | Purpose |
|---|---|
| `POST /optimization/run` | Run all 6 scenarios through the OR-Tools solver, persist, and pick a winner. Body: `provider`, `resource_id`, `horizon`, `max_latency_ms`, `min_availability`, `budget`. No LLM, no critic — see `POST /agent/run` for the critic-reviewed version. |
| `GET /optimization/{id}` | Fetch a stored optimization run. |
| `GET /optimization/latest` | Most recent run. Optional `resource_id` filter. |

## Agents

| Method & path | Purpose |
|---|---|
| `POST /agent/run` | Server-Sent Events. Runs the full LangGraph pipeline (planner → forecast → cost analysis → optimization ↔ critic → report), streaming one event per completed node. Body: same fields as `/optimization/run` plus `user_query` and `usage_type`. |
| `GET /agent/events` | One-shot fetch of all `agent_events` rows for a `session_id`. |
| `GET /agent/sessions` | Recent agent session ids, for a session picker UI. |
| `GET /agent-trace/{session_id}` | Server-Sent Events. Live tail of `agent_events` for one session — finer-grained than `/agent/run`'s per-node stream, since it surfaces every individual tool call the instant it's committed. |

## Settings

| Method & path | Purpose |
|---|---|
| `GET /settings` | System status: `gemini_model`, `gemini_configured` (env var is non-empty — not a validity check), `database_connected`, `usd_to_inr_rate`. |

## Notes on the two optimization paths

`POST /optimization/run` and `POST /agent/run` both run the same 6-scenario OR-Tools
solve, but only `/agent/run` adds the Critic's independent validation pass and an
LLM-narrated (or template-narrated, without a Gemini key) explanation. If you need a
programmatic "is this recommendation trustworthy" verdict, use `/agent/run` and read
`optimization_data.approved` from the accumulated stream state — that field is not a
logged tool call, so it never appears via `/agent/events`. See
[`running-locally.md`](running-locally.md#8d-run-the-full-agent-pipeline-and-get-a-critic-approved-plan)
for a worked example.
