"""Builds and runs the LangGraph pipeline:

    planner -> forecast -> cost_analysis -> optimization <-> critic -> report

`optimization` and `critic` form a bounded cycle: `optimization` proposes
one candidate scenario (all 6 are simulated once, on the first pass, and
cached in state — a retry just proposes a different already-computed
candidate), `critic` evaluates it, and a conditional edge either proceeds
to `report` (approved, or retries exhausted) or loops back to
`optimization` (rejected, retries remain).

Every node calls the deterministic tool layer (`app/tools/`) for every
number it needs — the LLM (via `app/agents/llm_client.py`) is only ever
asked to plan over or narrate results the tools already computed.
"""

from __future__ import annotations

import uuid

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.cost_analysis_agent import run_cost_analysis_agent
from app.agents.critic import evaluate_scenario, summarize_verdict
from app.agents.forecast_agent import run_forecast_agent
from app.agents.optimization_agent import (
    MAX_CRITIC_ATTEMPTS,
    build_optimization_narrative,
    pick_next_candidate,
    run_optimization_scenarios,
)
from app.agents.planner import plan_request
from app.agents.report import run_report_agent
from app.agents.state import AgentState
from app.optimization.enums import ScenarioType
from app.optimization.schemas import ConstraintCheck, ScenarioResult


def _planner_node(state: AgentState) -> dict:
    plan = plan_request(state["user_query"])
    return {"plan": plan.model_dump(mode="json")}


def _make_forecast_node(db: Session):
    def _node(state: AgentState) -> dict:
        if not state["plan"].get("run_forecast", True):
            return {"forecast_data": {}, "forecast_narrative": "Forecasting skipped per plan."}
        result = run_forecast_agent(
            db,
            session_id=state["session_id"],
            resource_id=state["resource_id"],
            usage_type=state["usage_type"],
            horizon=state["horizon"],
        )
        return {"forecast_data": result, "forecast_narrative": result.get("narrative", "")}

    return _node


def _make_cost_analysis_node(db: Session):
    def _node(state: AgentState) -> dict:
        if not state["plan"].get("run_cost_analysis", True):
            return {"cost_data": {}, "cost_narrative": "Cost analysis skipped per plan."}
        result = run_cost_analysis_agent(
            db,
            session_id=state["session_id"],
            provider=state["provider"],
            resource_id=state["resource_id"],
            horizon=state["horizon"],
        )
        return {"cost_data": result, "cost_narrative": result.get("narrative", "")}

    return _node


def _make_optimization_node(db: Session):
    def _node(state: AgentState) -> dict:
        if not state["plan"].get("run_optimization", True):
            return {
                "optimization_data": {},
                "optimization_narrative": "Optimization skipped per plan.",
                "optimization_skipped": True,
            }

        attempt = state.get("optimization_attempt", 0)
        rejected_types = state.get("rejected_scenario_types", [])

        if attempt == 0:
            bundle = run_optimization_scenarios(
                db,
                session_id=state["session_id"],
                provider=state["provider"],
                resource_id=state["resource_id"],
                horizon=state["horizon"],
                max_latency_ms=state["max_latency_ms"],
                min_availability=state["min_availability"],
                budget=state["budget"],
            )
            if not bundle.ranked_types:
                # Nothing could even be simulated — finalize_optimization
                # handles candidate=None uniformly (no separate narrative here).
                return {
                    "optimization_results_by_type": {},
                    "current_candidate_type": None,
                    "optimization_attempt": 1,
                }

            update: dict = {
                "optimization_ranked": [t.value for t in bundle.ranked_types],
                "optimization_results_by_type": {
                    t.value: r.model_dump(mode="json") for t, r in bundle.results_by_type.items()
                },
                "optimization_checks_by_type": {
                    t.value: [c.model_dump(mode="json") for c in checks]
                    for t, checks in bundle.checks_by_type.items()
                },
                "forecast_uncertainty_ratio": bundle.forecast_uncertainty_ratio,
                "current_cost": bundle.current_cost,
                "rejected_scenario_types": [],
                "critic_history": [],
            }
            ranked_types = bundle.ranked_types
        else:
            update = {}
            ranked_types = [ScenarioType(t) for t in state["optimization_ranked"]]

        candidate_type = pick_next_candidate(ranked_types, rejected_types)
        update["current_candidate_type"] = candidate_type.value if candidate_type else None
        update["optimization_attempt"] = attempt + 1
        return update

    return _node


def _critic_node(state: AgentState) -> dict:
    candidate_type_value = state.get("current_candidate_type")
    history = list(state.get("critic_history", []))

    if candidate_type_value is None:
        # Routing sends a None candidate straight to finalize_optimization
        # without visiting this node — kept as a defensive no-op.
        return {"optimization_exhausted": True, "critic_history": history}

    results_by_type = state["optimization_results_by_type"]
    checks_by_type = state["optimization_checks_by_type"]

    candidate = ScenarioResult.model_validate(results_by_type[candidate_type_value])
    checks = [ConstraintCheck.model_validate(c) for c in checks_by_type.get(candidate_type_value, [])]

    verdict = evaluate_scenario(
        candidate,
        checks,
        current_cost=state.get("current_cost"),
        forecast_uncertainty_ratio=state.get("forecast_uncertainty_ratio"),
    )
    note = summarize_verdict(verdict)
    history.append({"scenario_type": candidate_type_value, "verdict": verdict.model_dump(mode="json")})

    update: dict = {"critic_verdict": verdict.model_dump(mode="json"), "critic_notes": note, "critic_history": history}

    if not verdict.approved:
        rejected = list(state.get("rejected_scenario_types", []))
        rejected.append(candidate_type_value)
        update["rejected_scenario_types"] = rejected

    attempt = state.get("optimization_attempt", 1)
    exhausted = (not verdict.approved) and attempt >= MAX_CRITIC_ATTEMPTS
    update["optimization_exhausted"] = verdict.approved or exhausted

    return update


