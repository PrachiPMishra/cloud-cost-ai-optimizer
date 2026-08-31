from datetime import date

from app.pricing import CostCalculationResult, ServiceType, TierBreakdown
from app.pricing.aggregation import (
    aggregate_by_resource,
    aggregate_by_service,
    aggregate_by_usage_unit,
    aggregate_total,
)


def _result(service: ServiceType, sku: str, unit: str, resource_id: str, cost: float) -> CostCalculationResult:
    return CostCalculationResult(
        provider="aws",
        region="us-east-1",
        service=service,
        sku=sku,
        unit=unit,
        pricing_model="on_demand",
        commitment_term_months=None,
        resource_id=resource_id,
        resolved_quantity=1.0,
        cost=cost,
        currency="USD",
        effective_date=date(2026, 1, 1),
        tiers_applied=[TierBreakdown(tier_min=0, tier_max=None, quantity=1.0, rate=cost, subtotal=cost)],
    )


def _sample_results() -> list[CostCalculationResult]:
    return [
        _result(ServiceType.COMPUTE, "compute-instance-hour", "hour", "res-1", 10.0),
        _result(ServiceType.COMPUTE, "compute-network-egress", "gb", "res-1", 2.0),
        _result(ServiceType.DATABASE, "database-instance-hour", "hour", "res-2", 5.0),
    ]


def test_aggregate_total() -> None:
    assert aggregate_total(_sample_results()) == 17.0


def test_aggregate_by_service() -> None:
    totals = aggregate_by_service(_sample_results())
    assert totals == {"Compute": 12.0, "Database": 5.0}


def test_aggregate_by_resource() -> None:
    totals = aggregate_by_resource(_sample_results())
    assert totals == {"res-1": 12.0, "res-2": 5.0}


def test_aggregate_by_usage_unit() -> None:
    totals = aggregate_by_usage_unit(_sample_results())
    assert totals == {
        "Compute:compute-instance-hour:hour": 10.0,
        "Compute:compute-network-egress:gb": 2.0,
        "Database:database-instance-hour:hour": 5.0,
    }


def test_aggregations_on_empty_list() -> None:
    assert aggregate_total([]) == 0.0
    assert aggregate_by_service([]) == {}
    assert aggregate_by_resource([]) == {}
    assert aggregate_by_usage_unit([]) == {}
