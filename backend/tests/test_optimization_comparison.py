from app.optimization.comparison import compare_scenarios
from app.optimization.enums import ScenarioType
from app.optimization.schemas import ScenarioResult


def _result(scenario_type: ScenarioType, cost: float, latency=10.0, availability=0.9999, capacity=100.0, demand=50.0) -> ScenarioResult:
    return ScenarioResult(
        scenario_type=scenario_type,
        name=scenario_type.value,
        description="",
        configuration={},
        predicted_demand_peak=demand,
        capacity_provisioned=capacity,
        predicted_cost=cost,
        latency_ms=latency,
        availability=availability,
        solver_status="OPTIMAL",
    )


def test_compare_scenarios_ranks_by_cost_ascending() -> None:
    results = [
        _result(ScenarioType.CURRENT, 100.0),
        _result(ScenarioType.RESERVED, 70.0),
        _result(ScenarioType.COMBINED, 50.0),
    ]

    comparison = compare_scenarios(results, max_latency_ms=100.0, min_availability=0.99, budget=1000.0)

    assert [r.scenario_type for r in comparison.ranked] == [
        ScenarioType.COMBINED, ScenarioType.RESERVED, ScenarioType.CURRENT
    ]
    assert comparison.cheapest_feasible_scenario_type == ScenarioType.COMBINED
    assert comparison.fully_feasible is True


def test_compare_scenarios_savings_vs_current() -> None:
    results = [_result(ScenarioType.CURRENT, 100.0), _result(ScenarioType.RESERVED, 60.0)]
    comparison = compare_scenarios(results, max_latency_ms=100.0, min_availability=0.99, budget=1000.0)

    reserved = next(r for r in comparison.ranked if r.scenario_type == ScenarioType.RESERVED)
    current = next(r for r in comparison.ranked if r.scenario_type == ScenarioType.CURRENT)
    assert reserved.savings_vs_current == 40.0
    assert current.savings_vs_current == 0.0


def test_compare_scenarios_falls_back_when_none_feasible() -> None:
    results = [
        _result(ScenarioType.CURRENT, 100.0, latency=500.0),  # violates latency
        _result(ScenarioType.RESERVED, 60.0, latency=500.0),  # violates latency
    ]
    comparison = compare_scenarios(results, max_latency_ms=100.0, min_availability=0.99, budget=1000.0)

    assert comparison.fully_feasible is False
    assert comparison.cheapest_feasible_scenario_type is None
    # still ranked cheapest-first even though none are feasible
    assert comparison.ranked[0].scenario_type == ScenarioType.RESERVED


def test_compare_scenarios_uses_precomputed_checks_when_given() -> None:
    from app.optimization.schemas import ConstraintCheck

    results = [_result(ScenarioType.CURRENT, 100.0, latency=500.0)]  # would normally violate latency
    precomputed = {
        ScenarioType.CURRENT: [
            ConstraintCheck(constraint_type="latency", threshold=100.0, actual=500.0, satisfied=True, description="forced satisfied for this test")
        ]
    }

    comparison = compare_scenarios(
        results, max_latency_ms=100.0, min_availability=0.99, budget=1000.0,
        checks_by_scenario_type=precomputed,
    )

    assert comparison.ranked[0].constraints_satisfied is True


def test_compare_scenarios_empty_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        compare_scenarios([], max_latency_ms=100.0, min_availability=0.99, budget=1000.0)
