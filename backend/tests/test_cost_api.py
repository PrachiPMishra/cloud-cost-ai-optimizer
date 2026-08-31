import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.models.base import SessionLocal
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
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
def database_resource(db):
    external_id = f"test-cost-api-db-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type=ServiceType.DATABASE.value,
        provider=PROVIDER,
        region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    rng = np.random.default_rng(3)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
    values = np.clip(1.0 + rng.normal(0, 0.01, len(timestamps)), 0, None)
    db.add_all(
        UsageRecord(
            resource_id=resource.id,
            timestamp=ts.to_pydatetime(),
            usage_type="hours_used",
            quantity=float(v),
            unit="hours",
            provider=resource.provider,
            region=resource.region,
        )
        for ts, v in zip(timestamps, values)
    )
    db.commit()

    yield resource

    forecast_ids = [
        f.id for f in db.query(Forecast).all()
        if db.query(CostPrediction).filter(
            CostPrediction.forecast_id == f.id, CostPrediction.resource_id == resource.id
        ).first()
    ]
    if forecast_ids:
        db.execute(delete(CostPrediction).where(CostPrediction.forecast_id.in_(forecast_ids)))
        db.execute(delete(Forecast).where(Forecast.id.in_(forecast_ids)))
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_predict_and_get_breakdown(client: TestClient, database_resource) -> None:
    predict_response = client.post(
        "/api/cost/predict",
        json={
            "provider": PROVIDER,
            "horizon": "week",
            "resource_id": database_resource.external_id,
        },
    )

    assert predict_response.status_code == 200
    body = predict_response.json()
    assert body["horizon_days"] == 7
    assert body["total_cost"] > 0
    assert any(li["sku"] == "database-instance-hour" for li in body["line_items"])

    forecast_id = body["forecast_id"]
    breakdown_response = client.get(f"/api/cost/breakdown?forecast_id={forecast_id}")

    assert breakdown_response.status_code == 200
    breakdown_body = breakdown_response.json()
    assert breakdown_body["forecast_id"] == forecast_id
    assert breakdown_body["total_cost"] == pytest.approx(body["total_cost"], rel=1e-6)
    assert breakdown_body["by_service"] == body["by_service"]


def test_get_breakdown_without_id_returns_latest(
    client: TestClient, database_resource
) -> None:
    predict_response = client.post(
        "/api/cost/predict",
        json={
            "provider": PROVIDER,
            "horizon": "day",
            "resource_id": database_resource.external_id,
        },
    )
    forecast_id = predict_response.json()["forecast_id"]

    breakdown_response = client.get("/api/cost/breakdown")

    assert breakdown_response.status_code == 200
    assert breakdown_response.json()["forecast_id"] == forecast_id


def test_predict_returns_404_for_unknown_resource(client: TestClient) -> None:
    response = client.post(
        "/api/cost/predict",
        json={"provider": PROVIDER, "horizon": "day", "resource_id": "nope"},
    )
    assert response.status_code == 404


def test_get_breakdown_returns_404_for_unknown_id(client: TestClient) -> None:
    response = client.get("/api/cost/breakdown?forecast_id=999999999")
    assert response.status_code == 404


def test_predict_reserved_without_commitment_term_is_rejected(
    client: TestClient, database_resource
) -> None:
    response = client.post(
        "/api/cost/predict",
        json={
            "provider": PROVIDER,
            "horizon": "day",
            "resource_id": database_resource.external_id,
            "pricing_model": "reserved",
        },
    )
    assert response.status_code == 422
