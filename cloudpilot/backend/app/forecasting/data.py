"""Loads a historical (resource, usage_type) time series from `usage_records`
and aggregates it to a continuous daily series suitable for forecasting.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.forecasting.enums import GAUGE_USAGE_TYPES
from app.models.resource import Resource
from app.models.usage_record import UsageRecord


class NoHistoricalDataError(Exception):
    pass


def load_daily_series(
    db: Session, resource: Resource, usage_type: str
) -> pd.Series:
    """Return a daily-indexed, gap-filled series for one (resource, usage_type).

    Flow metrics (requests, hours_used, network_gb) are summed per day;
    gauge metrics (storage_gb) are averaged per day. Missing days within
    the observed range are filled by linear interpolation (gaps of a few
    hours/days are extremely unlikely given hourly ingestion, but this
    keeps the series well-defined if any exist).
    """
    rows = (
        db.query(UsageRecord.timestamp, UsageRecord.quantity)
        .filter(
            UsageRecord.resource_id == resource.id,
            UsageRecord.usage_type == usage_type,
        )
        .order_by(UsageRecord.timestamp.asc())
        .all()
    )
    if not rows:
        raise NoHistoricalDataError(
            f"No usage_records found for resource={resource.external_id!r} "
            f"usage_type={usage_type!r}"
        )

    df = pd.DataFrame(rows, columns=["timestamp", "quantity"])
    df["date"] = pd.to_datetime(df["timestamp"]).dt.floor("D")

    # The first/last calendar day of the observed range is often partial
    # (ingestion started or "now" falls mid-day), which would otherwise
    # look like an artificial usage drop to the model. Trim any leading/
    # trailing day that has fewer readings than a typical full day;
    # interior gaps are left to the interpolation below.
    counts = df.groupby("date").size()
    expected_count = int(counts.mode().iloc[0])
    full_days = counts[counts >= expected_count].index
    if len(full_days) > 0:
        df = df[(df["date"] >= full_days.min()) & (df["date"] <= full_days.max())]

    if usage_type in GAUGE_USAGE_TYPES:
        daily = df.groupby("date")["quantity"].mean()
    else:
        daily = df.groupby("date")["quantity"].sum()

    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_index)
    daily = daily.interpolate(method="linear").bfill().ffill()
    daily.index.name = "date"
    daily.name = usage_type

    return daily
