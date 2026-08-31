"""MAE / RMSE / MAPE computed directly from actual vs. predicted arrays.

These are always computed from real held-out data by the caller — nothing
here fabricates or looks up a canned metric value.
"""

from __future__ import annotations

import numpy as np


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    """Mean absolute percentage error, in percent. None if every actual is
    zero (MAPE is undefined there rather than a fabricated 0/100)."""
    mask = y_true != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)


def residual_std(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.std(y_true - y_pred, ddof=0))
