import numpy as np
import pandas as pd
import pytest

from app.forecasting.baseline import BaselineForecaster
from app.forecasting.engine import InsufficientHistoryError, run_forecast
from app.forecasting.enums import ForecastHorizon
from app.forecasting.evaluation import mae, mape, rmse
from app.forecasting.ml_model import MLForecaster


def _seasonal_series(n_days: int = 90, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-01-01", periods=n_days, freq="D")
    day_of_week = index.dayofweek.to_numpy()
    weekly = np.where(day_of_week >= 5, 0.6, 1.0)
    trend = 1.0 + 0.002 * np.arange(n_days)
    base = 100.0 * weekly * trend
    noise = rng.normal(0, 2.0, n_days)
    values = np.clip(base + noise, 0, None)
    return pd.Series(values, index=index, name="requests")


def test_evaluation_metrics_are_computed_correctly() -> None:
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([12.0, 18.0, 33.0])

    assert mae(y_true, y_pred) == pytest.approx((2 + 2 + 3) / 3)
    assert rmse(y_true, y_pred) == pytest.approx(np.sqrt((4 + 4 + 9) / 3))
    assert mape(y_true, y_pred) == pytest.approx(
        np.mean([2 / 10, 2 / 20, 3 / 30]) * 100
    )


def test_mape_undefined_when_all_actuals_zero() -> None:
    assert mape(np.array([0.0, 0.0]), np.array([1.0, 2.0])) is None


def test_baseline_forecaster_repeats_weekly_pattern() -> None:
    series = _seasonal_series(30)
    model = BaselineForecaster().fit(series)
    predictions = model.predict(7)

    assert len(predictions) == 7
    # day 8 predicted from day 1 (7-day lag) should be close to it
    assert predictions[0] == pytest.approx(series.iloc[-7], rel=0.3)


def test_ml_forecaster_predicts_non_negative_and_correct_length() -> None:
    series = _seasonal_series(60)
    model = MLForecaster().fit(series)
    predictions = model.predict(14)

    assert len(predictions) == 14
    assert (predictions >= 0).all()


def test_ml_forecaster_rejects_insufficient_training_rows() -> None:
    series = _seasonal_series(10)
    with pytest.raises(ValueError):
        MLForecaster().fit(series)


def test_run_forecast_raises_on_insufficient_history() -> None:
    series = _seasonal_series(20)
    with pytest.raises(InsufficientHistoryError):
        run_forecast(series, "res-1", "requests", ForecastHorizon.WEEK)


@pytest.mark.parametrize(
    "horizon,expected_days",
    [(ForecastHorizon.DAY, 1), (ForecastHorizon.WEEK, 7), (ForecastHorizon.MONTH, 30)],
)
def test_run_forecast_produces_expected_horizon_and_valid_structure(
    horizon, expected_days
) -> None:
    series = _seasonal_series(90)
    result = run_forecast(series, "res-1", "requests", horizon)

    assert len(result.points) == expected_days
    assert result.chosen_model_name in ("baseline_seasonal_naive", "xgboost")
    assert set(result.metrics.keys()) == {"baseline_seasonal_naive", "xgboost"}

    for name, metrics in result.metrics.items():
        assert metrics.mae >= 0
        assert metrics.rmse >= 0
        assert metrics.mape is None or metrics.mape >= 0

    dates = [p.date for p in result.points]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)

    for point in result.points:
        if point.lower_bound is not None and point.upper_bound is not None:
            assert point.lower_bound <= point.predicted_usage <= point.upper_bound

    # confidence interval should widen further into the future (sqrt(h) growth)
    if expected_days > 1:
        first_width = result.points[0].upper_bound - result.points[0].lower_bound
        last_width = result.points[-1].upper_bound - result.points[-1].lower_bound
        assert last_width >= first_width


def test_run_forecast_metrics_are_not_fabricated_placeholders() -> None:
    """The two models should generally score differently on real held-out
    data — identical MAE/RMSE/MAPE across models would suggest a stub."""
    series = _seasonal_series(90, seed=1)
    result = run_forecast(series, "res-1", "requests", ForecastHorizon.WEEK)

    baseline = result.metrics["baseline_seasonal_naive"]
    ml = result.metrics["xgboost"]
    assert (baseline.mae, baseline.rmse) != (ml.mae, ml.rmse)
