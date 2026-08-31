import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.models.base import SessionLocal
from app.models.constraint import Constraint
from app.models.optimization_run import OptimizationRun
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.models.usage_record import UsageRecord
from app.pricing.enums import ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing

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
    external_id = f"test-opt-api-compute-{uuid.uuid4().hex[:8]}"
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

    rng = np.random.default_rng(21)
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


def test_run_and_get_optimization(client: TestClient, compute_resource) -> None:
    run_response = client.post(
        "/api/optimization/run",
        json={
            "provider": PROVIDER,
            "resource_id": compute_resource.external_id,
            "horizon": "week",
            "max_latency_ms": 100.0,
            "min_availability": 0.99,
            "budget": 100000.0,
        },
    )

    assert run_response.status_code == 200
    body = run_response.json()
    assert len(body["scenarios"]) == 6
    assert body["resource_id"] == compute_resource.external_id

    run_id = body["optimization_run_id"]
    get_response = client.get(f"/api/optimization/{run_id}")

    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["optimization_run_id"] == run_id
    assert fetched["chosen_scenario_id"] == body["chosen_scenario_id"]


def test_run_optimization_unknown_resource_404(client: TestClient) -> None:
    response = client.post(
        "/api/optimization/run",
        json={
            "provider": PROVIDER,
            "resource_id": "nope",
            "horizon": "day",
            "max_latency_ms": 100.0,
            "min_availability": 0.99,
            "budget": 1000.0,
        },
    )
    assert response.status_code == 404


def test_get_optimization_unknown_id_404(client: TestClient) -> None:
    response = client.get("/api/optimization/999999999")
    assert response.status_code == 404


def test_run_optimization_rejects_invalid_availability(client: TestClient, compute_resource) -> None:
    response = client.post(
        "/api/optimization/run",
        json={
            "provider": PROVIDER,
            "resource_id": compute_resource.external_id,
            "horizon": "day",
            "max_latency_ms": 100.0,
            "min_availability": 1.5,
            "budget": 1000.0,
        },
    )
    assert response.status_code == 422
