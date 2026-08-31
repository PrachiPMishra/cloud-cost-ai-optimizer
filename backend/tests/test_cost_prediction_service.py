import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.models.base import SessionLocal
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.forecasting.enums import ForecastHorizon
from app.pricing.enums import PricingModel, ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.services.cost_prediction import (
    BillNotFoundError,
    NoForecastableLineItemsError,
    NoResourcesInScopeError,
    get_stored_breakdown,
    predict_bill,
)

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


def _insert_hourly_history(db, resource: Resource, usage_type: str, base: float) -> None:
    rng = np.random.default_rng(7)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
    day_of_week = timestamps.dayofweek.to_numpy()
    weekly = np.where(day_of_week >= 5, 0.7, 1.0)
    noise = rng.normal(0, base * 0.05, len(timestamps))
    values = np.clip(base * weekly + noise, 0, None)

    rows = [
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
    ]
    db.add_all(rows)
    db.commit()


@pytest.fixture()
def compute_resource(db):
    external_id = f"test-bill-compute-{uuid.uuid4().hex[:8]}"
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

    _insert_hourly_history(db, resource, "hours_used", base=1.0)
    _insert_hourly_history(db, resource, "network_gb", base=2.0)

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


def test_predict_bill_for_single_resource(db, compute_resource) -> None:
    summary = predict_bill(
        db,
        provider=PROVIDER,
        horizon=ForecastHorizon.WEEK,
        pricing_model=PricingModel.ON_DEMAND,
        resource_external_id=compute_resource.external_id,
    )

    assert summary.horizon_days == 7
    skus = {li.sku for li in summary.line_items}
    assert skus == {"compute-instance-hour", "compute-network-egress"}

    hours_item = next(li for li in summary.line_items if li.sku == "compute-instance-hour")
    expected_cost = hours_item.predicted_quantity * 0.096
    assert hours_item.predicted_cost == pytest.approx(expected_cost, rel=1e-6)

    assert summary.total_cost == pytest.approx(
        sum(li.predicted_cost for li in summary.line_items), rel=1e-9
    )
    assert summary.by_service == {"Compute": pytest.approx(summary.total_cost)}
    assert summary.by_resource == {compute_resource.external_id: pytest.approx(summary.total_cost)}

    # confidence interval should bracket the point estimate
    for li in summary.line_items:
        if li.lower_bound_cost is not None and li.upper_bound_cost is not None:
            assert li.lower_bound_cost <= li.predicted_cost <= li.upper_bound_cost

    # persisted correctly
    forecast_row = db.get(Forecast, summary.forecast_id)
    assert forecast_row.target_metric == "cost"
    assert forecast_row.model_name == "bill_prediction"

    stored_predictions = (
        db.query(CostPrediction).filter(CostPrediction.forecast_id == summary.forecast_id).all()
    )
    assert len(stored_predictions) == len(summary.line_items)
    assert {p.usage_type for p in stored_predictions} == {"hours_used", "network_gb"}
    assert {p.sku for p in stored_predictions} == skus


def test_predict_bill_unknown_resource_raises(db) -> None:
    with pytest.raises(NoResourcesInScopeError):
        predict_bill(
            db,
            provider=PROVIDER,
            horizon=ForecastHorizon.DAY,
            resource_external_id="does-not-exist",
        )


def test_predict_bill_no_resources_for_provider_scope_raises(db) -> None:
    with pytest.raises(NoResourcesInScopeError):
        predict_bill(
            db,
            provider="provider-with-no-resources-xyz",
            horizon=ForecastHorizon.DAY,
        )


def test_predict_bill_insufficient_history_raises(db) -> None:
    external_id = f"test-bill-short-{uuid.uuid4().hex[:8]}"
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

    rows = [
        UsageRecord(
            resource_id=resource.id,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=h),
            usage_type="hours_used",
            quantity=1.0,
            unit="hours",
            provider=PROVIDER,
            region="us-east-1",
        )
        for h in range(24 * 5)
    ]
    db.add_all(rows)
    db.commit()

    try:
        with pytest.raises(NoForecastableLineItemsError):
            predict_bill(
                db,
                provider=PROVIDER,
                horizon=ForecastHorizon.DAY,
                resource_external_id=external_id,
            )
    finally:
        db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
        db.execute(delete(Resource).where(Resource.id == resource.id))
        db.commit()


def test_get_stored_breakdown_by_id(db, compute_resource) -> None:
    summary = predict_bill(
        db,
        provider=PROVIDER,
        horizon=ForecastHorizon.DAY,
        resource_external_id=compute_resource.external_id,
    )

    fetched = get_stored_breakdown(db, summary.forecast_id)

    assert fetched.forecast_id == summary.forecast_id
    assert fetched.total_cost == pytest.approx(summary.total_cost, rel=1e-9)
    assert {li.sku for li in fetched.line_items} == {li.sku for li in summary.line_items}
    assert fetched.by_service == summary.by_service


def test_get_stored_breakdown_defaults_to_latest(db, compute_resource) -> None:
    summary = predict_bill(
        db,
        provider=PROVIDER,
        horizon=ForecastHorizon.DAY,
        resource_external_id=compute_resource.external_id,
    )

    fetched = get_stored_breakdown(db, forecast_id=None)

    assert fetched.forecast_id == summary.forecast_id


def test_get_stored_breakdown_unknown_id_raises(db) -> None:
    with pytest.raises(BillNotFoundError):
        get_stored_breakdown(db, 999999999)
