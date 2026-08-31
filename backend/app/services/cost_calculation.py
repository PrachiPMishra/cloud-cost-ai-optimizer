"""Bridges ingested `usage_records` to the pricing engine.

Groups raw usage rows (one metric per row, as stored by
`app.services.data_ingestion`) by (resource, usage_type), turns each group
into a single billable quantity, maps it to a SKU via
`app.pricing.skus.SKU_CATALOG`, and prices it with
`app.pricing.calculator.calculate_cost`. This is the only place that knows
how a raw usage metric becomes a billable quantity — the pricing engine
itself only ever sees an already-resolved quantity in the SKU's unit.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.pricing.calculator import PricingNotFoundError, calculate_cost
from app.pricing.enums import PricingModel, ServiceType, UsageMode
from app.pricing.schemas import CostCalculationRequest, CostCalculationResult
from app.pricing.skus import NON_BILLABLE_USAGE_TYPES, SKU_CATALOG

# usage_types whose readings are point-in-time levels (gauges) rather than
# per-interval flow amounts — must be time-weighted, not simply summed.
GAUGE_USAGE_TYPES = {"storage_gb"}


class PriceUsageResult(BaseModel):
    line_items: list[CostCalculationResult]
    skipped: list[str]


def _interval_hours(timestamps: list[datetime]) -> float:
    if len(timestamps) < 2:
        return 1.0
    ordered = sorted(timestamps)
    deltas_hours = [
        (b - a).total_seconds() / 3600.0 for a, b in zip(ordered, ordered[1:])
    ]
    return statistics.median(deltas_hours) or 1.0


def price_usage_records(
    db: Session,
    *,
    provider: str,
    pricing_model: PricingModel = PricingModel.ON_DEMAND,
    commitment_term_months: int | None = None,
    resource_external_id: str | None = None,
    service: ServiceType | None = None,
    region: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> PriceUsageResult:
    query = db.query(UsageRecord, Resource).join(
        Resource, UsageRecord.resource_id == Resource.id
    )
    filters = [UsageRecord.provider == provider]
    if resource_external_id:
        filters.append(Resource.external_id == resource_external_id)
    if service:
        filters.append(Resource.resource_type == service.value)
    if region:
        filters.append(UsageRecord.region == region)
    if start:
        filters.append(UsageRecord.timestamp >= start)
    if end:
        filters.append(UsageRecord.timestamp < end)

    rows = query.filter(*filters).all()

    quantities: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    timestamps: dict[tuple[str, str, str, str], list[datetime]] = defaultdict(list)

    for usage_record, resource in rows:
        if usage_record.usage_type in NON_BILLABLE_USAGE_TYPES:
            continue
        key = (
            resource.external_id,
            resource.resource_type,
            usage_record.region,
            usage_record.usage_type,
        )
        quantities[key].append(float(usage_record.quantity))
        timestamps[key].append(usage_record.timestamp)

    line_items: list[CostCalculationResult] = []
    skipped: list[str] = []

    for (external_id, resource_type, rgn, usage_type), values in quantities.items():
        try:
            service_enum = ServiceType(resource_type)
        except ValueError:
            skipped.append(f"{external_id}: unknown resource_type {resource_type!r}")
            continue

        sku_info = SKU_CATALOG.get(service_enum, {}).get(usage_type)
        if sku_info is None:
            skipped.append(
                f"{external_id}: no SKU mapping for {service_enum.value}/{usage_type}"
            )
            continue
        sku, unit = sku_info

        if usage_type in GAUGE_USAGE_TYPES:
            interval_hours = _interval_hours(timestamps[(external_id, resource_type, rgn, usage_type)])
            billable_quantity = sum(values) * interval_hours
        else:
            billable_quantity = sum(values)

        request = CostCalculationRequest(
            provider=provider,
            region=rgn,
            service=service_enum,
            sku=sku,
            unit=unit,
            pricing_model=pricing_model,
            commitment_term_months=commitment_term_months,
            usage_mode=UsageMode.FLAT,
            quantity=billable_quantity,
            resource_id=external_id,
        )
        try:
            line_items.append(calculate_cost(request, db))
        except PricingNotFoundError as exc:
            skipped.append(str(exc))

    return PriceUsageResult(line_items=line_items, skipped=skipped)
