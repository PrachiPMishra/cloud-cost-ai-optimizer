"""Synthetic cloud usage/billing dataset generator.

Produces a time series of usage + cost records across four service
categories (Compute, Database, Object Storage, Serverless) with daily and
weekly seasonality, per-resource growth trends, idle periods, traffic
spikes, and sparse anomalies.

The per-service unit rates used to derive `current_cost` here are
illustrative, public-cloud-like rates used only to make the synthetic
dataset internally consistent (usage that goes up should cost more). They
are independent of, and never used by, the platform's actual pricing
engine (`app/pricing`), which prices real ingested usage.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SERVICES = ["Compute", "Database", "Object Storage", "Serverless"]
REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]

COLUMNS = [
    "timestamp",
    "service",
    "resource",
    "region",
    "cpu_utilization",
    "memory_utilization",
    "requests",
    "storage_gb",
    "network_gb",
    "hours_used",
    "current_cost",
]

# Illustrative synthetic billing rates (USD) — see module docstring.
SERVICE_PARAMS: dict[str, dict] = {
    "Compute": {
        "has_cpu_mem": True,
        "can_fully_idle": True,
        "cpu_base": 35.0,
        "cpu_amp": 25.0,
        "mem_base": 45.0,
        "mem_amp": 20.0,
        "requests_base": 150.0,
        "requests_amp": 100.0,
        "storage_range_gb": (50.0, 300.0),
        "storage_cumulative": False,
        "network_base_gb": 1.5,
        "hourly_rate": 0.096,
        "network_rate_per_gb": 0.09,
        "request_rate": 0.0,
        "storage_rate_per_gb_hr": 0.0,
    },
    "Database": {
        "has_cpu_mem": True,
        "can_fully_idle": False,
        "cpu_base": 40.0,
        "cpu_amp": 20.0,
        "mem_base": 55.0,
        "mem_amp": 15.0,
        "requests_base": 5000.0,
        "requests_amp": 3000.0,
        "storage_range_gb": (100.0, 500.0),
        "storage_cumulative": True,
        "storage_daily_growth_gb": (0.5, 3.0),
        "network_base_gb": 3.0,
        "hourly_rate": 0.145,
        "network_rate_per_gb": 0.09,
        "request_rate": 0.0000002,
        "storage_rate_per_gb_hr": 0.115 / 730.0,
    },
    "Object Storage": {
        "has_cpu_mem": False,
        "can_fully_idle": False,
        "requests_base": 8000.0,
        "requests_amp": 5000.0,
        "storage_range_gb": (500.0, 5000.0),
        "storage_cumulative": True,
        "storage_daily_growth_gb": (2.0, 20.0),
        "network_base_gb": 5.0,
        "hourly_rate": 0.0,
        "network_rate_per_gb": 0.09,
        "request_rate": 0.0000004,
        "storage_rate_per_gb_hr": 0.023 / 730.0,
    },
    "Serverless": {
        "has_cpu_mem": True,
        "can_fully_idle": True,
        "cpu_base": 30.0,
        "cpu_amp": 25.0,
        "mem_base": 40.0,
        "mem_amp": 25.0,
        "requests_base": 2000.0,
        "requests_amp": 2500.0,
        "storage_range_gb": (0.5, 2.0),
        "storage_cumulative": False,
        "network_base_gb": 0.8,
        "hourly_rate": 0.0,
        "network_rate_per_gb": 0.09,
        "invocation_rate": 0.0000002,
        "gb_second_rate": 0.0000166667,
        "avg_duration_sec_range": (0.2, 1.5),
        "avg_memory_gb_range": (0.25, 1.0),
    },
}

RESOURCE_PREFIX = {
    "Compute": "compute-i",
    "Database": "database-db",
    "Object Storage": "objstore-bucket",
    "Serverless": "serverless-fn",
}


@dataclass
class ResourceProfile:
    service: str
    resource: str
    region: str
    growth_rate_per_day: float
    seed: int


def _seasonal_multiplier(
    timestamps: pd.DatetimeIndex,
    daily_amplitude: float,
    weekend_factor: float,
    growth_rate_per_day: float,
) -> np.ndarray:
    """Daily + weekly seasonality combined with a per-resource growth trend."""
    hours = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60.0
    daily = 1.0 + daily_amplitude * np.sin(2 * np.pi * (hours - 9.0) / 24.0)

    is_weekend = timestamps.dayofweek.to_numpy() >= 5
    weekly = np.where(is_weekend, weekend_factor, 1.0)

    days_elapsed = (timestamps - timestamps[0]).total_seconds() / 86400.0
    growth = 1.0 + growth_rate_per_day * days_elapsed

    return daily * weekly * growth


def _idle_mask(
    n: int, rng: np.random.Generator, n_periods_max: int = 4
) -> np.ndarray:
    """Boolean mask marking hours where the resource is effectively idle/stopped."""
    mask = np.zeros(n, dtype=bool)
    n_periods = int(rng.integers(0, n_periods_max + 1))
    for _ in range(n_periods):
        start = int(rng.integers(0, max(n - 1, 1)))
        duration = int(rng.integers(6, 49))
        mask[start : min(start + duration, n)] = True
    return mask


def _spike_multiplier(n: int, rng: np.random.Generator) -> np.ndarray:
    """Multiplicative overlay representing short traffic/load spikes."""
    multiplier = np.ones(n)
    n_spikes = int(rng.integers(1, max(n // (24 * 15), 2)))
    for _ in range(n_spikes):
        start = int(rng.integers(0, max(n - 1, 1)))
        duration = int(rng.integers(2, 7))
        factor = rng.uniform(3.0, 8.0)
        multiplier[start : min(start + duration, n)] *= factor
    return multiplier


def _anomaly_multiplier(
    n: int, rng: np.random.Generator, probability: float = 0.0015
) -> np.ndarray:
    """Sparse single-point anomalies (e.g. runaway process, traffic burst)."""
    multiplier = np.ones(n)
    hits = rng.random(n) < probability
    multiplier[hits] *= rng.uniform(5.0, 12.0, size=int(hits.sum()))
    return multiplier


def _cumulative_storage(
    n: int,
    base_gb: float,
    daily_growth_gb: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Monotonic-ish storage growth: steady ingest, occasional jumps/cleanups."""
    hourly_growth = daily_growth_gb / 24.0
    increments = rng.normal(hourly_growth, hourly_growth / 2.0 + 1e-6, size=n).clip(
        min=0.0
    )

    jump_hits = rng.random(n) < 0.003
    increments[jump_hits] += rng.uniform(
        daily_growth_gb * 2, daily_growth_gb * 8, size=int(jump_hits.sum())
    )

    storage = base_gb + np.cumsum(increments)

    drop_hits = np.where(rng.random(n) < 0.0002)[0]
    for idx in drop_hits:
        storage[idx:] *= 1.0 - rng.uniform(0.01, 0.05)

    return storage


