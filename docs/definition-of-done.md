# Definition of Done

A rule-by-rule audit of the Phase 0 non-negotiables against what's actually in the
codebase today (Phase 11), verified by grep/inspection in this pass — not carried
forward from memory of earlier phases.

## Core separation rule

> ML models forecast, pricing engine prices, OR-Tools optimizes, LLM agents only
> plan/reason/explain — never compute numbers.

| Check | Status | Evidence |
|---|---|---|
| Forecasting has no LLM import | ✅ Done | `app/forecasting/*.py` — grepped, zero references to `app.agents` or `genai` |
| Pricing has no LLM import | ✅ Done | `app/pricing/*.py` — same |
| Optimization has no LLM import | ✅ Done | `app/optimization/*.py` — same |
| Agents obtain every number via a logged tool call | ✅ Done | `app/tools/base.py::run_tool()` is the only path from an agent node to a number; every call logged to `agent_events` (see `docs/architecture.md`) |
| Every agent's system prompt explicitly forbids inventing numbers | ✅ Done | Verified by reading all 5 `*_SYSTEM_INSTRUCTION` strings in `app/agents/*.py` — each says so explicitly |
| The "never invent numbers" guarantee is checked at runtime against live Gemini output | ⚠️ **Gap** | No real `GEMINI_API_KEY` has been available in this project's environment through any of the 11 phases. The guarantee rests on prompt instruction + the deterministic template fallback (verified working), not on a runtime check that a live Gemini response's narrative numbers match the tool output it was given. Flagged, not fixed — fixing it means writing a number-extraction/diff check in `app/agents/llm_client.py` or per-agent, which is a real feature addition, not a test-gap fix. |

## Stack

