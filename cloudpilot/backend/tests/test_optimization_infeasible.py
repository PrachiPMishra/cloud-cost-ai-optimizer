"""Covers the 'no priceable/feasible configuration found' branches of the
three simulate_* functions — exercised by pointing a resource at a region
that has no seeded pricing rows at all, so every tier/pricing-model
combination is rejected via PricingNotFoundError and the simulators must
raise OptimizationInfeasibleError rather than silently returning garbage.
"""

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.forecasting.enums import ForecastHorizon
from app.models.base import SessionLocal
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.optimization.enums import ScenarioType
from app.optimization.scenarios import generate_scenarios
from app.optimization.simulator import simulate_scenario
from app.optimization.solver import OptimizationInfeasibleError
from app.pricing.enums import ServiceType
from app.pricing.seed_data import PROVIDER, REGIONS, seed_pricing
from app.services.optimization_service import build_context

HISTORY_DAYS = 60
UNSEEDED_REGION = "eu-central-1"


@pytest.fixture(scope="module", autouse=True)
def _ensure_seed_data():
    assert UNSEEDED_REGION not in REGIONS
    db = SessionLocal()
    try:
        seed_pricing(db)
    finally:
        db.close()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _hourly_history(base: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
    values = np.clip(base + rng.normal(0, base * 0.1, len(timestamps)), 0, None)
    return pd.Series(values, index=timestamps)


def _make_resource(db, service: ServiceType, prefix: str) -> Resource:
    external_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type=service.value,
        provider=PROVIDER,
        region=UNSEEDED_REGION,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


def _insert_history(db, resource: Resource, usage_type: str, series: pd.Series) -> None:
    db.add_all(
        UsageRecord(
            resource_id=resource.id,
            timestamp=ts.to_pydatetime(),
            usage_type=usage_type,
            quantity=float(v),
            unit="unit",
            provider=resource.provider,
            region=resource.region,
        )
        for ts, v in series.items()
    )
    db.commit()


def _cleanup(db, resource: Resource) -> None:
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_instance_based_simulation_raises_when_region_has_no_pricing(db) -> None:
    resource = _make_resource(db, ServiceType.COMPUTE, "test-infeasible-compute")
    _insert_history(db, resource, "requests", _hourly_history(base=200.0, seed=1))
    _insert_history(db, resource, "network_gb", _hourly_history(base=2.0, seed=2))
    try:
        ctx = build_context(
            db, PROVIDER, resource, ServiceType.COMPUTE, ForecastHorizon.WEEK, 100.0, 0.99, 100000.0
        )
        spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.CURRENT)

        with pytest.raises(OptimizationInfeasibleError):
            simulate_scenario(db, ctx, spec)
    finally:
        _cleanup(db, resource)


def test_storage_based_simulation_raises_when_region_has_no_pricing(db) -> None:
    resource = _make_resource(db, ServiceType.OBJECT_STORAGE, "test-infeasible-objstore")
    _insert_history(db, resource, "requests", _hourly_history(base=8000.0, seed=3))
    _insert_history(db, resource, "network_gb", _hourly_history(base=5.0, seed=4))
    _insert_history(db, resource, "storage_gb", _hourly_history(base=1000.0, seed=5))
    try:
        ctx = build_context(
            db, PROVIDER, resource, ServiceType.OBJECT_STORAGE, ForecastHorizon.WEEK, 100.0, 0.99, 100000.0
        )
        spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.CURRENT)

        with pytest.raises(OptimizationInfeasibleError):
            simulate_scenario(db, ctx, spec)
    finally:
        _cleanup(db, resource)


def test_serverless_simulation_raises_when_region_has_no_pricing(db) -> None:
    resource = _make_resource(db, ServiceType.SERVERLESS, "test-infeasible-serverless")
    _insert_history(db, resource, "requests", _hourly_history(base=2000.0, seed=6))
    _insert_history(db, resource, "network_gb", _hourly_history(base=0.8, seed=7))
    try:
        ctx = build_context(
            db, PROVIDER, resource, ServiceType.SERVERLESS, ForecastHorizon.WEEK, 100.0, 0.99, 100000.0
        )
        spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.CURRENT)

        with pytest.raises(OptimizationInfeasibleError):
            simulate_scenario(db, ctx, spec)
    finally:
        _cleanup(db, resource)


def test_run_optimization_falls_back_to_placeholder_scenarios_when_infeasible(db) -> None:
    from app.models.optimization_run import OptimizationRun
    from app.models.constraint import Constraint
    from app.models.scenario import Scenario
    from app.services.optimization_service import run_optimization

    resource = _make_resource(db, ServiceType.COMPUTE, "test-infeasible-run")
    _insert_history(db, resource, "requests", _hourly_history(base=200.0, seed=8))
    _insert_history(db, resource, "network_gb", _hourly_history(base=2.0, seed=9))
    try:
        summary = run_optimization(
            db,
            provider=PROVIDER,
            resource_external_id=resource.external_id,
            horizon=ForecastHorizon.WEEK,
            max_latency_ms=100.0,
            min_availability=0.99,
            budget=100000.0,
        )

        # Every scenario is infeasible (no pricing for this region), so the
        # service must still return a summary — every scenario placeholder'd
        # out, none satisfying constraints — rather than raising or fabricating.
        assert len(summary.scenarios) == 6
        assert all(not s.constraints_satisfied for s in summary.scenarios)
        assert all(s.predicted_cost == float("inf") for s in summary.scenarios)
    finally:
        run_ids = [r.id for r in db.query(OptimizationRun).all()]
        scenario_ids_touched = set()
        for rid in run_ids:
            run = db.get(OptimizationRun, rid)
            if run.input_snapshot.get("resource_id") == resource.external_id:
                scenario_ids_touched.update(run.result_summary["scenario_ids"])
                db.delete(run)
        db.commit()
        if scenario_ids_touched:
            db.execute(delete(Constraint).where(Constraint.scenario_id.in_(scenario_ids_touched)))
            db.execute(delete(Scenario).where(Scenario.id.in_(scenario_ids_touched)))
        db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
        db.execute(delete(Resource).where(Resource.id == resource.id))
        db.commit()
