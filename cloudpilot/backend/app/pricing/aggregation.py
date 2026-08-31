"""Pure aggregation helpers over a list of CostCalculationResult.

No DB access and no pricing logic here — just grouping and summing
already-computed results, kept separate so callers can aggregate results
from any source (a single calculation, a batch job, a forecast run).
"""

from __future__ import annotations

from collections import defaultdict

from app.pricing.schemas import CostCalculationResult


def aggregate_total(results: list[CostCalculationResult]) -> float:
    return sum(r.cost for r in results)


def aggregate_by_service(results: list[CostCalculationResult]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for r in results:
        totals[r.service.value] += r.cost
    return dict(totals)


def aggregate_by_resource(results: list[CostCalculationResult]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for r in results:
        key = r.resource_id if r.resource_id is not None else "__unassigned__"
        totals[key] += r.cost
    return dict(totals)


def aggregate_by_usage_unit(results: list[CostCalculationResult]) -> dict[str, float]:
    """Group by (service, sku, unit) — i.e. by kind of billed usage."""
    totals: dict[str, float] = defaultdict(float)
    for r in results:
        key = f"{r.service.value}:{r.sku}:{r.unit}"
        totals[key] += r.cost
    return dict(totals)
