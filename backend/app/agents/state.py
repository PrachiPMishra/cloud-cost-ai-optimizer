"""Shared LangGraph state threaded through planner -> forecast ->
cost_analysis -> optimization <-> critic -> report.

The optimization/critic pair can cycle: `optimization` proposes one
candidate scenario, `critic` evaluates it and either approves it (-> report)
or rejects it and routes back to `optimization` for another candidate,
bounded by `optimization_attempt` vs. MAX_CRITIC_ATTEMPTS
(`app.agents.optimization_agent`). All 6 scenarios are simulated once on
the first pass and cached here (`optimization_ranked`, `*_by_type`) — a
retry re-evaluates a different already-computed candidate, it never
re-runs the solver.
"""

from __future__ import annotations

from typing import TypedDict

from app.forecasting.enums import ForecastHorizon


class AgentState(TypedDict, total=False):
    session_id: str
    user_query: str
    provider: str
    resource_id: str
    usage_type: str
    horizon: ForecastHorizon
    max_latency_ms: float
    min_availability: float
    budget: float

    plan: dict
    forecast_data: dict
    forecast_narrative: str
    cost_data: dict
    cost_narrative: str

    # optimization <-> critic loop
    optimization_ranked: list[dict]
    optimization_results_by_type: dict[str, dict]
    optimization_checks_by_type: dict[str, list[dict]]
    forecast_uncertainty_ratio: float
    rejected_scenario_types: list[str]
    optimization_attempt: int
    current_candidate_type: str | None
    current_cost: float | None
    critic_verdict: dict
    critic_history: list[dict]
    optimization_exhausted: bool
    optimization_skipped: bool

    optimization_data: dict
    optimization_narrative: str
    critic_notes: str
    final_report: str
