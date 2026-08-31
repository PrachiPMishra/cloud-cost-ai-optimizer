from datetime import date

from pydantic import BaseModel

from app.forecasting.enums import ForecastHorizon


class ModelMetrics(BaseModel):
    mae: float
    rmse: float
    mape: float | None


class ForecastPoint(BaseModel):
    date: date
    predicted_usage: float
    lower_bound: float | None
    upper_bound: float | None


class ForecastRunResult(BaseModel):
    resource_external_id: str
    usage_type: str
    horizon: ForecastHorizon
    chosen_model_name: str
    chosen_model_version: str
    training_window_start: date
    training_window_end: date
    test_size_days: int
    metrics: dict[str, ModelMetrics]
    points: list[ForecastPoint]