| Requirement | Status | Evidence |
|---|---|---|
| React + TS + Vite + Tailwind + Recharts frontend | ✅ Done | `frontend/` — `package.json` dependencies, 7 pages |
| FastAPI + Pydantic + Postgres backend | ✅ Done | `app/main.py`, `app/config/settings.py` (Pydantic `Settings`), SQLAlchemy + Alembic |
| LangGraph agents backed by hosted Gemini (no local inference) | ✅ Done | `app/agents/graph.py` (`StateGraph`), `app/agents/llm_client.py` (`google-genai` SDK, `genai.Client`) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` env vars, default `gemini-2.5-flash` | ✅ Done | `app/config/settings.py`, `.env.example` |
| XGBoost or LightGBM forecasting | ✅ Done | `app/forecasting/ml_model.py` uses `XGBRegressor`; compared against a seasonal-naive baseline on real held-out MAE/RMSE/MAPE |
| OR-Tools optimization | ✅ Done | `app/optimization/solver.py` — genuine CP-SAT model for the instance-scheduling sub-problem; plain enumeration for small categorical choices (tier/pricing-model), documented as a deliberate scope decision in the Optimization section of the README, not a shortcut around OR-Tools |
| FAISS or Chroma RAG | ✅ Done | `app/rag/index.py` — `faiss.IndexFlatIP` over local `sentence-transformers` embeddings |
| Docker Compose | ✅ Done | `docker-compose.yml` — backend + postgres (no local LLM container; Gemini is hosted, correctly not containerized) |
| Pytest | ✅ Done | `backend/tests/` — 215 tests, 97% line coverage |

## Repo structure

| Requirement | Status | Evidence |
|---|---|---|
| `cloudpilot/{frontend, backend/app/{agents,tools,forecasting,optimization,pricing,rag,api,models,services,evaluation,config}, backend/tests, datasets, benchmark, docs, docker-compose.yml, .env.example, README.md}` | ✅ Structurally done | Every listed directory/file exists |
| `app/evaluation/` contains real evaluation logic | ⚠️ **Gap** | Contains only `__init__.py`. Scaffolded in Phase 1, never populated — no later phase asked for benchmark/evaluation content, so none was added rather than inventing scope. Not imported anywhere; removing it would change nothing at runtime. |
| `benchmark/` contains benchmark task definitions | ⚠️ **Gap** | Directory exists and is empty. Same reasoning as above. |
| `benchmark_runs` / `evaluation_results` DB tables | ⚠️ Partial | Tables and ORM models exist (`app/models/benchmark_run.py`, `app/models/evaluation_result.py`, both migrated), but nothing writes to them — a natural consequence of `app/evaluation/`/`benchmark/` being unimplemented. |
| 11 named tables | ✅ Done | `usage_records`, `resources`, `pricing`, `forecasts`, `cost_predictions`, `optimization_runs`, `scenarios`, `constraints`, `agent_events`, `benchmark_runs`, `evaluation_results` — all present via Alembic migrations |

## Engineering rules

| Rule | Status | Evidence |
|---|---|---|
| Real working code | ✅ Done | No mocked DB layer anywhere in `backend/tests/` — every test runs against a real Postgres. Mocking is confined to two narrow, unavoidable cases: Gemini API responses (`test_llm_client.py`'s retry/backoff tests, and a few agent-behavior tests in `test_agent_graph.py`/`test_agents.py`/`test_critic.py` that need a specific narrative to assert against) and, in this phase's own `test_rag_index_gaps.py`, the knowledge-chunk loader — to force the "no documents found" error path without deleting real markdown files. |
| No fake metrics/traces/hardcoded results | ✅ Done | MAE/RMSE/MAPE computed from real held-out arrays (`app/forecasting/evaluation.py`); `agent_events` rows are written by the actual tool calls that happened, not synthesized after the fact; confidence intervals derived from real residual std, `null` when not meaningful rather than fabricated |
| Recommendation-only — never touches real cloud infrastructure | ✅ Done | Grepped the whole `backend/app/` tree for `boto3`, `azure-mgmt`, `google-cloud-`, `azure.identity`, `botocore` — zero matches. No cloud provider SDK is imported anywhere. |
| Modular | ✅ Done | Each layer (forecasting/pricing/optimization/rag/agents/tools) is independently importable and independently tested; adding a new pricing provider is a data-only change (see README's Pricing engine section) |
| No scope creep | ✅ Done | Several explicit scope boundaries are documented rather than silently expanded: Database's storage cost is priced but not optimized by `storage_optimization`; OR-Tools used only for the genuinely combinatorial sub-problem; the What-If Simulator reuses the persisting optimization endpoint rather than a parallel non-persisting path |

## Test coverage by area (Phase 11 ask)

| Area | Status | Notes |
|---|---|---|
| Forecasting | ✅ | Baseline before-fit error, trailing-mean fallback, seasonal-naive path, ML model, engine model-selection, confidence intervals |
| Pricing | ✅ | Calculator, tiered pricing, aggregation, seed data (`build_seed_rows`, insert/skip/replace, `main()`) |
| Cost | ✅ | `cost_calculation.py`, `cost_prediction.py`, API success + 404/422 error paths, `cost/drivers` both `current` and `forecasted` sources |
| Optimization | ✅ | All 6 scenario simulators, solver, heuristics edge cases, `UnsupportedServiceError`/`InsufficientDemandDataError`, and — newly added this phase — the **fully-infeasible** path (see "Bug found" below) |
| Constraints | ✅ | `check_constraints`, plus infeasible-scenario constraint violations end-to-end |
| RAG | ✅ | Retrieval relevance, index build/reset, empty-knowledge-base error path |
| Tools | ✅ | Every tool's success + `ToolError` path, including the previously-untested `identify_cost_drivers(source="forecasted")` branch, and `run_tool`'s generic-exception-wrapping branch |
| Agents | ✅ | Full pipeline, critic reject/retry cycle to exhaustion, and — newly added this phase — every `plan.run_*=False` skip branch (previously untested since `DEFAULT_PLAN` always runs every step) |
| APIs | ✅ | Every route's success path; error paths for unknown resource, insufficient history, missing horizon, no backfilled actuals, no optimization runs |
| Full end-to-end workflow | ✅ | `test_agent_graph.py` runs the real graph against a real Postgres + real dataset, no mocking except Gemini itself |

Overall: **97% line coverage** (up from 94% at the start of this phase), 215/215 tests
passing. Remaining uncovered lines are almost entirely `if __name__ == "__main__":` CLI
entry points and the one documented unreachable branch in `heuristics.py` (see the
README's "Known gaps" section) — not untested business logic.

## Bug found and fixed during this phase

Filling the optimization test gaps surfaced a real production bug: when every one of
the 6 scenarios for a resource is infeasible (e.g. a region with no seeded pricing —
previously untested because every existing fixture used a seeded region), the
infeasible-placeholder's `predicted_cost`/`latency_ms` of `inf` crashed
`run_optimization` on write, because Postgres' `JSON` columns reject the `Infinity`
token and its `NUMERIC` columns can't represent non-finite values at all. Fixed with a
sanitize-on-write/restore-on-read helper (`_db_safe_float` in
`app/services/optimization_service.py`) across `Scenario.parameters`,
`Constraint.value`, `OptimizationRun.objective_value`, and
`result_summary.savings_vs_current` (the last one is now recomputed from the restored
per-scenario costs on read, rather than round-tripped as its own sanitized value). This
is exactly the class of gap this test-filling phase exists to find — a path no existing
test exercised, that would have crashed for a real user hitting a genuinely infeasible
configuration.
