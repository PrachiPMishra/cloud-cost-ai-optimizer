"""simulate_scenario(): prices one scenario for one resource.

Dispatches by service:
- Compute/Database: an instance-fleet sizing problem — tier and pricing
  model are enumerated (small, fixed sets), and for each combination
  `app.optimization.solver.solve_instance_schedule` (OR-Tools CP-SAT)
  finds the minimum-cost instance-count schedule meeting capacity (with
  latency/availability targets already folded in as minimums). The
  cheapest feasible (tier, pricing model) combination is returned.
- Object Storage: no instance/capacity concept — provider-managed storage
  is treated as always meeting demand. The only decision is storage tier,
  a 2-option enumeration (no scheduling sub-problem, so no solver call).
- Serverless: no instance/capacity concept either (inherently
  auto-elastic) — the only decision is memory tier, also a small
  enumeration.

Every candidate's cost comes from `app.pricing.calculator.calculate_cost`
— tiers only ever scale the quantity or select the pricing model fed into
it, never invent a price of their own (see `app.optimization.catalog`).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.forecasting.schemas import ForecastRunResult
from app.models.resource import Resource
from app.optimization.catalog import (
    INSTANCE_TIER_CATALOG,
    RESERVED_COMMITMENT_TERMS_MONTHS,
    SERVERLESS_BASE_AVAILABILITY,
    SERVERLESS_BASE_DURATION_HOURS,
    SERVERLESS_BASE_LATENCY_MS,
    SERVERLESS_MEMORY_TIER_CATALOG,
    STORAGE_TIER_CATALOG,
)
from app.optimization.enums import (
    BASELINE_INSTANCE_TIER,
    BASELINE_SERVERLESS_MEMORY_TIER,
    BASELINE_STORAGE_TIER,
    InstanceTier,
    ServerlessMemoryTier,
    StorageTier,
)
from app.optimization.heuristics import (
    estimate_availability,
    estimate_latency_ms,
    min_capacity_for_latency,
    min_instances_for_availability,
)
from app.optimization.schemas import ScenarioResult, ScenarioSpec
from app.optimization.solver import OptimizationInfeasibleError, solve_instance_schedule
from app.pricing.calculator import PricingNotFoundError, calculate_cost
from app.pricing.enums import PricingModel, ServiceType, UsageMode
from app.pricing.schemas import CostCalculationRequest, UsageSample
from app.pricing.skus import SKU_CATALOG


@dataclass
class ScenarioContext:
    service: ServiceType
    resource: Resource
    provider: str
    demand_forecast: ForecastRunResult | None
    storage_forecast: ForecastRunResult | None
    invariant_cost: float
    max_latency_ms: float
    min_availability: float
    budget: float


def _select_best_candidate(
    candidates: list[dict], max_latency_ms: float, min_availability: float
) -> dict:
    """Prefer the cheapest candidate that satisfies latency/availability; if
    none do, fall back to the cheapest overall — `check_constraints` will
    flag the violation, but the scenario still gets a concrete answer
    instead of an optimizer that never even tried to comply."""
    compliant = [
        c
        for c in candidates
        if c["latency_ms"] <= max_latency_ms and c["availability"] >= min_availability
    ]
    pool = compliant if compliant else candidates
    return min(pool, key=lambda c: c["total_cost"])


def simulate_scenario(db: Session, ctx: ScenarioContext, spec: ScenarioSpec) -> ScenarioResult:
    if ctx.service in (ServiceType.COMPUTE, ServiceType.DATABASE):
        return _simulate_instance_based(db, ctx, spec)
    if ctx.service == ServiceType.OBJECT_STORAGE:
        return _simulate_storage_based(db, ctx, spec)
    if ctx.service == ServiceType.SERVERLESS:
        return _simulate_serverless(db, ctx, spec)
    raise ValueError(f"Unsupported service for optimization: {ctx.service}")


def _simulate_instance_based(db: Session, ctx: ScenarioContext, spec: ScenarioSpec) -> ScenarioResult:
    assert ctx.demand_forecast is not None
    demand_per_day = [p.predicted_usage for p in ctx.demand_forecast.points]
    peak_demand = max(demand_per_day)

    tier_options: list[InstanceTier] = (
        list(InstanceTier) if spec.allow_tier_choice else [BASELINE_INSTANCE_TIER]
    )
    pricing_options: list[tuple[PricingModel, int | None]] = [(PricingModel.ON_DEMAND, None)]
    if spec.allow_pricing_model_choice:
        pricing_options += [
            (PricingModel.RESERVED, term) for term in RESERVED_COMMITMENT_TERMS_MONTHS
        ]

    sku, unit = SKU_CATALOG[ctx.service]["hours_used"]
    remaining_budget = ctx.budget - ctx.invariant_cost

    best: dict | None = None
    for tier in tier_options:
        tier_info = INSTANCE_TIER_CATALOG[ctx.service][tier]
        min_instances = min_instances_for_availability(
            tier_info["base_failure_rate"], ctx.min_availability
        )
        effective_demand_per_day = [
            max(d, min_capacity_for_latency(d, tier_info["base_latency_ms"], ctx.max_latency_ms))
            for d in demand_per_day
        ]
        capacity_per_instance_per_day = tier_info["capacity_per_hour"] * 24.0

        for pricing_model, term in pricing_options:
            try:
                base_rate = calculate_cost(
                    CostCalculationRequest(
                        provider=ctx.provider,
                        region=ctx.resource.region,
                        service=ctx.service,
                        sku=sku,
                        unit=unit,
                        pricing_model=pricing_model,
                        commitment_term_months=term,
                        quantity=1.0,
                        resource_id=ctx.resource.external_id,
                    ),
                    db,
                ).cost
            except PricingNotFoundError:
                continue

            effective_hourly_rate = base_rate * tier_info["cost_multiplier"]

            try:
                schedule, solver_status = solve_instance_schedule(
                    demand_per_day=effective_demand_per_day,
                    capacity_per_instance_per_day=capacity_per_instance_per_day,
                    min_instances=min_instances,
                    hourly_rate=effective_hourly_rate,
                    allow_autoscaling=spec.allow_autoscaling,
                    budget=remaining_budget,
                )
            except OptimizationInfeasibleError:
                continue

            instance_hour_cost = calculate_cost(
                CostCalculationRequest(
                    provider=ctx.provider,
                    region=ctx.resource.region,
                    service=ctx.service,
                    sku=sku,
                    unit=unit,
                    pricing_model=pricing_model,
                    commitment_term_months=term,
                    usage_mode=UsageMode.AUTOSCALING,
                    usage_series=[
                        UsageSample(quantity=count * tier_info["cost_multiplier"], duration_hours=24.0)
                        for count in schedule
                    ],
                    resource_id=ctx.resource.external_id,
                ),
                db,
            ).cost

            total_cost = instance_hour_cost + ctx.invariant_cost
            peak_capacity = max(schedule) * capacity_per_instance_per_day
            latency_ms = estimate_latency_ms(tier_info["base_latency_ms"], peak_demand, peak_capacity)
            availability = estimate_availability(tier_info["base_failure_rate"], min(schedule))

            if best is None or total_cost < best["total_cost"]:
                best = dict(
                    tier=tier,
                    pricing_model=pricing_model,
                    commitment_term_months=term,
                    schedule=schedule,
                    solver_status=solver_status,
                    total_cost=total_cost,
                    peak_capacity=peak_capacity,
                    latency_ms=latency_ms,
                    availability=availability,
                )

    if best is None:
        raise OptimizationInfeasibleError(
            f"No tier/pricing-model combination for {ctx.resource.external_id} produced "
            "a feasible schedule"
        )

    return ScenarioResult(
        scenario_type=spec.scenario_type,
        name=spec.name,
        description=spec.description,
        configuration={
            "tier": best["tier"].value,
            "pricing_model": best["pricing_model"].value,
            "commitment_term_months": best["commitment_term_months"],
            "autoscaling": spec.allow_autoscaling,
            "instance_schedule": best["schedule"],
        },
        predicted_demand_peak=peak_demand,
        capacity_provisioned=best["peak_capacity"],
        predicted_cost=best["total_cost"],
        latency_ms=best["latency_ms"],
        availability=best["availability"],
        solver_status=best["solver_status"],
    )


def _simulate_storage_based(db: Session, ctx: ScenarioContext, spec: ScenarioSpec) -> ScenarioResult:
    assert ctx.storage_forecast is not None
    storage_per_day = [p.predicted_usage for p in ctx.storage_forecast.points]
    total_gb_hours = sum(storage_per_day) * 24.0
    peak_storage = max(storage_per_day)

    tier_options: list[StorageTier] = (
        list(StorageTier) if spec.allow_storage_tier_choice else [BASELINE_STORAGE_TIER]
    )
    sku, unit = SKU_CATALOG[ServiceType.OBJECT_STORAGE]["storage_gb"]

    candidates: list[dict] = []
    for tier in tier_options:
        tier_info = STORAGE_TIER_CATALOG[tier]
        try:
            storage_cost = calculate_cost(
                CostCalculationRequest(
                    provider=ctx.provider,
                    region=ctx.resource.region,
                    service=ServiceType.OBJECT_STORAGE,
                    sku=sku,
                    unit=unit,
                    pricing_model=PricingModel.ON_DEMAND,
                    quantity=total_gb_hours * tier_info["sku_multiplier"],
                    resource_id=ctx.resource.external_id,
                ),
                db,
            ).cost
        except PricingNotFoundError:
            continue

        candidates.append(
            dict(
                tier=tier,
                total_cost=storage_cost + ctx.invariant_cost,
                latency_ms=tier_info["base_latency_ms"],
                availability=tier_info["availability"],
            )
        )

    if not candidates:
        raise OptimizationInfeasibleError(
            f"No storage tier for {ctx.resource.external_id} produced a priceable configuration"
        )

    best = _select_best_candidate(candidates, ctx.max_latency_ms, ctx.min_availability)

    return ScenarioResult(
        scenario_type=spec.scenario_type,
        name=spec.name,
        description=spec.description,
        configuration={"storage_tier": best["tier"].value},
        predicted_demand_peak=peak_storage,
        # Object storage capacity is provider-managed and elastic in this
        # model — it always meets demand, so "capacity" trivially equals it.
        capacity_provisioned=peak_storage,
        predicted_cost=best["total_cost"],
        latency_ms=best["latency_ms"],
        availability=best["availability"],
        solver_status="not_applicable_no_scheduling_subproblem",
    )


def _simulate_serverless(db: Session, ctx: ScenarioContext, spec: ScenarioSpec) -> ScenarioResult:
    assert ctx.demand_forecast is not None
    requests_per_day = [p.predicted_usage for p in ctx.demand_forecast.points]
    total_requests = sum(requests_per_day)
    peak_requests = max(requests_per_day)

    tier_options: list[ServerlessMemoryTier] = (
        list(ServerlessMemoryTier) if spec.allow_tier_choice else [BASELINE_SERVERLESS_MEMORY_TIER]
    )
    sku, unit = SKU_CATALOG[ServiceType.SERVERLESS]["hours_used"]

    candidates: list[dict] = []
    for tier in tier_options:
        tier_info = SERVERLESS_MEMORY_TIER_CATALOG[tier]
        duration_hours_per_invocation = SERVERLESS_BASE_DURATION_HOURS * tier_info["duration_multiplier"]
        effective_billable_hours = (
            total_requests * duration_hours_per_invocation * tier_info["cost_multiplier"]
        )

        try:
            duration_cost = calculate_cost(
                CostCalculationRequest(
                    provider=ctx.provider,
                    region=ctx.resource.region,
                    service=ServiceType.SERVERLESS,
                    sku=sku,
                    unit=unit,
                    pricing_model=PricingModel.ON_DEMAND,
                    quantity=effective_billable_hours,
                    resource_id=ctx.resource.external_id,
                ),
                db,
            ).cost
        except PricingNotFoundError:
            continue

        candidates.append(
            dict(
                tier=tier,
                total_cost=duration_cost + ctx.invariant_cost,
                latency_ms=SERVERLESS_BASE_LATENCY_MS * tier_info["duration_multiplier"],
                availability=SERVERLESS_BASE_AVAILABILITY,
            )
        )

    if not candidates:
        raise OptimizationInfeasibleError(
            f"No memory tier for {ctx.resource.external_id} produced a priceable configuration"
        )

    best = _select_best_candidate(candidates, ctx.max_latency_ms, ctx.min_availability)

    return ScenarioResult(
        scenario_type=spec.scenario_type,
        name=spec.name,
        description=spec.description,
        configuration={"memory_tier": best["tier"].value},
        predicted_demand_peak=peak_requests,
        # Serverless is inherently auto-elastic in this model — capacity
        # always meets demand.
        capacity_provisioned=peak_requests,
        predicted_cost=best["total_cost"],
        latency_ms=best["latency_ms"],
        availability=best["availability"],
        solver_status="not_applicable_no_scheduling_subproblem",
    )
