"""Covers the planner-driven 'skip this step' branches of the LangGraph
pipeline nodes. The planner (Gemini, or DEFAULT_PLAN when the LLM is
unavailable) can set run_forecast/run_cost_analysis/run_optimization to
False; the graph nodes must honor that without touching the DB or the
deterministic tool layer at all. These branches are never exercised by the
existing end-to-end tests because DEFAULT_PLAN always runs every step, so
they're tested here by calling the node closures directly with a
hand-built state.
"""

from app.agents.graph import (
    _make_cost_analysis_node,
    _make_forecast_node,
    _make_optimization_node,
    _route_after_optimization,
)


def test_forecast_node_skips_when_plan_says_no() -> None:
    node = _make_forecast_node(db=None)
    state = {"plan": {"run_forecast": False}}

    result = node(state)

    assert result == {"forecast_data": {}, "forecast_narrative": "Forecasting skipped per plan."}


def test_cost_analysis_node_skips_when_plan_says_no() -> None:
    node = _make_cost_analysis_node(db=None)
    state = {"plan": {"run_cost_analysis": False}}

    result = node(state)

    assert result == {"cost_data": {}, "cost_narrative": "Cost analysis skipped per plan."}


def test_optimization_node_skips_when_plan_says_no() -> None:
    node = _make_optimization_node(db=None)
    state = {"plan": {"run_optimization": False}}

    result = node(state)

    assert result["optimization_data"] == {}
    assert result["optimization_narrative"] == "Optimization skipped per plan."
    assert result["optimization_skipped"] is True


def test_route_after_optimization_goes_straight_to_report_when_skipped() -> None:
    assert _route_after_optimization({"optimization_skipped": True}) == "report"


def test_route_after_optimization_finalizes_when_no_candidate_selected() -> None:
    assert _route_after_optimization({"current_candidate_type": None}) == "finalize_optimization"


def test_route_after_optimization_goes_to_critic_when_candidate_present() -> None:
    assert _route_after_optimization({"current_candidate_type": "right_sizing"}) == "critic"
