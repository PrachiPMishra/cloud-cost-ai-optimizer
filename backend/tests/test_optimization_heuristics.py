import pytest

from app.optimization.heuristics import (
    estimate_availability,
    estimate_latency_ms,
    min_capacity_for_latency,
    min_instances_for_availability,
)


def test_latency_increases_with_utilization() -> None:
    low = estimate_latency_ms(base_latency_ms=10.0, demand=10, capacity=100)
    high = estimate_latency_ms(base_latency_ms=10.0, demand=90, capacity=100)
    assert high > low
    assert low >= 10.0


def test_latency_is_bounded_when_capacity_is_zero() -> None:
    assert estimate_latency_ms(base_latency_ms=10.0, demand=10, capacity=0) == float("inf")


def test_availability_increases_with_instance_count() -> None:
    one = estimate_availability(base_failure_rate=0.02, instance_count=1)
    two = estimate_availability(base_failure_rate=0.02, instance_count=2)
    three = estimate_availability(base_failure_rate=0.02, instance_count=3)
    assert one < two < three
    assert one == pytest.approx(0.98)
    assert two == pytest.approx(1 - 0.02**2)


def test_min_capacity_for_latency_round_trips() -> None:
    demand = 500.0
    base_latency = 20.0
    max_latency = 40.0

    required_capacity = min_capacity_for_latency(demand, base_latency, max_latency)
    resulting_latency = estimate_latency_ms(base_latency, demand, required_capacity)

    assert resulting_latency <= max_latency + 1e-6


def test_min_capacity_for_latency_impossible_target_returns_large_value() -> None:
    # max_latency below base_latency can never be satisfied by any capacity
    result = min_capacity_for_latency(demand=100.0, base_latency_ms=50.0, max_latency_ms=10.0)
    assert result > 100.0 * 100


def test_min_instances_for_availability_round_trips() -> None:
    base_failure_rate = 0.02
    min_availability = 0.9999

    n = min_instances_for_availability(base_failure_rate, min_availability)
    achieved = estimate_availability(base_failure_rate, n)

    assert achieved >= min_availability
    # one fewer instance should not meet the target (tightness check)
    if n > 1:
        assert estimate_availability(base_failure_rate, n - 1) < min_availability


def test_min_instances_for_availability_trivial_target() -> None:
    assert min_instances_for_availability(0.02, 0.0) == 1
