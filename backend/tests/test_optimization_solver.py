import pytest

from app.optimization.solver import OptimizationInfeasibleError, solve_instance_schedule


def test_fixed_schedule_is_sized_to_peak_demand() -> None:
    demand = [3600, 5000, 12000, 4000, 3600, 3600, 3600]
    schedule, status = solve_instance_schedule(
        demand, capacity_per_instance_per_day=7200, min_instances=1, hourly_rate=0.096,
        allow_autoscaling=False,
    )

    assert status == "OPTIMAL"
    assert len(set(schedule)) == 1  # constant across all days
    assert schedule[0] * 7200 >= max(demand)


def test_autoscaling_schedule_tracks_demand_and_costs_less() -> None:
    demand = [3600, 5000, 12000, 4000, 3600, 3600, 3600]

    fixed_schedule, _ = solve_instance_schedule(
        demand, capacity_per_instance_per_day=7200, min_instances=1, hourly_rate=0.096,
        allow_autoscaling=False,
    )
    auto_schedule, status = solve_instance_schedule(
        demand, capacity_per_instance_per_day=7200, min_instances=1, hourly_rate=0.096,
        allow_autoscaling=True,
    )

    assert status == "OPTIMAL"
    assert len(auto_schedule) == len(demand)
    for count, d in zip(auto_schedule, demand):
        assert count * 7200 >= d
    assert sum(auto_schedule) <= sum(fixed_schedule)
    assert len(set(auto_schedule)) > 1  # actually varies


def test_autoscaling_respects_max_daily_step() -> None:
    demand = [100, 100, 100, 100000, 100, 100, 100]
    schedule, _ = solve_instance_schedule(
        demand, capacity_per_instance_per_day=100, min_instances=1, hourly_rate=0.01,
        allow_autoscaling=True, max_daily_step=5,
    )

    for a, b in zip(schedule, schedule[1:]):
        assert abs(a - b) <= 5


def test_min_instances_is_respected_even_when_demand_is_low() -> None:
    demand = [1, 1, 1]
    schedule, _ = solve_instance_schedule(
        demand, capacity_per_instance_per_day=1000, min_instances=3, hourly_rate=0.1,
        allow_autoscaling=False,
    )
    assert all(count >= 3 for count in schedule)


def test_budget_constraint_is_honored_when_feasible() -> None:
    demand = [100] * 5
    cheap_schedule, status = solve_instance_schedule(
        demand, capacity_per_instance_per_day=100, min_instances=1, hourly_rate=0.10,
        allow_autoscaling=False, budget=1000.0,
    )
    assert status == "OPTIMAL"
    total_cost = sum(cheap_schedule) * 0.10 * 24
    assert total_cost <= 1000.0


def test_infeasible_budget_falls_back_without_budget_constraint() -> None:
    demand = [10000] * 5
    schedule, status = solve_instance_schedule(
        demand, capacity_per_instance_per_day=100, min_instances=1, hourly_rate=1.0,
        allow_autoscaling=False, budget=0.01,
    )
    # capacity is still respected even though budget could not be
    assert schedule[0] * 100 >= 10000


def test_empty_demand_raises_value_error() -> None:
    with pytest.raises(ValueError):
        solve_instance_schedule([], capacity_per_instance_per_day=100, min_instances=1, hourly_rate=0.1)
