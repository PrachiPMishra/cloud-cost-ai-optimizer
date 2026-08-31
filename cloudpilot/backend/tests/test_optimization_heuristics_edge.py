from app.optimization.heuristics import (
    estimate_availability,
    estimate_latency_ms,
    min_capacity_for_latency,
    min_instances_for_availability,
)


def test_min_capacity_for_latency_near_base_latency_needs_huge_capacity() -> None:
    # max_latency_ms only marginally above base_latency_ms forces
    # max_allowed_utilization down near zero, so the required capacity
    # (demand / max_allowed_utilization) blows up towards infinity — the
    # function must return that huge finite number rather than raising or
    # dividing by exactly zero.
    demand = 100.0
    base_latency_ms = 50.0
    max_latency_ms = 50.0000001

    result = min_capacity_for_latency(demand, base_latency_ms, max_latency_ms)

    assert result > demand * 1_000_000
    # Sanity: provisioning that much capacity for this demand keeps latency near base.
    assert estimate_latency_ms(base_latency_ms, demand, result) < base_latency_ms * 1.01


def test_min_capacity_for_latency_max_at_or_below_base_returns_large_capacity() -> None:
    result = min_capacity_for_latency(demand=100.0, base_latency_ms=50.0, max_latency_ms=10.0)
    assert result == 100.0 * 1000.0


def test_min_instances_for_availability_asymptotic_target_is_capped() -> None:
    # Requesting exactly 100% availability is mathematically unreachable for any
    # finite instance count under the independent-failure model; the function
    # caps at a bounded fleet size instead of looping forever / returning inf.
    n = min_instances_for_availability(base_failure_rate=0.01, min_availability=1.0)
    assert n == 20


def test_min_instances_for_availability_normal_case_matches_forward_model() -> None:
    n = min_instances_for_availability(base_failure_rate=0.05, min_availability=0.999)
    assert estimate_availability(0.05, n) >= 0.999
    assert estimate_availability(0.05, n - 1) < 0.999


def test_min_instances_for_availability_trivial_targets_return_one() -> None:
    assert min_instances_for_availability(base_failure_rate=0.05, min_availability=0.0) == 1
    assert min_instances_for_availability(base_failure_rate=0.0, min_availability=0.99) == 1
