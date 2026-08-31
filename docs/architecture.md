# Architecture

CloudPilot is recommendation-only: every arrow below either reads stored data or writes
a recommendation back to Postgres. Nothing in this system calls a real cloud provider's
API to provision, resize, or delete anything.

## Table of contents

- [Layer responsibilities](#layer-responsibilities)
- [System diagram](#system-diagram)
- [Why the tool layer exists](#why-the-tool-layer-exists)
- [Why the deterministic core has no LLM](#why-the-deterministic-core-has-no-llm)

## Layer responsibilities

The one non-negotiable rule the whole codebase is organized around:

| Layer | Package | Computes |
|---|---|---|
| ML models | `app/forecasting/` (XGBoost + seasonal-naive baseline) | Future usage |
| Pricing engine | `app/pricing/` | Cost, from usage × versioned rate data |
| Solver | `app/optimization/` (OR-Tools CP-SAT + documented heuristics) | Resource allocation under constraints |
| LLM agents | `app/agents/` (LangGraph + Gemini) | **Nothing numeric** — plan, narrate, critique |

Every number an agent's narrative mentions was produced by one of the top three rows
and handed to Gemini as already-computed JSON; the system instructions in
`app/agents/*.py` explicitly forbid the model from computing or inventing a number of
its own (see [`definition-of-done.md`](definition-of-done.md) for how this is verified
today, and its limits).

## System diagram

```mermaid
flowchart TB
    subgraph Client
        FE["React + TS + Vite + Tailwind + Recharts\n(frontend/)"]
    end

    subgraph API["FastAPI (app/api/)"]
        DataAPI["/data/upload"]
        ForecastAPI["/forecast"]
        CostAPI["/cost/*"]
        OptAPI["/optimization/*"]
        AgentAPI["/agent/run (SSE)"]
        TraceAPI["/agent-trace/{id} (SSE)"]
    end

    subgraph Core["Deterministic core — no LLM"]
        Ingest["app/services/data_ingestion.py"]
        Forecasting["app/forecasting/\nXGBoost + seasonal-naive baseline"]
        Pricing["app/pricing/\ncalculate_cost()"]
        CostPred["app/services/cost_prediction.py\nforecast x price"]
        Optimization["app/optimization/\nOR-Tools CP-SAT + heuristics"]
    end

    subgraph Agents["app/agents/ — LangGraph + Gemini"]
        Planner["Planner"]
        ForecastAgent["Forecast agent"]
        CostAgent["Cost Analysis agent"]
        OptAgent["Optimization agent"]
        Critic["Critic\n(deterministic checks + 1-sentence Gemini summary)"]
        Report["Report agent"]
    end

    Tools["app/tools/\ntyped, validated, logged wrappers\n(the ONLY way an agent gets a number)"]

    RAG["app/rag/\nFAISS + local sentence-transformers\n5 markdown FinOps guides"]

    DB[("PostgreSQL\nusage_records, pricing, forecasts,\ncost_predictions, scenarios, constraints,\noptimization_runs, agent_events")]

    Gemini[("Google Gemini API\ngemini-2.5-flash\nplan / narrate / critique-summary ONLY")]

    FE -->|REST + SSE| API
    DataAPI --> Ingest --> DB
    ForecastAPI --> Forecasting
    Forecasting <--> DB
    CostAPI --> CostPred
    CostPred --> Forecasting
    CostPred --> Pricing
    Pricing <--> DB
    CostPred --> DB
    OptAPI --> Optimization
    Optimization --> Pricing
    Optimization --> Forecasting
    Optimization --> DB

    AgentAPI --> Planner --> ForecastAgent --> CostAgent --> OptAgent
    OptAgent <-->|reject / retry, bounded to 3 attempts| Critic
    Critic --> Report
    ForecastAgent -.calls.-> Tools
    CostAgent -.calls.-> Tools
    OptAgent -.calls.-> Tools
    Tools --> Forecasting
    Tools --> Pricing
    Tools --> Optimization
    Tools --> RAG
    Tools -->|logs every call| DB
    TraceAPI -->|live tail| DB

    ForecastAgent -.narrate via.-> Gemini
    CostAgent -.narrate via.-> Gemini
    OptAgent -.narrate via.-> Gemini
    Critic -.1-sentence summary via.-> Gemini
    Report -.combine via.-> Gemini
    Planner -.classify via.-> Gemini
```

## Why the tool layer exists

`app/tools/` (Phase 7) is the enforcement mechanism for "agents never compute numbers,"
not just documentation of it. Every tool:

1. Takes typed, validated Pydantic input.
2. Calls straight into the deterministic core (forecasting/pricing/optimization/RAG) —
   never an LLM.
3. Is wrapped by `app/tools/base.py::run_tool()`, which logs agent name, tool name,
   input, output, latency, and status to `agent_events` — success or failure — before
   returning or raising.

An agent node can *only* obtain a number by calling one of these tools; there is no
other path from an agent node to a number in the codebase. That's what makes the
`agent_events` table a genuine audit trail rather than a best-effort log: any number in
a final report is traceable to exactly one logged tool call.

## Why the deterministic core has no LLM

Forecasting, pricing, and optimization are pure Python/NumPy/XGBoost/OR-Tools —
independently testable and independently correct without ever importing
`app/agents/llm_client.py`. This is why the test suite runs to completion (231 tests,
97% coverage) with no `GEMINI_API_KEY` configured at all: every deterministic
computation is verified for real, and every LLM-touching code path is verified via its
documented fallback behavior (see [`definition-of-done.md`](definition-of-done.md)).
