"""Optimization agent: orchestrates generate_scenarios -> simulate_scenario
(x6) -> check_constraints (x6) -> compare_scenarios ONCE per session (all
four are logged tool calls), then proposes candidates from the ranked list
one at a time for the Critic to approve or reject. A retry never re-runs
the solver — it just moves to the next already-computed candidate.

Once a candidate is approved (or every candidate has been rejected and the
bounded retry budget is spent), a final narrative is built that calls
`search_optimization_knowledge` for the scenario's category and cites the
retrieved source(s) — the recommendation is never presented as the
agent's own unsupported opinion.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.llm_client import LLMUnavailableError, generate_text
from app.forecasting.enums import ForecastHorizon
from app.models.resource import Resource
from app.optimization.enums import ScenarioType
from app.optimization.schemas import ConstraintCheck, ScenarioResult
from app.pricing.aggregation import aggregate_total
from app.pricing.enums import ServiceType
from app.tools.base import ToolError
from app.tools.cost_analysis import IdentifyCostDriversInput
from app.tools.forecasting import ForecastUsageInput, forecast_usage
from app.tools.knowledge import SearchOptimizationKnowledgeInput, search_optimization_knowledge
from app.tools.optimization import (
    CheckConstraintsInput,
    CompareScenariosInput,
    GenerateScenariosInput,
    SimulateScenarioInput,
    check_constraints,
    compare_scenarios,
    generate_scenarios,
    simulate_scenario,
)
from app.tools.pricing import CalculateCurrentCostInput, calculate_current_cost

AGENT_NAME = "optimization_agent"
MAX_CRITIC_ATTEMPTS = 3

# The usage_type that drives each service's demand-side capacity decision
# (see app.services.optimization_service.build_context, which uses the
# same mapping for the same reason).
_DEMAND_USAGE_TYPE = {
    ServiceType.COMPUTE: "requests",
    ServiceType.DATABASE: "requests",
    ServiceType.SERVERLESS: "requests",
    ServiceType.OBJECT_STORAGE: "storage_gb",
}

_KNOWLEDGE_QUERY_BY_SCENARIO = {
    ScenarioType.CURRENT: "utilization monitoring best practices",
    ScenarioType.AUTOSCALING: "autoscaling best practices avoiding outages",
    ScenarioType.RESERVED: "reserved capacity commitment pricing when it makes sense",
    ScenarioType.RIGHT_SIZING: "right-sizing cloud instance capacity",
    ScenarioType.STORAGE_OPTIMIZATION: "storage tier optimization cost",
    ScenarioType.COMBINED: "cloud cost optimization right-sizing autoscaling reserved capacity storage tiering",
}

NARRATION_SYSTEM_INSTRUCTION = (
    "You are the optimization explanation module of a cloud cost assistant. You are "
    "given an already-approved (or, if none could be approved, a best-effort) "
    "optimization scenario, its validation outcome, and supporting knowledge-base "
    "excerpts, all as structured JSON. Write a short (4-6 sentence) recommendation for "
    "a non-technical reader, and explicitly cite the knowledge-base source(s) by name "
    "when you use them (e.g. 'according to our Autoscaling Best Practices guide...'). "
    "Use ONLY the numbers given in the JSON — do not calculate, estimate, round "
    "differently, or invent any new number. If the scenario was not approved, say so "
    "plainly rather than presenting it as a confident recommendation."
)


class ScenarioBundle(BaseModel):
    results_by_type: dict[ScenarioType, ScenarioResult]
    checks_by_type: dict[ScenarioType, list[ConstraintCheck]]
    ranked_types: list[ScenarioType]
    forecast_uncertainty_ratio: float | None
    current_cost: float | None


def _forecast_uncertainty_ratio(forecast) -> float:
    ratios = []
    for p in forecast.points:
        if p.lower_bound is None or p.upper_bound is None:
            continue
        if p.predicted_usage and p.predicted_usage > 0:
            ratios.append((p.upper_bound - p.lower_bound) / p.predicted_usage)
    return sum(ratios) / len(ratios) if ratios else 0.0


def run_optimization_scenarios(
    db: Session,
    *,
    session_id: str,
    provider: str,
    resource_id: str,
    horizon: ForecastHorizon,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
) -> ScenarioBundle:
    resource = db.query(Resource).filter(Resource.external_id == resource_id).first()
    service = ServiceType(resource.resource_type) if resource else None

    scenarios_out = generate_scenarios(
        db, agent_name=AGENT_NAME, session_id=session_id, input=GenerateScenariosInput()
    )

    results_by_type: dict[ScenarioType, ScenarioResult] = {}
    checks_by_type: dict[ScenarioType, list[ConstraintCheck]] = {}

    for spec in scenarios_out.scenarios:
        try:
            result = simulate_scenario(
                db,
                agent_name=AGENT_NAME,
                session_id=session_id,
                input=SimulateScenarioInput(
                    provider=provider,
                    resource_id=resource_id,
                    scenario_type=spec.scenario_type,
                    horizon=horizon,
                    max_latency_ms=max_latency_ms,
                    min_availability=min_availability,
                    budget=budget,
                ),
            )
        except ToolError:
            continue

        results_by_type[result.scenario_type] = result

        try:
            checks_out = check_constraints(
                db,
                agent_name=AGENT_NAME,
                session_id=session_id,
                input=CheckConstraintsInput(
                    scenario_result=result,
                    max_latency_ms=max_latency_ms,
                    min_availability=min_availability,
                    budget=budget,
                ),
            )
            checks_by_type[result.scenario_type] = checks_out.checks
        except ToolError:
            checks_by_type[result.scenario_type] = []

    ranked_types: list[ScenarioType] = []
    if results_by_type:
        comparison = compare_scenarios(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=CompareScenariosInput(
                scenario_results=list(results_by_type.values()),
                max_latency_ms=max_latency_ms,
                min_availability=min_availability,
                budget=budget,
                checks_by_scenario_type=checks_by_type,
            ),
        )
        ranked_types = [r.scenario_type for r in comparison.ranked]

    forecast_uncertainty_ratio = None
    demand_usage_type = _DEMAND_USAGE_TYPE.get(service)
    if demand_usage_type:
        try:
            forecast = forecast_usage(
                db,
                agent_name=AGENT_NAME,
                session_id=session_id,
                input=ForecastUsageInput(resource_id=resource_id, usage_type=demand_usage_type, horizon=horizon),
            )
            forecast_uncertainty_ratio = _forecast_uncertainty_ratio(forecast)
        except ToolError:
            pass

    current_cost = None
    try:
        current = calculate_current_cost(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=CalculateCurrentCostInput(provider=provider, resource_id=resource_id),
        )
        current_cost = aggregate_total(current.line_items)
    except ToolError:
        pass

    return ScenarioBundle(
        results_by_type=results_by_type,
        checks_by_type=checks_by_type,
        ranked_types=ranked_types,
        forecast_uncertainty_ratio=forecast_uncertainty_ratio,
        current_cost=current_cost,
    )


def pick_next_candidate(ranked_types: list[ScenarioType], rejected_types: list[str]) -> ScenarioType | None:
    for scenario_type in ranked_types:
        if scenario_type.value not in rejected_types:
            return scenario_type
    return None


def build_optimization_narrative(
    db: Session,
    *,
    session_id: str,
    candidate: ScenarioResult | None,
    approved: bool,
    rejection_history: list[dict],
    exhausted: bool,
) -> tuple[dict, str]:
    knowledge_results = []
    if candidate is not None:
        try:
            knowledge_out = search_optimization_knowledge(
                db,
                agent_name=AGENT_NAME,
                session_id=session_id,
                input=SearchOptimizationKnowledgeInput(
                    query=_KNOWLEDGE_QUERY_BY_SCENARIO.get(candidate.scenario_type, "cloud cost optimization"),
                    top_k=2,
                ),
            )
            knowledge_results = [r.model_dump(mode="json") for r in knowledge_out.results]
        except ToolError:
            pass

    data = {
        "candidate": candidate.model_dump(mode="json") if candidate else None,
        "approved": approved,
        "exhausted_without_approval": exhausted,
        "rejection_history": rejection_history,
        "knowledge_sources": knowledge_results,
    }

    if candidate is None:
        narrative = (
            "No scenario could be simulated for this resource, so no optimization "
            "recommendation is available."
        )
        return data, narrative

    prompt = f"Data (JSON): {data}"
    try:
        narrative = generate_text(prompt, system_instruction=NARRATION_SYSTEM_INSTRUCTION)
    except LLMUnavailableError:
        sources_note = (
            " Sources: " + "; ".join(k["source"] for k in knowledge_results) if knowledge_results else ""
        )
        if approved:
            narrative = (
                f"[template fallback — Gemini unavailable] Recommended scenario: "
                f"'{candidate.name}' at an estimated cost of ${candidate.predicted_cost:.2f}; "
                f"all validation checks passed.{sources_note}"
            )
        else:
            narrative = (
                f"[template fallback — Gemini unavailable] No scenario passed validation "
                f"after {len(rejection_history)} attempt(s). The closest option was "
                f"'{candidate.name}' at ${candidate.predicted_cost:.2f}, but it was rejected: "
                f"{rejection_history[-1]['verdict']['rejection_reason'] if rejection_history else 'unknown reason'}."
                f"{sources_note}"
            )

    return data, narrative
