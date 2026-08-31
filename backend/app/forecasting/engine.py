"""Orchestrates a forecast run: load history, chronological train/held-out
split, fit baseline + XGBoost, score both on the real held-out data,
pick the better one by held-out RMSE, refit it on the full series, and
produce the forward-looking forecast with residual-based confidence
intervals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.forecasting.baseline import MODEL_NAME as BASELINE_NAME
from app.forecasting.baseline import MODEL_VERSION as BASELINE_VERSION
from app.forecasting.baseline import BaselineForecaster
from app.forecasting.enums import ForecastHorizon
from app.forecasting.evaluation import mae, mape, residual_std, rmse
from app.forecasting.ml_model import MODEL_NAME as XGBOOST_NAME
from app.forecasting.ml_model import MODEL_VERSION as XGBOOST_VERSION
from app.forecasting.ml_model import MLForecaster
from app.forecasting.schemas import ForecastPoint, ForecastRunResult, ModelMetrics

MIN_HISTORY_DAYS = 45

# 90% confidence interval under a normal-residuals assumption.
CONFIDENCE_Z = 1.645


class InsufficientHistoryError(Exception):
    pass


def _test_size_for(n_days: int) -> int:
    return min(14, max(7, n_days // 5))


def _score(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[ModelMetrics, float]:
    metrics = ModelMetrics(
        mae=mae(y_true, y_pred),
        rmse=rmse(y_true, y_pred),
        mape=mape(y_true, y_pred),
    )
    return metrics, residual_std(y_true, y_pred)


def run_forecast(
    series: pd.Series,
    resource_external_id: str,
    usage_type: str,
    horizon: ForecastHorizon,
) -> ForecastRunResult:
    if len(series) < MIN_HISTORY_DAYS:
        raise InsufficientHistoryError(
            f"Need at least {MIN_HISTORY_DAYS} days of history for "
            f"resource={resource_external_id!r} usage_type={usage_type!r}, "
            f"got {len(series)}"
        )

    test_size = _test_size_for(len(series))
    train_series = series.iloc[:-test_size]
    test_series = series.iloc[-test_size:]
    y_test = test_series.to_numpy(dtype=float)

    baseline = BaselineForecaster().fit(train_series)
    baseline_pred = baseline.predict(test_size)
    baseline_metrics, baseline_residual_std = _score(y_test, baseline_pred)

    ml_model = MLForecaster().fit(train_series)
    ml_pred = ml_model.predict(test_size)
    ml_metrics, ml_residual_std = _score(y_test, ml_pred)

    candidates = {
        BASELINE_NAME: (BASELINE_VERSION, baseline_metrics, baseline_residual_std, BaselineForecaster),
        XGBOOST_NAME: (XGBOOST_VERSION, ml_metrics, ml_residual_std, MLForecaster),
    }

    # Lower held-out RMSE wins; tie goes to XGBoost (it uses strictly more
    # information than the baseline, so a tie suggests the extra signal
    # available in this series simply isn't there yet).
    chosen_name = min(
        candidates,
        key=lambda name: (candidates[name][1].rmse, 0 if name == XGBOOST_NAME else 1),
    )
    chosen_version, _, chosen_residual_std, chosen_cls = candidates[chosen_name]

    final_model = chosen_cls().fit(series)
    future_values = final_model.predict(horizon.days)

    points: list[ForecastPoint] = []
    last_date = series.index[-1]
    for step, value in enumerate(future_values, start=1):
        forecast_date = (last_date + pd.Timedelta(days=step)).date()
        width = CONFIDENCE_Z * chosen_residual_std * (step**0.5)
        points.append(
            ForecastPoint(
                date=forecast_date,
                predicted_usage=float(value),
                lower_bound=max(0.0, float(value) - width) if chosen_residual_std > 0 else None,
                upper_bound=float(value) + width if chosen_residual_std > 0 else None,
            )
        )

    return ForecastRunResult(
        resource_external_id=resource_external_id,
        usage_type=usage_type,
        horizon=horizon,
        chosen_model_name=chosen_name,
        chosen_model_version=chosen_version,
        training_window_start=series.index.min().date(),
        training_window_end=series.index.max().date(),
        test_size_days=test_size,
        metrics={
            BASELINE_NAME: baseline_metrics,
            XGBOOST_NAME: ml_metrics,
        },
        points=points,
    )
