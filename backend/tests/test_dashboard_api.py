import json
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.optimization_run import OptimizationRun
from app.models.resource import Resource
from app.models.scenario import Scenario
from app.models.constraint import Constraint
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
    external_id = f"test-dash-compute-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id, name=external_id, resource_type=ServiceType.COMPUTE.value,
        provider=PROVIDER, region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    rng = np.random.default_rng(1)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=1),
        periods=HISTORY_DAYS * 24, freq="h",
    )
    for usage_type, base in (("requests", 200.0), ("hours_used", 1.0), ("network_gb", 2.0)):
        values = np.clip(base + rng.normal(0, base * 0.05, len(timestamps)), 0, None)
        db.add_all(
            UsageRecord(
                resource_id=resource.id, timestamp=ts.to_pydatetime(), usage_type=usage_type,
                quantity=float(v), unit="unit", provider=resource.provider, region=resource.region,
            )
            for ts, v in zip(timestamps, values)
        )
    db.commit()

    yield resource

    forecast_ids = [f.id for f in db.query(Forecast).all() if f.resource_id == resource.id]
    if forecast_ids:
        db.execute(delete(CostPrediction).where(CostPrediction.forecast_id.in_(forecast_ids)))
        db.execute(delete(Forecast).where(Forecast.id.in_(forecast_ids)))
    run_ids = [
        r.id for r in db.query(OptimizationRun).all() if r.input_snapshot.get("resource_id") == resource.external_id
    ]
    scenario_ids_touched = set()
    for rid in run_ids:
        run = db.get(OptimizationRun, rid)
        scenario_ids_touched.update(run.result_summary["scenario_ids"])
        db.delete(run)
    db.commit()
    if scenario_ids_touched:
        db.execute(delete(Constraint).where(Constraint.scenario_id.in_(scenario_ids_touched)))
        db.execute(delete(Scenario).where(Scenario.id.in_(scenario_ids_touched)))
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_list_resources(client: TestClient, compute_resource) -> None:
    response = client.get("/api/resources", params={"provider": PROVIDER, "service": "Compute"})
    assert response.status_code == 200
    body = response.json()
    assert any(r["resource_id"] == compute_resource.external_id for r in body["resources"])


def test_usage_history_endpoint(client: TestClient, compute_resource) -> None:
    response = client.get(
        "/api/usage/history", params={"resource_id": compute_resource.external_id, "usage_type": "requests"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["points"]) > 0


def test_usage_history_404_for_unknown_resource(client: TestClient) -> None:
    response = client.get("/api/usage/history", params={"resource_id": "nope", "usage_type": "requests"})
    assert response.status_code == 404


def test_current_cost_endpoint(client: TestClient, compute_resource) -> None:
    response = client.get(
        "/api/cost/current", params={"provider": PROVIDER, "resource_id": compute_resource.external_id}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["line_items"]) > 0


def test_cost_drivers_endpoint(client: TestClient, compute_resource) -> None:
    response = client.get(
        "/api/cost/drivers",
        params={"provider": PROVIDER, "resource_id": compute_resource.external_id, "source": "current", "top_n": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_cost"] > 0
    assert len(body["drivers"]) > 0


def test_cost_drivers_forecasted_requires_horizon(client: TestClient, compute_resource) -> None:
    response = client.get(
        "/api/cost/drivers",
        params={"provider": PROVIDER, "resource_id": compute_resource.external_id, "source": "forecasted"},
    )
    assert response.status_code == 422


def test_cost_drivers_forecasted_source(client: TestClient, compute_resource) -> None:
    response = client.get(
        "/api/cost/drivers",
        params={
            "provider": PROVIDER,
            "resource_id": compute_resource.external_id,
            "source": "forecasted",
            "horizon": "week",
            "top_n": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_cost"] > 0
    assert len(body["drivers"]) > 0


def test_forecast_accuracy_returns_404_when_nothing_backfilled(client: TestClient) -> None:
    response = client.get("/api/forecast/accuracy", params={"resource_id": "nonexistent-resource-xyz"})
    assert response.status_code == 404


def test_optimization_latest_and_get(client: TestClient, compute_resource) -> None:
    run_response = client.post(
        "/api/optimization/run",
        json={
            "provider": PROVIDER, "resource_id": compute_resource.external_id, "horizon": "week",
            "max_latency_ms": 100.0, "min_availability": 0.99, "budget": 100000.0,
        },
    )
    assert run_response.status_code == 200
    run_id = run_response.json()["optimization_run_id"]

    latest_response = client.get("/api/optimization/latest", params={"resource_id": compute_resource.external_id})
    assert latest_response.status_code == 200
    assert latest_response.json()["optimization_run_id"] == run_id


def test_optimization_latest_404_when_none_exist(client: TestClient) -> None:
    response = client.get("/api/optimization/latest", params={"resource_id": "no-runs-for-this-one-xyz"})
    assert response.status_code == 404


def test_settings_endpoint(client: TestClient) -> None:
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["database_connected"] is True
    assert "gemini_model" in body
    assert isinstance(body["gemini_configured"], bool)
    # Display-only USD->INR rate (app/services/currency.py) — exposed so the
    # frontend can reformat already-fetched USD figures client-side.
    assert isinstance(body["usd_to_inr_rate"], (int, float))
    assert body["usd_to_inr_rate"] > 0


def test_agent_run_streams_progress_and_events_are_queryable(client: TestClient, compute_resource, db) -> None:
    with client.stream(
        "POST",
        "/api/agent/run",
        json={
            "user_query": "optimize this resource",
            "provider": PROVIDER,
            "resource_id": compute_resource.external_id,
            "usage_type": "requests",
            "horizon": "day",
            "max_latency_ms": 100.0,
            "min_availability": 0.99,
            "budget": 100000.0,
        },
    ) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    assert events[0]["_meta"]["event"] == "started"
    session_id = events[0]["_meta"]["session_id"]
    assert events[-1]["_meta"]["event"] == "done"

    node_names = {list(e.keys())[0] for e in events if "_meta" not in e}
    assert "planner" in node_names
    assert "forecast" in node_names
    assert "report" in node_names

    events_response = client.get("/api/agent/events", params={"session_id": session_id})
    assert events_response.status_code == 200
    tool_calls = events_response.json()["events"]
    assert len(tool_calls) > 0
    assert any(e["tool_name"] == "forecast_usage" for e in tool_calls)

    sessions_response = client.get("/api/agent/sessions", params={"limit": 5})
    assert sessions_response.status_code == 200
    assert any(s["session_id"] == session_id for s in sessions_response.json()["sessions"])

    db.execute(delete(AgentEvent).where(AgentEvent.session_id == session_id))
    db.commit()
