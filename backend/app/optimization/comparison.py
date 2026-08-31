"""compare_scenarios(): pure ranking over already-simulated scenario
results — no solving, no pricing, no DB access. Shared by
`app.services.optimization_service.run_optimization` (which already has
per-scenario constraint checks in hand) and the Phase 7 `compare_scenarios`
tool (which can supply checks too, or let this compute them itself).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.optimization.constraints import check_constraints
from app.optimization.enums import ScenarioType
from app.optimization.schemas import ConstraintCheck, ScenarioResult


class RankedScenario(BaseModel):
    scenario_type: ScenarioType
    name: str
    predicted_cost: float
    constraints_satisfied: bool
    savings_vs_current: float


class ScenarioComparison(BaseModel):
    ranked: list[RankedScenario]
    cheapest_feasible_scenario_type: ScenarioType | None
    fully_feasible: bool


def compare_scenarios(
    results: list[ScenarioResult],
    *,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
    checks_by_scenario_type: dict[ScenarioType, list[ConstraintCheck]] | None = None,
) -> ScenarioComparison:
    if not results:
        raise ValueError("results must not be empty")

    if checks_by_scenario_type is None:
        checks_by_scenario_type = {
            r.scenario_type: check_constraints(
                r, max_latency_ms=max_latency_ms, min_availability=min_availability, budget=budget
            )
            for r in results
        }

    current = next((r for r in results if r.scenario_type == ScenarioType.CURRENT), None)
    current_cost = current.predicted_cost if current is not None else None

    ranked = [
        RankedScenario(
            scenario_type=r.scenario_type,
            name=r.name,
            predicted_cost=r.predicted_cost,
            constraints_satisfied=all(c.satisfied for c in checks_by_scenario_type.get(r.scenario_type, [])),
            savings_vs_current=(current_cost - r.predicted_cost) if current_cost is not None else 0.0,
        )
        for r in sorted(results, key=lambda r: r.predicted_cost)
    ]

    feasible = [r for r in ranked if r.constraints_satisfied]
    if feasible:
        cheapest_feasible = min(feasible, key=lambda r: r.predicted_cost).scenario_type
        fully_feasible = True
    else:
        cheapest_feasible = None
        fully_feasible = False

    return ScenarioComparison(
        ranked=ranked,
        cheapest_feasible_scenario_type=cheapest_feasible,
        fully_feasible=fully_feasible,
    )
