"""OR-Tools CP-SAT capacity-schedule solver.

Decides, for each day in the horizon, how many instances of a given tier
to run so that capacity meets demand at minimum total instance-hours,
optionally under a hard budget. Latency and availability targets are not
modeled as nonlinear constraints here — the caller folds them into
`demand_per_day` (via `heuristics.min_capacity_for_latency`) and
`min_instances` (via `heuristics.min_instances_for_availability`) first,
so the schedule this solver returns satisfies capacity, latency, and
availability by construction; only budget is an explicit solver
constraint (and is dropped and re-solved without it, with the violation
left for `check_constraints` to report, if it makes the problem
infeasible).

When `allow_autoscaling` is False, every day is forced to run the same
instance count — i.e. peak-provisioned for the whole period.
"""

from __future__ import annotations

import math

from ortools.sat.python import cp_model

COST_SCALE = 1_000_000  # integer micro-dollars, since CP-SAT needs integer coefficients
MAX_INSTANCES = 2000


class OptimizationInfeasibleError(Exception):
    pass


def solve_instance_schedule(
    demand_per_day: list[float],
    capacity_per_instance_per_day: float,
    min_instances: int,
    hourly_rate: float,
    hours_per_day: float = 24.0,
    allow_autoscaling: bool = False,
    max_daily_step: int = 25,
    budget: float | None = None,
) -> tuple[list[int], str]:
    if not demand_per_day:
        raise ValueError("demand_per_day must be non-empty")

    n_days = len(demand_per_day)

    min_counts = []
    for demand in demand_per_day:
        needed = (
            math.ceil(demand / capacity_per_instance_per_day)
            if capacity_per_instance_per_day > 0
            else min_instances
        )
        min_counts.append(max(needed, min_instances, 0))

    scaled_rate = round(hourly_rate * hours_per_day * COST_SCALE)

    def _build_and_solve(with_budget: bool):
        m = cp_model.CpModel()
        c = [m.NewIntVar(min_counts[d], MAX_INSTANCES, f"count_{d}") for d in range(n_days)]
        if not allow_autoscaling:
            for d in range(1, n_days):
                m.Add(c[d] == c[0])
        else:
            for d in range(1, n_days):
                m.Add(c[d] - c[d - 1] <= max_daily_step)
                m.Add(c[d - 1] - c[d] <= max_daily_step)
        cost_expr = sum(c) * scaled_rate
        if with_budget and budget is not None:
            m.Add(cost_expr <= round(budget * COST_SCALE))
        m.Minimize(cost_expr)

        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = 5.0
        status = s.Solve(m)
        return s, c, status

    solver, solved_counts, status = _build_and_solve(with_budget=budget is not None)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if budget is not None:
            # Retry without the budget constraint so we still return a
            # concrete capacity/latency/availability-compliant schedule;
            # the caller's constraint check will flag the budget as violated.
            solver, solved_counts, status = _build_and_solve(with_budget=False)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise OptimizationInfeasibleError(
                "No feasible instance schedule found even without a budget "
                f"constraint (solver status={solver.StatusName(status)})"
            )

    schedule = [solver.Value(c) for c in solved_counts]
    return schedule, solver.StatusName(status)
