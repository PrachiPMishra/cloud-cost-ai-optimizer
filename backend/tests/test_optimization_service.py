import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.forecasting.enums import ForecastHorizon
from app.models.base import SessionLocal
from app.models.constraint import Constraint
from app.models.optimization_run import OptimizationRun
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.models.usage_record import UsageRecord
from app.optimization.enums import ScenarioType
from app.pricing.enums import ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.services.optimization_service import (
    ResourceNotFoundError,
    get_optimization_run,
    run_optimization,
)
from app.services.optimization_service import OptimizationRunNotFoundError

HISTORY_DAYS = 60


@pytest.fixture(scope="module", autouse=True)
def _ensure_seed_data():
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


@pytest.fixture()
def compute_resource(db):
    external_id = f"test-opt-svc-compute-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type=ServiceType.COMPUTE.value,
        provider=PROVIDER,
        region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    rng = np.random.default_rng(11)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
    for usage_type, base in (("requests", 200.0), ("network_gb", 2.0)):
        values = np.clip(base + rng.normal(0, base * 0.1, len(timestamps)), 0, None)
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
            for ts, v in zip(timestamps, values)
        )
    db.commit()

    yield resource

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


def test_run_optimization_persists_all_scenarios_and_constraints(db, compute_resource) -> None:
    summary = run_optimization(
        db,
        provider=PROVIDER,
        resource_external_id=compute_resource.external_id,
        horizon=ForecastHorizon.WEEK,
        max_latency_ms=100.0,
        min_availability=0.99,
        budget=100000.0,
    )

    assert len(summary.scenarios) == 6
    scenario_types = {s.scenario_type for s in summary.scenarios}
    assert scenario_types == set(ScenarioType)

    run_row = db.get(OptimizationRun, summary.optimization_run_id)
    assert run_row is not None
    assert run_row.objective == "minimize_cost"
    assert run_row.scenario_id == summary.chosen_scenario_id

    for s in summary.scenarios:
        scenario_row = db.get(Scenario, s.scenario_id)
        assert scenario_row is not None
        constraint_rows = (
            db.query(Constraint).filter(Constraint.scenario_id == s.scenario_id).all()
        )
        assert {c.constraint_type for c in constraint_rows} == {
            "capacity", "latency", "availability", "budget"
        }

    chosen = next(s for s in summary.scenarios if s.scenario_id == summary.chosen_scenario_id)
    assert chosen.predicted_cost == pytest.approx(
        min(s.predicted_cost for s in summary.scenarios if s.constraints_satisfied)
    )


def test_get_optimization_run_round_trips(db, compute_resource) -> None:
    summary = run_optimization(
        db,
        provider=PROVIDER,
        resource_external_id=compute_resource.external_id,
        horizon=ForecastHorizon.DAY,
        max_latency_ms=100.0,
        min_availability=0.99,
        budget=100000.0,
    )

    fetched = get_optimization_run(db, summary.optimization_run_id)

    assert fetched.optimization_run_id == summary.optimization_run_id
    assert fetched.chosen_scenario_id == summary.chosen_scenario_id
    assert fetched.savings_vs_current == pytest.approx(summary.savings_vs_current)
    assert len(fetched.scenarios) == len(summary.scenarios)


def test_run_optimization_unknown_resource_raises(db) -> None:
    with pytest.raises(ResourceNotFoundError):
        run_optimization(
            db,
            provider=PROVIDER,
            resource_external_id="does-not-exist",
            horizon=ForecastHorizon.DAY,
            max_latency_ms=100.0,
            min_availability=0.99,
            budget=1000.0,
        )


def test_get_optimization_run_unknown_id_raises(db) -> None:
    with pytest.raises(OptimizationRunNotFoundError):
        get_optimization_run(db, 999999999)


def test_impossible_budget_yields_not_fully_feasible(db, compute_resource) -> None:
    summary = run_optimization(
        db,
        provider=PROVIDER,
        resource_external_id=compute_resource.external_id,
        horizon=ForecastHorizon.MONTH,
        max_latency_ms=100.0,
        min_availability=0.99,
        budget=0.0001,
    )

    assert summary.fully_feasible is False
    chosen = next(s for s in summary.scenarios if s.scenario_id == summary.chosen_scenario_id)
    assert any(c.constraint_type == "budget" and not c.satisfied for c in chosen.constraint_checks)
