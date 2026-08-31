"""Seasonal-naive baseline: predicts day t as the value from t-7 (same
weekday last week). Falls back to the trailing mean when a week of history
isn't yet available. Recursive: once a day is forecast, it becomes
available as history for forecasting 7 days later.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MODEL_NAME = "baseline_seasonal_naive"
MODEL_VERSION = "1.0"


class BaselineForecaster:
    def __init__(self) -> None:
        self._history: list[float] = []

    def fit(self, series: pd.Series) -> "BaselineForecaster":
        self._history = list(series.to_numpy(dtype=float))
        return self

    def predict(self, horizon_days: int) -> np.ndarray:
        if not self._history:
            raise RuntimeError("BaselineForecaster.fit() must be called before predict()")

        extended = list(self._history)
        predictions = []
        for _ in range(horizon_days):
            if len(extended) >= 7:
                value = extended[-7]
            else:
                value = float(np.mean(extended))
            predictions.append(value)
            extended.append(value)

        return np.array(predictions, dtype=float)
