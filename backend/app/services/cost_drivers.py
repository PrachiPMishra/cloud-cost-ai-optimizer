"""Generic cost-driver ranking: given (label, cost) pairs from any already
-priced source (current usage cost, forecasted bill cost, ...), rank by
contribution to total. Pure ranking/arithmetic — no pricing or forecasting
decisions live here, so it works identically regardless of where the
costs came from.
"""

from __future__ import annotations

from pydantic import BaseModel


class CostDriver(BaseModel):
    label: str
    cost: float
    pct_of_total: float


class CostDriverReport(BaseModel):
    total_cost: float
    drivers: list[CostDriver]


def rank_cost_drivers(items: list[tuple[str, float]], top_n: int = 5) -> CostDriverReport:
    total = sum(cost for _, cost in items)
    ranked_items = sorted(items, key=lambda pair: pair[1], reverse=True)[:top_n]

    drivers = [
        CostDriver(
            label=label,
            cost=cost,
            pct_of_total=(cost / total * 100.0) if total > 0 else 0.0,
        )
        for label, cost in ranked_items
    ]
    return CostDriverReport(total_cost=total, drivers=drivers)
