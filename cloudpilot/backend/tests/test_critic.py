from unittest.mock import patch

from app.agents.critic import (
    MAX_ACCEPTABLE_UNCERTAINTY_RATIO,
    MAX_PLAUSIBLE_COST_REDUCTION_FRACTION,
    evaluate_scenario,
    summarize_verdict,
)
from app.optimization.enums import ScenarioType
from app.optimization.schemas import ConstraintCheck, ScenarioResult


def _scenario(**overrides) -> ScenarioResult:
    defaults = dict(
        scenario_type=ScenarioType.RIGHT_SIZING,
        name="Right-sizing",
        description="",
        configuration={},
        predicted_demand_peak=100.0,
        capacity_provisioned=150.0,
        predicted_cost=50.0,
        latency_ms=30.0,
        availability=0.999,
        solver_status="OPTIMAL",
    )
    defaults.update(overrides)
    return ScenarioResult(**defaults)


def _passing_checks() -> list[ConstraintCheck]:
    return [
        ConstraintCheck(constraint_type="capacity", threshold=100.0, actual=150.0, satisfied=True, description="ok"),
        ConstraintCheck(constraint_type="latency", threshold=100.0, actual=30.0, satisfied=True, description="ok"),
        ConstraintCheck(constraint_type="availability", threshold=0.99, actual=0.999, satisfied=True, description="ok"),
        ConstraintCheck(constraint_type="budget", threshold=1000.0, actual=50.0, satisfied=True, description="ok"),
    ]


def test_approves_a_clean_scenario() -> None:
    verdict = evaluate_scenario(
        _scenario(), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3
    )
    assert verdict.approved is True
    assert verdict.rejection_reason is None
    assert all(f.passed for f in verdict.findings)


def test_rejects_when_a_constraint_check_fails() -> None:
    checks = _passing_checks()
    checks[1] = ConstraintCheck(constraint_type="latency", threshold=20.0, actual=30.0, satisfied=False, description="too slow")

    verdict = evaluate_scenario(_scenario(), checks, current_cost=100.0, forecast_uncertainty_ratio=0.3)

    assert verdict.approved is False
    assert "constraint:latency" in verdict.rejection_reason


def test_rejects_negative_cost() -> None:
    verdict = evaluate_scenario(
        _scenario(predicted_cost=-10.0), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3
    )
    assert verdict.approved is False
    assert "unrealistic_assumptions:cost" in verdict.rejection_reason


def test_rejects_invalid_availability() -> None:
    verdict = evaluate_scenario(
        _scenario(availability=1.5), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3
    )
    assert verdict.approved is False
    assert "unrealistic_assumptions:availability" in verdict.rejection_reason


def test_rejects_nonpositive_latency() -> None:
    verdict = evaluate_scenario(
        _scenario(latency_ms=0.0), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3
    )
    assert verdict.approved is False
    assert "unrealistic_assumptions:latency" in verdict.rejection_reason


def test_rejects_capacity_below_demand() -> None:
    verdict = evaluate_scenario(
        _scenario(capacity_provisioned=50.0, predicted_demand_peak=100.0),
        _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3,
    )
    assert verdict.approved is False
    assert "capacity" in verdict.rejection_reason


def test_rejects_implausibly_large_cost_reduction() -> None:
    # 99% cost reduction is far more likely a pricing/data bug than a real win.
    verdict = evaluate_scenario(
        _scenario(predicted_cost=1.0), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3
    )
    assert verdict.approved is False
    assert "unrealistic_assumptions:savings" in verdict.rejection_reason


def test_approves_plausible_cost_reduction() -> None:
    reduction = MAX_PLAUSIBLE_COST_REDUCTION_FRACTION - 0.1
    verdict = evaluate_scenario(
        _scenario(predicted_cost=100.0 * (1 - reduction)),
        _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3,
    )
    assert verdict.approved is True


def test_rejects_high_forecast_uncertainty() -> None:
    verdict = evaluate_scenario(
        _scenario(),
        _passing_checks(),
        current_cost=100.0,
        forecast_uncertainty_ratio=MAX_ACCEPTABLE_UNCERTAINTY_RATIO + 0.5,
    )
    assert verdict.approved is False
    assert "forecast_uncertainty" in verdict.rejection_reason


def test_uncertainty_at_threshold_is_still_approved() -> None:
    verdict = evaluate_scenario(
        _scenario(), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=MAX_ACCEPTABLE_UNCERTAINTY_RATIO
    )
    assert verdict.approved is True


def test_missing_forecast_uncertainty_does_not_block_approval() -> None:
    verdict = evaluate_scenario(_scenario(), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=None)
    assert verdict.approved is True


def test_summarize_verdict_fallback_without_api_key() -> None:
    verdict = evaluate_scenario(_scenario(), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3)
    note = summarize_verdict(verdict)
    assert "template fallback" in note


def test_summarize_verdict_uses_llm_when_available() -> None:
    verdict = evaluate_scenario(_scenario(), _passing_checks(), current_cost=100.0, forecast_uncertainty_ratio=0.3)
    with patch("app.agents.critic.generate_text", return_value="Looks solid."):
        note = summarize_verdict(verdict)
    assert note == "Looks solid."
