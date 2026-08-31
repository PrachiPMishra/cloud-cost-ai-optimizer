import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.data import NoHistoricalDataError
from app.forecasting.engine import InsufficientHistoryError
from app.forecasting.enums import ForecastHorizon
from app.forecasting.evaluation import mae, mape, rmse
from app.models.base import get_db
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
from app.services.forecast_service import (
    ForecastResponse,
    InvalidUsageTypeError,
    ResourceNotFoundError,
    create_forecast,
    get_forecast_with_predictions,
    to_forecast_response,
)

router = APIRouter()


class ForecastAccuracyResponse(BaseModel):
    sample_size: int
    mae: float
    rmse: float
    mape: float | None


@router.get("/accuracy", response_model=ForecastAccuracyResponse)
def get_forecast_accuracy_endpoint(
    resource_id: str | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
) -> ForecastAccuracyResponse:
    """Aggregate accuracy (MAE/RMSE/MAPE) across every usage forecast point
    that has since been backfilled with a real actual — i.e. genuinely
    computed forecast-vs-reality error, not a modeled/reported confidence
    figure."""
    query = (
        db.query(CostPrediction)
        .join(Forecast, CostPrediction.forecast_id == Forecast.id)
        .filter(CostPrediction.actual_usage.isnot(None), Forecast.target_metric != "cost")
    )
    if resource_id:
        query = query.join(Resource, CostPrediction.resource_id == Resource.id).filter(
            Resource.external_id == resource_id
        )

    rows = query.order_by(CostPrediction.predicted_date.desc()).limit(limit).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No backfilled forecast actuals available yet")

    predicted = np.array([float(r.predicted_usage) for r in rows])
    actual = np.array([float(r.actual_usage) for r in rows])

    return ForecastAccuracyResponse(
        sample_size=len(rows),
        mae=mae(actual, predicted),
        rmse=rmse(actual, predicted),
        mape=mape(actual, predicted),
    )


class ForecastCreateRequest(BaseModel):
    resource_id: str
    usage_type: str
    horizon: ForecastHorizon


@router.post("", response_model=ForecastResponse)
def create_forecast_endpoint(
    request: ForecastCreateRequest, db: Session = Depends(get_db)
) -> ForecastResponse:
    try:
        forecast = create_forecast(
            db,
            resource_external_id=request.resource_id,
            usage_type=request.usage_type,
            horizon=request.horizon,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoHistoricalDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidUsageTypeError, InsufficientHistoryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = get_forecast_with_predictions(db, forecast.id)
    assert result is not None
    forecast, predictions = result
    resource = db.get(Resource, forecast.resource_id)
    return to_forecast_response(forecast, resource, predictions)


@router.get("/{forecast_id}", response_model=ForecastResponse)
def get_forecast_endpoint(forecast_id: int, db: Session = Depends(get_db)) -> ForecastResponse:
    result = get_forecast_with_predictions(db, forecast_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No forecast with id={forecast_id}")

    forecast, predictions = result
    resource = db.get(Resource, forecast.resource_id)
    return to_forecast_response(forecast, resource, predictions)
