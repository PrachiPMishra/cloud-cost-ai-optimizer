import json

import numpy as np
import pandas as pd
import pytest

from app.services.synthetic_data import _cumulative_storage, save_dataset


def test_cumulative_storage_occasionally_drops() -> None:
    # drop probability is 0.0002/hour; a large enough sample makes at least
    # one drop a near-certainty, exercising the cleanup-event branch that
    # unit tests using realistic (short) history lengths never hit.
    rng = np.random.default_rng(0)
    storage = _cumulative_storage(n=100_000, base_gb=100.0, daily_growth_gb=5.0, rng=rng)

    diffs = np.diff(storage)
    assert (diffs < 0).any(), "expected at least one cleanup-driven drop over 100k hourly steps"
    assert storage.min() > 0


def test_save_dataset_csv(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
            "service": ["Compute", "Compute", "Compute"],
            "value": [1.0, 2.0, 3.0],
        }
    )
    out = tmp_path / "nested" / "out.csv"
    save_dataset(df, out, fmt="csv")

    assert out.exists()
    reloaded = pd.read_csv(out)
    assert len(reloaded) == 3
    assert list(reloaded["service"]) == ["Compute", "Compute", "Compute"]


def test_save_dataset_json(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC"),
            "service": ["Database", "Database"],
            "value": [10.0, 20.0],
        }
    )
    out = tmp_path / "out.json"
    save_dataset(df, out, fmt="json")

    assert out.exists()
    records = json.loads(out.read_text())
    assert isinstance(records, list)
    assert len(records) == 2
    assert records[0]["service"] == "Database"


def test_save_dataset_unsupported_format_raises(tmp_path) -> None:
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(ValueError, match="Unsupported format"):
        save_dataset(df, tmp_path / "out.parquet", fmt="parquet")