def _make_finalize_optimization_node(db: Session):
    def _node(state: AgentState) -> dict:
        candidate_type_value = state.get("current_candidate_type")
        results_by_type = state.get("optimization_results_by_type", {})

        candidate = (
            ScenarioResult.model_validate(results_by_type[candidate_type_value])
            if candidate_type_value and candidate_type_value in results_by_type
            else None
        )
        verdict = state.get("critic_verdict", {})
        approved = bool(verdict.get("approved"))

        data, narrative = build_optimization_narrative(
            db,
            session_id=state["session_id"],
            candidate=candidate,
            approved=approved,
            rejection_history=state.get("critic_history", []),
            exhausted=not approved,
        )
        return {"optimization_data": data, "optimization_narrative": narrative}

    return _node


def _route_after_optimization(state: AgentState) -> str:
    if state.get("optimization_skipped"):
        return "report"
    if state.get("current_candidate_type") is None:
        return "finalize_optimization"
    return "critic"


def _route_after_critic(state: AgentState) -> str:
    if state.get("optimization_exhausted"):
        return "finalize_optimization"
    return "optimization"


def _report_node(state: AgentState) -> dict:
    report = run_report_agent(
        forecast_narrative=state.get("forecast_narrative", ""),
        cost_narrative=state.get("cost_narrative", ""),
        optimization_narrative=state.get("optimization_narrative", ""),
        critic_notes=state.get("critic_notes", ""),
    )
    return {"final_report": report}


def build_graph(db: Session):
    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner_node)
    graph.add_node("forecast", _make_forecast_node(db))
    graph.add_node("cost_analysis", _make_cost_analysis_node(db))
    graph.add_node("optimization", _make_optimization_node(db))
    graph.add_node("critic", _critic_node)
    graph.add_node("finalize_optimization", _make_finalize_optimization_node(db))
    graph.add_node("report", _report_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "forecast")
    graph.add_edge("forecast", "cost_analysis")
    graph.add_edge("cost_analysis", "optimization")
    graph.add_conditional_edges(
        "optimization", _route_after_optimization, ["critic", "finalize_optimization", "report"]
    )
    graph.add_conditional_edges("critic", _route_after_critic, ["optimization", "finalize_optimization"])
    graph.add_edge("finalize_optimization", "report")
    graph.add_edge("report", END)

    return graph.compile()


def _build_initial_state(
    *,
    session_id: str,
    user_query: str,
    provider: str,
    resource_id: str,
    usage_type: str,
    horizon,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
) -> AgentState:
    return {
        "session_id": session_id,
        "user_query": user_query,
        "provider": provider,
        "resource_id": resource_id,
        "usage_type": usage_type,
        "horizon": horizon,
        "max_latency_ms": max_latency_ms,
        "min_availability": min_availability,
        "budget": budget,
        "optimization_attempt": 0,
        "rejected_scenario_types": [],
    }


def run_agent_session(
    db: Session,
    *,
    user_query: str,
    provider: str,
    resource_id: str,
    usage_type: str,
    horizon,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
) -> AgentState:
    session_id = str(uuid.uuid4())
    graph = build_graph(db)
    initial_state = _build_initial_state(
        session_id=session_id, user_query=user_query, provider=provider, resource_id=resource_id,
        usage_type=usage_type, horizon=horizon, max_latency_ms=max_latency_ms,
        min_availability=min_availability, budget=budget,
    )
    return graph.invoke(initial_state, {"recursion_limit": 50})


def stream_agent_session(
    db: Session,
    *,
    user_query: str,
    provider: str,
    resource_id: str,
    usage_type: str,
    horizon,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
):
    """Yields one {node_name: partial_state_update} dict per completed
    LangGraph node, in real time — genuine live step progress (via
    LangGraph's own `stream_mode="updates"`), not a simulated progress bar.
    The first yielded item is a synthetic `{"_meta": {"session_id": ...}}`
    so a caller can start tracking the session before any node completes.
    """
    session_id = str(uuid.uuid4())
    graph = build_graph(db)
    initial_state = _build_initial_state(
        session_id=session_id, user_query=user_query, provider=provider, resource_id=resource_id,
        usage_type=usage_type, horizon=horizon, max_latency_ms=max_latency_ms,
        min_availability=min_availability, budget=budget,
    )

    yield {"_meta": {"session_id": session_id, "event": "started"}}
    for chunk in graph.stream(initial_state, {"recursion_limit": 50}, stream_mode="updates"):
        yield chunk
    yield {"_meta": {"session_id": session_id, "event": "done"}}
