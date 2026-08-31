import pandas as pd
import pytest

from app.forecasting.baseline import BaselineForecaster


def test_predict_before_fit_raises() -> None:
    forecaster = BaselineForecaster()
    with pytest.raises(RuntimeError, match="fit\\(\\) must be called before predict\\(\\)"):
        forecaster.predict(horizon_days=3)


def test_predict_falls_back_to_trailing_mean_with_less_than_a_week_of_history() -> None:
    # Only 3 days of history -> no t-7 value exists yet, so every prediction
    # must come from the trailing-mean fallback, not the seasonal-naive path.
    series = pd.Series([10.0, 20.0, 30.0])
    forecaster = BaselineForecaster().fit(series)

    predictions = forecaster.predict(horizon_days=2)

    assert predictions[0] == pytest.approx(20.0)  # mean of [10, 20, 30]
    # extended history now includes the first prediction, so mean shifts.
    assert predictions[1] == pytest.approx((10.0 + 20.0 + 30.0 + 20.0) / 4)


def test_predict_uses_seasonal_naive_once_a_week_of_history_exists() -> None:
    series = pd.Series([float(i) for i in range(10)])  # day 0..9, values 0..9
    forecaster = BaselineForecaster().fit(series)

    predictions = forecaster.predict(horizon_days=1)

    assert predictions[0] == pytest.approx(3.0)  # value from 7 days back (index 3)
