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

HISTORY_DAYS = 60


def _insert_hourly_history(db, resource: Resource, usage_type: str) -> None:
    rng = np.random.default_rng(42)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
    hour = timestamps.hour.to_numpy()
    day_of_week = timestamps.dayofweek.to_numpy()
    daily_pattern = 1.0 + 0.3 * np.sin(2 * np.pi * (hour - 9) / 24)
    weekly_pattern = np.where(day_of_week >= 5, 0.6, 1.0)
    base = 20.0 * daily_pattern * weekly_pattern
    noise = rng.normal(0, 1.0, len(timestamps))
    values = np.clip(base + noise, 0, None)

    rows = [
        UsageRecord(
            resource_id=resource.id,
            timestamp=ts.to_pydatetime(),
            usage_type=usage_type,
            quantity=float(v),
            unit="count",
            provider=resource.provider,
            region=resource.region,
        )
        for ts, v in zip(timestamps, values)
    ]
    db.add_all(rows)
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def resource_with_history(db):
    external_id = f"test-forecast-compute-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type="Compute",
        provider="test-provider",
        region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    _insert_hourly_history(db, resource, "requests")

    yield resource

    forecast_ids = [
        f.id for f in db.query(Forecast).filter(Forecast.resource_id == resource.id).all()
    ]
    if forecast_ids:
        db.execute(
            delete(CostPrediction).where(CostPrediction.forecast_id.in_(forecast_ids))
        )
        db.execute(delete(Forecast).where(Forecast.id.in_(forecast_ids)))
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_create_forecast_endpoint(client: TestClient, resource_with_history) -> None:
    response = client.post(
        "/api/forecast",
        json={
            "resource_id": resource_with_history.external_id,
            "usage_type": "requests",
            "horizon": "week",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resource_id"] == resource_with_history.external_id
    assert body["service"] == "Compute"
    assert body["usage_type"] == "requests"
    assert body["horizon_days"] == 7
    assert len(body["points"]) == 7
    assert set(body["metrics"].keys()) == {"baseline_seasonal_naive", "xgboost"}
    assert body["model_name"] in ("baseline_seasonal_naive", "xgboost")
    for point in body["points"]:
        assert point["actual_usage"] is None


def test_get_forecast_endpoint_returns_same_data(
    client: TestClient, resource_with_history
) -> None:
    create_response = client.post(
        "/api/forecast",
        json={
            "resource_id": resource_with_history.external_id,
            "usage_type": "requests",
            "horizon": "day",
        },
    )
    forecast_id = create_response.json()["id"]

    get_response = client.get(f"/api/forecast/{forecast_id}")

    assert get_response.status_code == 200
    body = get_response.json()
    assert body["id"] == forecast_id
    assert body["horizon_days"] == 1
    assert len(body["points"]) == 1


def test_get_forecast_returns_404_for_unknown_id(client: TestClient) -> None:
    response = client.get("/api/forecast/999999999")
    assert response.status_code == 404


def test_create_forecast_returns_404_for_unknown_resource(client: TestClient) -> None:
    response = client.post(
        "/api/forecast",
        json={
            "resource_id": "does-not-exist",
            "usage_type": "requests",
            "horizon": "day",
        },
    )
    assert response.status_code == 404


def test_create_forecast_rejects_invalid_usage_type(
    client: TestClient, resource_with_history
) -> None:
    response = client.post(
        "/api/forecast",
        json={
            "resource_id": resource_with_history.external_id,
            "usage_type": "cpu_utilization",
            "horizon": "day",
        },
    )
    assert response.status_code == 422


def test_backfill_populates_actual_usage_for_past_predictions(
    client: TestClient, db, resource_with_history
) -> None:
    create_response = client.post(
        "/api/forecast",
        json={
            "resource_id": resource_with_history.external_id,
            "usage_type": "requests",
            "horizon": "day",
        },
    )
    forecast_id = create_response.json()["id"]

    forecast = db.get(Forecast, forecast_id)
    prediction = (
        db.query(CostPrediction).filter(CostPrediction.forecast_id == forecast_id).first()
    )
    # Force the prediction into the past and add a full day (24 hourly
    # rows — backfill only counts a day once it's completely ingested) of
    # real usage_records for that date so the backfill on GET has a
    # complete actual to find.
    past_date = prediction.predicted_date.replace(year=prediction.predicted_date.year - 1)
    prediction.predicted_date = past_date
    db.commit()

    hourly_value = 10.0
    db.add_all(
        UsageRecord(
            resource_id=resource_with_history.id,
            timestamp=datetime.combine(past_date, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(hours=hour),
            usage_type="requests",
            quantity=hourly_value,
            unit="count",
            provider=resource_with_history.provider,
            region=resource_with_history.region,
        )
        for hour in range(24)
    )
    db.commit()

    get_response = client.get(f"/api/forecast/{forecast_id}")
    body = get_response.json()

    assert body["points"][0]["actual_usage"] == pytest.approx(24 * hourly_value)
