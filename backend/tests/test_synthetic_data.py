import numpy as np
import pandas as pd

from app.services.synthetic_data import COLUMNS, SERVICES, generate_dataset


def _small_dataset() -> pd.DataFrame:
    start = pd.Timestamp("2026-01-01")
    end = start + pd.Timedelta(days=14)
    return generate_dataset(
        start=start, end=end, freq="h", resources_per_service=2, seed=7
    )


def test_generated_dataset_has_expected_shape_and_columns() -> None:
    df = _small_dataset()

    assert list(df.columns) == COLUMNS
    assert set(df["service"].unique()) == set(SERVICES)
    # 14 days * 24h * 2 resources * 4 services
    assert len(df) == 14 * 24 * 2 * 4


def test_generation_is_deterministic_given_seed() -> None:
    df1 = _small_dataset()
    df2 = _small_dataset()

    pd.testing.assert_frame_equal(df1, df2)


def test_utilization_metrics_are_bounded() -> None:
    df = _small_dataset()
    numeric = df["cpu_utilization"].dropna()

    assert (numeric >= 0).all()
    assert (numeric <= 100).all()


def test_object_storage_has_no_cpu_memory_metrics() -> None:
    df = _small_dataset()
    object_storage = df[df["service"] == "Object Storage"]

    assert object_storage["cpu_utilization"].isna().all()
    assert object_storage["memory_utilization"].isna().all()


def test_database_storage_grows_over_time() -> None:
    df = _small_dataset()
    database = df[df["service"] == "Database"]

    for resource in database["resource"].unique():
        series = database[database["resource"] == resource].sort_values("timestamp")
        assert series["storage_gb"].iloc[-1] > series["storage_gb"].iloc[0]


def test_daily_seasonality_present_in_compute_cpu() -> None:
    df = _small_dataset()
    compute = df[df["service"] == "Compute"].copy()
    compute["hour"] = pd.to_datetime(compute["timestamp"]).dt.hour

    hourly_mean = compute.groupby("hour")["cpu_utilization"].mean()
    assert hourly_mean.max() - hourly_mean.min() > 10.0


def test_costs_and_core_metrics_are_non_negative() -> None:
    df = _small_dataset()

    for column in ["requests", "storage_gb", "network_gb", "hours_used", "current_cost"]:
        assert (df[column].dropna() >= 0).all()

    assert not np.isnan(df["current_cost"]).any()
