"""check_constraints(): pure comparison of a simulated scenario's actual
metrics against the caller's targets. No solving, no pricing — just flags."""

from __future__ import annotations

from app.optimization.schemas import ConstraintCheck, ScenarioResult


def check_constraints(
    result: ScenarioResult,
    *,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
) -> list[ConstraintCheck]:
    return [
        ConstraintCheck(
            constraint_type="capacity",
            threshold=result.predicted_demand_peak,
            actual=result.capacity_provisioned,
            satisfied=result.capacity_provisioned >= result.predicted_demand_peak,
            description="Provisioned capacity must meet or exceed peak predicted demand",
        ),
        ConstraintCheck(
            constraint_type="latency",
            threshold=max_latency_ms,
            actual=result.latency_ms,
            satisfied=result.latency_ms <= max_latency_ms,
            description=f"Estimated latency must not exceed {max_latency_ms}ms",
        ),
        ConstraintCheck(
            constraint_type="availability",
            threshold=min_availability,
            actual=result.availability,
            satisfied=result.availability >= min_availability,
            description=f"Estimated availability must be at least {min_availability}",
        ),
        ConstraintCheck(
            constraint_type="budget",
            threshold=budget,
            actual=result.predicted_cost,
            satisfied=result.predicted_cost <= budget,
            description=f"Predicted cost must not exceed budget of {budget}",
        ),
    ]
