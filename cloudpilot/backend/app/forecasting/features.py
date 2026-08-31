"""Feature engineering for the ML forecaster.

Every feature is computable from information available strictly before the
day being predicted (lags, rolling stats over the past, calendar fields),
so there is no leakage between train/held-out/future prediction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LAGS = (1, 7, 14)
ROLLING_WINDOWS = (7, 14)


def build_feature_frame(series: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"y": series})
    df["day_of_week"] = df.index.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["day_of_month"] = df.index.day
    df["trend"] = np.arange(len(df))

    for lag in LAGS:
        df[f"lag_{lag}"] = df["y"].shift(lag)

    for window in ROLLING_WINDOWS:
        df[f"rolling_mean_{window}"] = df["y"].shift(1).rolling(window).mean()
        df[f"rolling_std_{window}"] = df["y"].shift(1).rolling(window).std()

    return df


FEATURE_COLUMNS = (
    ["day_of_week", "is_weekend", "day_of_month", "trend"]
    + [f"lag_{lag}" for lag in LAGS]
    + [f"rolling_mean_{w}" for w in ROLLING_WINDOWS]
    + [f"rolling_std_{w}" for w in ROLLING_WINDOWS]
)


def supervised_training_frame(series: pd.Series) -> pd.DataFrame:
    """Feature frame with rows lacking full lag/rolling history dropped."""
    df = build_feature_frame(series)
    return df.dropna(subset=FEATURE_COLUMNS)
