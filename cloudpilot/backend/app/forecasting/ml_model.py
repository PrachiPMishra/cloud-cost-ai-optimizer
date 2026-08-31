"""XGBoost forecaster: a single one-step-ahead regressor trained on lag /
rolling / calendar features, applied recursively to reach any horizon
(each predicted day's value feeds the lag features for the next).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost
from xgboost import XGBRegressor

from app.forecasting.features import FEATURE_COLUMNS, build_feature_frame, supervised_training_frame

MODEL_NAME = "xgboost"
MODEL_VERSION = xgboost.__version__


class MLForecaster:
    def __init__(self, **xgb_params) -> None:
        params = dict(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
        )
        params.update(xgb_params)
        self._model = XGBRegressor(**params)
        self._history: list[float] = []
        self._last_date: pd.Timestamp | None = None
        self._fitted = False

    def fit(self, series: pd.Series) -> "MLForecaster":
        train_frame = supervised_training_frame(series)
        if len(train_frame) < 10:
            raise ValueError(
                "Not enough history to train the ML forecaster after feature "
                f"engineering (got {len(train_frame)} usable rows, need >= 10)"
            )
        X = train_frame[FEATURE_COLUMNS]
        y = train_frame["y"]
        self._model.fit(X, y)
        self._history = list(series.to_numpy(dtype=float))
        self._last_date = series.index[-1]
        self._fitted = True
        return self

    def predict(self, horizon_days: int) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("MLForecaster.fit() must be called before predict()")

        extended = pd.Series(
            list(self._history),
            index=pd.date_range(
                end=self._last_date, periods=len(self._history), freq="D"
            ),
        )

        predictions = []
        for _ in range(horizon_days):
            feature_frame = build_feature_frame(extended)
            next_features = feature_frame.iloc[[-1]][FEATURE_COLUMNS]
            next_value = float(self._model.predict(next_features)[0])
            next_value = max(next_value, 0.0)
            predictions.append(next_value)

            next_date = extended.index[-1] + pd.Timedelta(days=1)
            extended.loc[next_date] = next_value

        return np.array(predictions, dtype=float)
