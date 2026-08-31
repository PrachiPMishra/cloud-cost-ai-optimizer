"""Validation and persistence for uploaded usage/billing data.

Accepts rows shaped like the synthetic dataset schema (see
`app.services.synthetic_data`) — one row per (timestamp, resource) with
several metrics — and fans each row out into one `usage_records` row per
metric present, since `usage_records` stores one (usage_type, quantity,
unit) measurement per row.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.models.resource import Resource
from app.models.usage_record import UsageRecord

VALID_SERVICES = {"Compute", "Database", "Object Storage", "Serverless"}

# (field name, unit) for the metric columns that become usage_records rows.
METRIC_FIELDS: list[tuple[str, str]] = [
    ("cpu_utilization", "percent"),
    ("memory_utilization", "percent"),
    ("requests", "count"),
    ("storage_gb", "gb"),
    ("network_gb", "gb"),
    ("hours_used", "hours"),
]


class UsageRowIngest(BaseModel):
    timestamp: datetime
    service: str
    resource: str
    region: str
    cpu_utilization: float | None = Field(default=None, ge=0, le=100)
    memory_utilization: float | None = Field(default=None, ge=0, le=100)
    requests: float | None = Field(default=None, ge=0)
    storage_gb: float | None = Field(default=None, ge=0)
    network_gb: float | None = Field(default=None, ge=0)
    hours_used: float | None = Field(default=None, ge=0)
    current_cost: float | None = Field(default=None, ge=0)
    provider: str = "synthetic"

    @field_validator("service")
    @classmethod
    def validate_service(cls, value: str) -> str:
        if value not in VALID_SERVICES:
            raise ValueError(
                f"service must be one of {sorted(VALID_SERVICES)}, got {value!r}"
            )
        return value

    @field_validator("timestamp")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class RowError(BaseModel):
    row_index: int
    error: str


class IngestSummary(BaseModel):
    rows_received: int
    rows_valid: int
    rows_failed: int
    usage_records_inserted: int
    resources_created: int
    resources_updated: int
    errors: list[RowError]


class PersistResult(BaseModel):
    usage_records_inserted: int
    resources_created: int
    resources_updated: int


class UnsupportedFileFormatError(ValueError):
    pass


def parse_upload(content: bytes, filename: str) -> list[dict]:
    """Parse an uploaded CSV or JSON file into a list of raw row dicts."""
    lower_name = filename.lower()
    if lower_name.endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        if isinstance(data, dict):
            data = data.get("records", data.get("data", [data]))
        if not isinstance(data, list):
            raise UnsupportedFileFormatError("JSON payload must be a list of records")
        return data
    if lower_name.endswith(".csv"):
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)
    raise UnsupportedFileFormatError(
        f"Unsupported file extension for {filename!r}; expected .csv or .json"
    )


def validate_rows(
    raw_rows: list[dict],
) -> tuple[list[UsageRowIngest], list[RowError]]:
    valid: list[UsageRowIngest] = []
    errors: list[RowError] = []

    for idx, raw in enumerate(raw_rows):
        cleaned = {k: v for k, v in raw.items() if v not in (None, "")}
        try:
            valid.append(UsageRowIngest(**cleaned))
        except Exception as exc:  # pydantic.ValidationError or type errors
            errors.append(RowError(row_index=idx, error=str(exc)))

    return valid, errors


def _get_or_create_resource(
    db: Session, row: UsageRowIngest, cache: dict[str, Resource]
) -> tuple[Resource, bool, bool]:
    cache_key = row.resource
    if cache_key in cache:
        resource = cache[cache_key]
        updated = False
    else:
        resource = (
            db.query(Resource).filter(Resource.external_id == row.resource).first()
        )
        updated = False
        if resource is None:
            resource = Resource(
                external_id=row.resource,
                name=row.resource,
                resource_type=row.service,
                provider=row.provider,
                region=row.region,
            )
            db.add(resource)
            db.flush()
            cache[cache_key] = resource
            return resource, True, False

        if resource.region != row.region or resource.resource_type != row.service:
            resource.region = row.region
            resource.resource_type = row.service
            updated = True

        cache[cache_key] = resource

    return resource, False, updated


def persist_rows(db: Session, rows: list[UsageRowIngest]) -> PersistResult:
    resource_cache: dict[str, Resource] = {}
    resources_created = 0
    resources_updated = 0
    usage_records: list[UsageRecord] = []

    for row in rows:
        resource, created, updated = _get_or_create_resource(db, row, resource_cache)
        resources_created += int(created)
        resources_updated += int(updated)

        for field_name, unit in METRIC_FIELDS:
            value = getattr(row, field_name)
            if value is None:
                continue
            usage_records.append(
                UsageRecord(
                    resource_id=resource.id,
                    timestamp=row.timestamp,
                    usage_type=field_name,
                    quantity=value,
                    unit=unit,
                    cost=None,
                    provider=row.provider,
                    region=row.region,
                )
            )

        if row.current_cost is not None:
            usage_records.append(
                UsageRecord(
                    resource_id=resource.id,
                    timestamp=row.timestamp,
                    usage_type="cost",
                    quantity=row.current_cost,
                    unit="usd",
                    cost=row.current_cost,
                    provider=row.provider,
                    region=row.region,
                )
            )

    db.add_all(usage_records)
    db.commit()

    return PersistResult(
        usage_records_inserted=len(usage_records),
        resources_created=resources_created,
        resources_updated=resources_updated,
    )