def generate_resource_timeseries(
    profile: ResourceProfile, timestamps: pd.DatetimeIndex
) -> pd.DataFrame:
    rng = np.random.default_rng(profile.seed)
    params = SERVICE_PARAMS[profile.service]
    n = len(timestamps)

    load = _seasonal_multiplier(
        timestamps,
        daily_amplitude=0.35,
        weekend_factor=0.6,
        growth_rate_per_day=profile.growth_rate_per_day,
    )
    load *= _spike_multiplier(n, rng)
    anomaly = _anomaly_multiplier(n, rng)

    idle = _idle_mask(n, rng) if params["can_fully_idle"] else np.zeros(n, dtype=bool)
    load_adj = np.where(idle, load * 0.02, load)

    if params["has_cpu_mem"]:
        cpu = (params["cpu_base"] * load_adj * anomaly) + rng.normal(0, 3.0, n)
        cpu = np.clip(cpu, 0.0, 100.0)
        mem = (params["mem_base"] * load_adj * anomaly) + rng.normal(0, 3.0, n)
        mem = np.clip(mem, 0.0, 100.0)
    else:
        cpu = np.full(n, np.nan)
        mem = np.full(n, np.nan)

    requests = (params["requests_base"] * load_adj * anomaly) + rng.normal(
        0, params["requests_amp"] * 0.05, n
    )
    requests = np.clip(requests, 0, None).round().astype(float)
    if params["can_fully_idle"]:
        requests = np.where(idle, requests * 0.05, requests)

    lo, hi = params["storage_range_gb"]
    base_storage = rng.uniform(lo, hi)
    if params["storage_cumulative"]:
        glo, ghi = params["storage_daily_growth_gb"]
        daily_growth = rng.uniform(glo, ghi)
        storage_gb = _cumulative_storage(n, base_storage, daily_growth, rng)
    else:
        storage_gb = base_storage + rng.normal(0, base_storage * 0.02, n)
        storage_gb = np.clip(storage_gb, 0.1, None)

    network_gb = (params["network_base_gb"] * load_adj * anomaly) + rng.normal(
        0, params["network_base_gb"] * 0.1, n
    )
    network_gb = np.clip(network_gb, 0.0, None)

    if profile.service in ("Compute", "Serverless"):
        hours_used = np.where(idle, 0.0, 1.0)
        if profile.service == "Serverless":
            lo_d, hi_d = params["avg_duration_sec_range"]
            avg_duration_sec = rng.uniform(lo_d, hi_d)
            hours_used = (requests * avg_duration_sec) / 3600.0
    else:
        hours_used = np.ones(n)

    current_cost = hours_used * params.get("hourly_rate", 0.0)
    current_cost += network_gb * params["network_rate_per_gb"]
    current_cost += storage_gb * params.get("storage_rate_per_gb_hr", 0.0)
    current_cost += requests * params.get("request_rate", 0.0)

    if profile.service == "Serverless":
        lo_m, hi_m = params["avg_memory_gb_range"]
        avg_memory_gb = rng.uniform(lo_m, hi_m)
        current_cost += requests * params["invocation_rate"]
        current_cost += hours_used * 3600.0 * avg_memory_gb * params["gb_second_rate"]

    current_cost = np.clip(current_cost, 0.0, None)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "service": profile.service,
            "resource": profile.resource,
            "region": profile.region,
            "cpu_utilization": cpu,
            "memory_utilization": mem,
            "requests": requests,
            "storage_gb": storage_gb,
            "network_gb": network_gb,
            "hours_used": hours_used,
            "current_cost": current_cost,
        }
    )


