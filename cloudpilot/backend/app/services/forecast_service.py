"""Wires the pure forecasting engine to persistence: creates a `forecasts`
row plus its `cost_predictions` points, and — on read — backfills
`actual_usage` for any predicted dates that have since passed and now have
real usage_records to compare against.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.data import load_daily_series
from app.forecasting.engine import run_forecast
from app.forecasting.enums import GAUGE_USAGE_TYPES, FORECASTABLE_USAGE_TYPES, ForecastHorizon
from app.forecasting.schemas import ModelMetrics
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
from app.models.usage_record import UsageRecord


class ResourceNotFoundError(Exception):
    pass


class InvalidUsageTypeError(Exception):
    pass


class StoredForecastPoint(BaseModel):
    date: date
    predicted_usage: float | None
    lower_bound: float | None
    upper_bound: float | None
    actual_usage: float | None


class ForecastResponse(BaseModel):
    id: int
    resource_id: str
    service: str
    usage_type: str
    horizon_days: int
    model_name: str
    model_version: str
    status: str
    generated_at: datetime
    training_window_start: date
    training_window_end: date
    metrics: dict[str, ModelMetrics]
    points: list[StoredForecastPoint]


def create_forecast(
    db: Session,
    *,
    resource_external_id: str,
    usage_type: str,
    horizon: ForecastHorizon,
) -> Forecast:
    if usage_type not in FORECASTABLE_USAGE_TYPES:
        raise InvalidUsageTypeError(
            f"usage_type must be one of {sorted(FORECASTABLE_USAGE_TYPES)}, "
            f"got {usage_type!r}"
        )

    resource = (
        db.query(Resource).filter(Resource.external_id == resource_external_id).first()
    )
    if resource is None:
        raise ResourceNotFoundError(
            f"No resource with external_id={resource_external_id!r}"
        )

    series = load_daily_series(db, resource, usage_type)
    result = run_forecast(series, resource.external_id, usage_type, horizon)

    forecast_row = Forecast(
        resource_id=resource.id,
        model_name=result.chosen_model_name,
        model_version=result.chosen_model_version,
        target_metric=usage_type,
        horizon_days=horizon.days,
        training_window_start=datetime.combine(
            result.training_window_start, time.min, tzinfo=timezone.utc
        ),
        training_window_end=datetime.combine(
            result.training_window_end, time.min, tzinfo=timezone.utc
        ),
        status="completed",
        run_metadata={
            "models_compared": {
                name: metrics.model_dump() for name, metrics in result.metrics.items()
            },
            "chosen_model": result.chosen_model_name,
            "test_size_days": result.test_size_days,
        },
    )
    db.add(forecast_row)
    db.flush()

    prediction_rows = [
        CostPrediction(
            forecast_id=forecast_row.id,
            resource_id=resource.id,
            predicted_date=point.date,
            predicted_usage=point.predicted_usage,
            predicted_cost=None,
            lower_bound=point.lower_bound,
            upper_bound=point.upper_bound,
        )
        for point in result.points
    ]
    db.add_all(prediction_rows)
    db.commit()
    db.refresh(forecast_row)
    return forecast_row


def _backfill_actuals(db: Session, forecast: Forecast) -> None:
    today = date.today()
    pending = (
        db.query(CostPrediction)
        .filter(
            CostPrediction.forecast_id == forecast.id,
            CostPrediction.predicted_date <= today,
            CostPrediction.actual_usage.is_(None),
        )
        .all()
    )
    if not pending:
        return

    usage_type = forecast.target_metric
    updated = False
    expected_count = _expected_daily_row_count(db, forecast.resource_id, usage_type)

    for prediction in pending:
        day_start = datetime.combine(prediction.predicted_date, time.min, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        values = [
            float(q)
            for (q,) in db.query(UsageRecord.quantity)
            .filter(
                UsageRecord.resource_id == forecast.resource_id,
                UsageRecord.usage_type == usage_type,
                UsageRecord.timestamp >= day_start,
                UsageRecord.timestamp < day_end,
            )
            .all()
        ]
        # Only treat a day as "actual" once it has a full day of readings —
        # a still-partial day (ingestion caught up to only part of today,
        # or of a day that hasn't fully elapsed yet) would otherwise be
        # compared against a full-day forecast, understating usage.
        if len(values) < expected_count:
            continue

        actual = sum(values) / len(values) if usage_type in GAUGE_USAGE_TYPES else sum(values)
        prediction.actual_usage = actual
        prediction.actual_recorded_at = datetime.now(timezone.utc)
        updated = True

    if updated:
        db.commit()


def _expected_daily_row_count(db: Session, resource_id: int, usage_type: str) -> int:
    """Typical number of readings per day for this (resource, usage_type),
    used to tell a complete day of ingested data from a partial one."""
    rows = (
        db.query(UsageRecord.timestamp)
        .filter(
            UsageRecord.resource_id == resource_id,
            UsageRecord.usage_type == usage_type,
        )
        .all()
    )
    if not rows:
        return 24  # sensible default for hourly ingestion cadence

    counts = Counter(ts.date() for (ts,) in rows)
    return Counter(counts.values()).most_common(1)[0][0]


def get_forecast_with_predictions(
    db: Session, forecast_id: int
) -> tuple[Forecast, list[CostPrediction]] | None:
    forecast = db.get(Forecast, forecast_id)
    if forecast is None:
        return None

    _backfill_actuals(db, forecast)

    predictions = (
        db.query(CostPrediction)
        .filter(CostPrediction.forecast_id == forecast_id)
        .order_by(CostPrediction.predicted_date.asc())
        .all()
    )
    return forecast, predictions


def to_forecast_response(
    forecast: Forecast, resource: Resource, predictions: list[CostPrediction]
) -> ForecastResponse:
    metrics = {
        name: ModelMetrics(**values)
        for name, values in forecast.run_metadata["models_compared"].items()
    }
    return ForecastResponse(
        id=forecast.id,
        resource_id=resource.external_id,
        service=resource.resource_type,
        usage_type=forecast.target_metric,
        horizon_days=forecast.horizon_days,
        model_name=forecast.model_name,
        model_version=forecast.model_version,
        status=forecast.status,
        generated_at=forecast.generated_at,
        training_window_start=forecast.training_window_start.date(),
        training_window_end=forecast.training_window_end.date(),
        metrics=metrics,
        points=[
            StoredForecastPoint(
                date=p.predicted_date,
                predicted_usage=p.predicted_usage,
                lower_bound=p.lower_bound,
                upper_bound=p.upper_bound,
                actual_usage=p.actual_usage,
            )
            for p in predictions
        ],
    )
