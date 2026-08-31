"""Orchestrates one optimization run: forecast demand for a resource, run
every scenario from `app.optimization.generate_scenarios` through
`simulate_scenario`, check each against the caller's constraints, persist
everything to `optimization_runs` / `scenarios` / `constraints`, and pick
the lowest-cost scenario among the ones that satisfy every constraint (or,
if none do, the lowest-cost scenario overall — flagged as not fully
feasible rather than silently presented as a clean win).

Database's storage cost is included (at the standard tier, held constant
across scenarios) so its total predicted cost stays realistic for the
budget constraint — but this phase's `storage_optimization` scenario only
exercises the storage-tier lever for Object Storage. Extending it to
Database storage is a natural follow-up, not implemented here.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.data import NoHistoricalDataError, load_daily_series
from app.forecasting.engine import InsufficientHistoryError, run_forecast
from app.forecasting.enums import ForecastHorizon
from app.models.constraint import Constraint
from app.models.optimization_run import OptimizationRun
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.optimization.comparison import compare_scenarios
from app.optimization.constraints import check_constraints
from app.optimization.enums import ScenarioType
from app.optimization.scenarios import generate_scenarios
from app.optimization.schemas import ConstraintCheck, ScenarioResult
from app.optimization.simulator import ScenarioContext, simulate_scenario
from app.optimization.solver import OptimizationInfeasibleError
from app.pricing.calculator import PricingNotFoundError, calculate_cost
from app.pricing.enums import PricingModel, ServiceType
from app.pricing.schemas import CostCalculationRequest
from app.pricing.skus import SKU_CATALOG


class ResourceNotFoundError(Exception):
    pass


class UnsupportedServiceError(Exception):
    pass


class InsufficientDemandDataError(Exception):
    pass


class OptimizationRunNotFoundError(Exception):
    pass


class ScenarioSummary(BaseModel):
    scenario_id: int
    scenario_type: ScenarioType
    name: str
    description: str
    configuration: dict
    predicted_demand_peak: float
    capacity_provisioned: float
    predicted_cost: float
    latency_ms: float
    availability: float
    solver_status: str
    constraints_satisfied: bool
    constraint_checks: list[ConstraintCheck]


class OptimizationRunSummary(BaseModel):
    optimization_run_id: int
    resource_id: str
    service: str
    provider: str
    horizon_days: int
    max_latency_ms: float
    min_availability: float
    budget: float
    chosen_scenario_id: int
    fully_feasible: bool
    savings_vs_current: float
    scenarios: list[ScenarioSummary]
    generated_at: datetime


def _forecast_or_none(db: Session, resource: Resource, usage_type: str, horizon: ForecastHorizon):
    try:
        series = load_daily_series(db, resource, usage_type)
        return run_forecast(series, resource.external_id, usage_type, horizon)
    except (NoHistoricalDataError, InsufficientHistoryError):
        return None


def _flat_cost_or_zero(
    db: Session, provider: str, resource: Resource, service: ServiceType, sku: str, unit: str, quantity: float
) -> float:
    try:
        return calculate_cost(
            CostCalculationRequest(
                provider=provider,
                region=resource.region,
                service=service,
                sku=sku,
                unit=unit,
                pricing_model=PricingModel.ON_DEMAND,
                quantity=quantity,
                resource_id=resource.external_id,
            ),
            db,
        ).cost
    except PricingNotFoundError:
        return 0.0


def build_context(
    db: Session,
    provider: str,
    resource: Resource,
    service: ServiceType,
    horizon: ForecastHorizon,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
) -> ScenarioContext:
    invariant_cost = 0.0
    demand_forecast = None
    storage_forecast = None

    network_forecast = _forecast_or_none(db, resource, "network_gb", horizon)
    if network_forecast is not None and "network_gb" in SKU_CATALOG.get(service, {}):
        sku, unit = SKU_CATALOG[service]["network_gb"]
        total = sum(p.predicted_usage for p in network_forecast.points)
        invariant_cost += _flat_cost_or_zero(db, provider, resource, service, sku, unit, total)

    if service in (ServiceType.COMPUTE, ServiceType.DATABASE, ServiceType.SERVERLESS):
        demand_forecast = _forecast_or_none(db, resource, "requests", horizon)
        if demand_forecast is None:
            raise InsufficientDemandDataError(
                f"Not enough 'requests' history for {resource.external_id} to optimize"
            )

    if service == ServiceType.DATABASE:
        sku, unit = SKU_CATALOG[ServiceType.DATABASE]["requests"]
        total = sum(p.predicted_usage for p in demand_forecast.points)
        invariant_cost += _flat_cost_or_zero(db, provider, resource, service, sku, unit, total)

        db_storage_forecast = _forecast_or_none(db, resource, "storage_gb", horizon)
        if db_storage_forecast is not None:
            sku, unit = SKU_CATALOG[ServiceType.DATABASE]["storage_gb"]
            total_gb_hours = sum(p.predicted_usage for p in db_storage_forecast.points) * 24.0
            invariant_cost += _flat_cost_or_zero(db, provider, resource, service, sku, unit, total_gb_hours)

    if service == ServiceType.OBJECT_STORAGE:
        requests_forecast = _forecast_or_none(db, resource, "requests", horizon)
        if requests_forecast is not None:
            sku, unit = SKU_CATALOG[ServiceType.OBJECT_STORAGE]["requests"]
            total = sum(p.predicted_usage for p in requests_forecast.points)
            invariant_cost += _flat_cost_or_zero(db, provider, resource, service, sku, unit, total)

        storage_forecast = _forecast_or_none(db, resource, "storage_gb", horizon)
        if storage_forecast is None:
            raise InsufficientDemandDataError(
                f"Not enough 'storage_gb' history for {resource.external_id} to optimize"
            )

    if service == ServiceType.SERVERLESS:
        sku, unit = SKU_CATALOG[ServiceType.SERVERLESS]["requests"]
        total = sum(p.predicted_usage for p in demand_forecast.points)
        invariant_cost += _flat_cost_or_zero(db, provider, resource, service, sku, unit, total)

    return ScenarioContext(
        service=service,
        resource=resource,
        provider=provider,
        demand_forecast=demand_forecast,
        storage_forecast=storage_forecast,
        invariant_cost=invariant_cost,
        max_latency_ms=max_latency_ms,
        min_availability=min_availability,
        budget=budget,
    )


def _db_safe_float(value: float) -> float | None:
    """Neither Postgres' JSON columns (which reject the non-standard
    `Infinity`/`NaN` tokens Python's json encoder emits) nor its NUMERIC
    columns (which have no representation for non-finite values at all)
    can store `inf`/`nan`. The infeasible-placeholder scenario's cost and
    latency are `inf` by design (see `_infeasible_placeholder`), so any
    non-finite value must be swapped for `None` before storage, and
    restored by the caller on read-back."""
    return value if math.isfinite(value) else None


def _infeasible_placeholder(spec) -> ScenarioResult:
    return ScenarioResult(
        scenario_type=spec.scenario_type,
        name=spec.name,
        description=spec.description,
        configuration={"error": "no feasible configuration found"},
        predicted_demand_peak=0.0,
        capacity_provisioned=0.0,
        predicted_cost=float("inf"),
        latency_ms=float("inf"),
        availability=0.0,
        solver_status="INFEASIBLE",
    )


def run_optimization(
    db: Session,
    *,
    provider: str,
    resource_external_id: str,
    horizon: ForecastHorizon,
    max_latency_ms: float,
    min_availability: float,
    budget: float,
) -> OptimizationRunSummary:
    resource = db.query(Resource).filter(Resource.external_id == resource_external_id).first()
    if resource is None:
        raise ResourceNotFoundError(f"No resource with external_id={resource_external_id!r}")

    try:
        service = ServiceType(resource.resource_type)
    except ValueError as exc:
        raise UnsupportedServiceError(
            f"Unsupported resource_type {resource.resource_type!r} for optimization"
        ) from exc

    ctx = build_context(db, provider, resource, service, horizon, max_latency_ms, min_availability, budget)

    specs = generate_scenarios()
    results: list[ScenarioResult] = []
    for spec in specs:
        try:
            results.append(simulate_scenario(db, ctx, spec))
        except OptimizationInfeasibleError:
            results.append(_infeasible_placeholder(spec))

    scenario_rows: list[Scenario] = []
    checks_by_index: list[list[ConstraintCheck]] = []

    for spec, result in zip(specs, results):
        scenario_row = Scenario(
            name=result.name,
            description=result.description,
            created_by="optimization_engine",
            parameters={
                "scenario_type": result.scenario_type.value,
                "configuration": result.configuration,
                "predicted_demand_peak": result.predicted_demand_peak,
                "capacity_provisioned": result.capacity_provisioned,
                "predicted_cost": _db_safe_float(result.predicted_cost),
                "latency_ms": _db_safe_float(result.latency_ms),
                "availability": result.availability,
                "solver_status": result.solver_status,
            },
        )
        db.add(scenario_row)
        db.flush()
        scenario_rows.append(scenario_row)

        checks = check_constraints(
            result, max_latency_ms=max_latency_ms, min_availability=min_availability, budget=budget
        )
        checks_by_index.append(checks)
        for check in checks:
            db.add(
                Constraint(
                    scenario_id=scenario_row.id,
                    constraint_type=check.constraint_type,
                    resource_type=resource.resource_type,
                    value={
                        "threshold": _db_safe_float(check.threshold),
                        "actual": _db_safe_float(check.actual),
                        "satisfied": check.satisfied,
                    },
                    description=check.description,
                )
            )

    db.flush()

    checks_by_scenario_type = {
        specs[i].scenario_type: checks_by_index[i] for i in range(len(specs))
    }
    comparison = compare_scenarios(
        results,
        max_latency_ms=max_latency_ms,
        min_availability=min_availability,
        budget=budget,
        checks_by_scenario_type=checks_by_scenario_type,
    )
    fully_feasible = comparison.fully_feasible

    if comparison.cheapest_feasible_scenario_type is not None:
        chosen_index = next(
            i for i, spec in enumerate(specs) if spec.scenario_type == comparison.cheapest_feasible_scenario_type
        )
    else:
        chosen_index = min(range(len(results)), key=lambda i: results[i].predicted_cost)

    current_index = next(i for i, spec in enumerate(specs) if spec.scenario_type == ScenarioType.CURRENT)
    savings_vs_current = results[current_index].predicted_cost - results[chosen_index].predicted_cost

    now = datetime.now(timezone.utc)
    optimization_run = OptimizationRun(
        scenario_id=scenario_rows[chosen_index].id,
        status="completed",
        objective="minimize_cost",
        solver_status=results[chosen_index].solver_status,
        objective_value=_db_safe_float(results[chosen_index].predicted_cost),
        input_snapshot={
            "provider": provider,
            "resource_id": resource.external_id,
            "service": service.value,
            "horizon_days": horizon.days,
            "max_latency_ms": max_latency_ms,
            "min_availability": min_availability,
            "budget": budget,
        },
        result_summary={
            "chosen_scenario_id": scenario_rows[chosen_index].id,
            "fully_feasible": fully_feasible,
            "savings_vs_current": _db_safe_float(savings_vs_current),
            "scenario_ids": [row.id for row in scenario_rows],
        },
        started_at=now,
        completed_at=now,
    )
    db.add(optimization_run)
    db.commit()
    db.refresh(optimization_run)

    constraint_checks_by_scenario_id = {
        scenario_rows[i].id: checks_by_index[i] for i in range(len(scenario_rows))
    }

    return _build_summary(
        run=optimization_run,
        resource_external_id=resource.external_id,
        service=service.value,
        scenario_rows=scenario_rows,
        constraint_checks_by_scenario_id=constraint_checks_by_scenario_id,
    )


def _build_summary(
    *,
    run: OptimizationRun,
    resource_external_id: str,
    service: str,
    scenario_rows: list[Scenario],
    constraint_checks_by_scenario_id: dict[int, list[ConstraintCheck]],
) -> OptimizationRunSummary:
    scenario_summaries = []
    for row in scenario_rows:
        params = row.parameters
        checks = constraint_checks_by_scenario_id.get(row.id, [])
        scenario_summaries.append(
            ScenarioSummary(
                scenario_id=row.id,
                scenario_type=ScenarioType(params["scenario_type"]),
                name=row.name,
                description=row.description,
                configuration=params["configuration"],
                predicted_demand_peak=params["predicted_demand_peak"],
                capacity_provisioned=params["capacity_provisioned"],
                # None on read-back means "stored as non-finite" (see
                # _db_safe_float) — an infeasible scenario's cost/latency
                # really is unboundedly bad, not zero or missing.
                predicted_cost=params["predicted_cost"] if params["predicted_cost"] is not None else float("inf"),
                latency_ms=params["latency_ms"] if params["latency_ms"] is not None else float("inf"),
                availability=params["availability"],
                solver_status=params["solver_status"],
                constraints_satisfied=all(c.satisfied for c in checks),
                constraint_checks=checks,
            )
        )

    input_snapshot = run.input_snapshot
    result_summary = run.result_summary

    # Recomputed from the (already sentinel-restored) scenario summaries
    # rather than trusting the stored value directly: when either side was
    # non-finite it was persisted as null (see _db_safe_float), so
    # deriving it fresh is simpler than un-sanitizing a second field and
    # stays consistent with what scenario_summaries now says.
    current_summary = next(
        (s for s in scenario_summaries if s.scenario_type == ScenarioType.CURRENT), None
    )
    chosen_summary = next(
        (s for s in scenario_summaries if s.scenario_id == result_summary["chosen_scenario_id"]), None
    )
    if current_summary is not None and chosen_summary is not None:
        savings_vs_current = current_summary.predicted_cost - chosen_summary.predicted_cost
        if not math.isfinite(savings_vs_current):
            savings_vs_current = 0.0
    else:
        savings_vs_current = 0.0

    return OptimizationRunSummary(
        optimization_run_id=run.id,
        resource_id=resource_external_id,
        service=service,
        provider=input_snapshot["provider"],
        horizon_days=input_snapshot["horizon_days"],
        max_latency_ms=input_snapshot["max_latency_ms"],
        min_availability=input_snapshot["min_availability"],
        budget=input_snapshot["budget"],
        chosen_scenario_id=result_summary["chosen_scenario_id"],
        fully_feasible=result_summary["fully_feasible"],
        savings_vs_current=savings_vs_current,
        scenarios=scenario_summaries,
        generated_at=run.created_at,
    )


def get_optimization_run(db: Session, optimization_run_id: int) -> OptimizationRunSummary:
    run = db.get(OptimizationRun, optimization_run_id)
    if run is None:
        raise OptimizationRunNotFoundError(f"No optimization run with id={optimization_run_id}")
    return _load_summary_from_run(db, run)


def get_latest_optimization_run(
    db: Session, resource_external_id: str | None = None
) -> OptimizationRunSummary:
    query = db.query(OptimizationRun)
    if resource_external_id:
        # resource_id lives inside input_snapshot JSON, not a column — filter in Python
        # since the result set of optimization runs is small enough for this to be fine.
        candidates = query.order_by(OptimizationRun.created_at.desc()).all()
        run = next(
            (r for r in candidates if r.input_snapshot.get("resource_id") == resource_external_id), None
        )
    else:
        run = query.order_by(OptimizationRun.created_at.desc()).first()

    if run is None:
        raise OptimizationRunNotFoundError("No optimization runs have been generated yet")
    return _load_summary_from_run(db, run)


def _load_summary_from_run(db: Session, run: OptimizationRun) -> OptimizationRunSummary:
    scenario_ids = run.result_summary["scenario_ids"]
    scenario_rows = (
        db.query(Scenario).filter(Scenario.id.in_(scenario_ids)).all()
    )
    scenario_rows.sort(key=lambda row: scenario_ids.index(row.id))

    constraint_rows = db.query(Constraint).filter(Constraint.scenario_id.in_(scenario_ids)).all()
    constraint_checks_by_scenario_id: dict[int, list[ConstraintCheck]] = {}
    for c in constraint_rows:
        constraint_checks_by_scenario_id.setdefault(c.scenario_id, []).append(
            ConstraintCheck(
                constraint_type=c.constraint_type,
                # None on read-back means "stored as non-finite" (see
                # _db_safe_float) — restore it rather than pretend a
                # violating scenario's actual value was 0.
                threshold=c.value["threshold"] if c.value["threshold"] is not None else float("inf"),
                actual=c.value["actual"] if c.value["actual"] is not None else float("inf"),
                satisfied=c.value["satisfied"],
                description=c.description,
            )
        )

    # resource_id/service aren't stored on Scenario; they live in the run's input_snapshot.
    resource_external_id = run.input_snapshot["resource_id"]
    service = run.input_snapshot["service"]

    return _build_summary(
        run=run,
        resource_external_id=resource_external_id,
        service=service,
        scenario_rows=scenario_rows,
        constraint_checks_by_scenario_id=constraint_checks_by_scenario_id,
    )