def generate_dataset(
    start: pd.Timestamp,
    end: pd.Timestamp,
    freq: str = "h",
    resources_per_service: int = 4,
    seed: int = 42,
) -> pd.DataFrame:
    timestamps = pd.date_range(start=start, end=end, freq=freq, inclusive="left")
    rng = np.random.default_rng(seed)

    frames = []
    resource_counter = 0
    for service in SERVICES:
        for i in range(resources_per_service):
            resource_counter += 1
            resource_id = f"{RESOURCE_PREFIX[service]}-{i + 1:04d}"
            region = REGIONS[resource_counter % len(REGIONS)]
            profile = ResourceProfile(
                service=service,
                resource=resource_id,
                region=region,
                growth_rate_per_day=float(rng.uniform(0.0005, 0.006)),
                seed=int(rng.integers(0, 2**32 - 1)),
            )
            frames.append(generate_resource_timeseries(profile, timestamps))

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["timestamp", "service", "resource"]).reset_index(drop=True)
    return df[COLUMNS]


def save_dataset(df: pd.DataFrame, output_path: Path, fmt: str = "csv") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        df.to_csv(output_path, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    elif fmt == "json":
        records = json.loads(df.to_json(orient="records", date_format="iso"))
        output_path.write_text(json.dumps(records, indent=2))
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _default_datasets_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "datasets"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic cloud usage data")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--freq", type=str, default="h")
    parser.add_argument("--resources-per-service", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    end = pd.Timestamp.utcnow().tz_localize(None).floor("h")
    start = end - pd.Timedelta(days=args.days)

    df = generate_dataset(
        start=start,
        end=end,
        freq=args.freq,
        resources_per_service=args.resources_per_service,
        seed=args.seed,
    )

    output_path = (
        Path(args.output)
        if args.output
        else _default_datasets_dir() / f"synthetic_usage.{args.format}"
    )
    save_dataset(df, output_path, fmt=args.format)
    print(f"Wrote {len(df):,} rows to {output_path}")


if __name__ == "__main__":
    main()
