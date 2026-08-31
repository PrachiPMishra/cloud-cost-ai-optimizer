"""Canonical SKU catalog: which usage metrics are billable per service, and
under what SKU/unit. Shared by seed data (what to price) and by
`app.services.cost_calculation` (how to turn an ingested usage_records
metric into a priceable SKU) so the two stay in lockstep.

`cpu_utilization` and `memory_utilization` are intentionally absent: no
public cloud bills raw utilization directly, so there is no SKU for them —
they are rightsizing/optimization signals, not billable quantities.
"""

from __future__ import annotations

from app.pricing.enums import ServiceType

# usage_type (as stored in usage_records) -> (sku, unit)
SKU_CATALOG: dict[ServiceType, dict[str, tuple[str, str]]] = {
    ServiceType.COMPUTE: {
        "hours_used": ("compute-instance-hour", "hour"),
        "network_gb": ("compute-network-egress", "gb"),
    },
    ServiceType.DATABASE: {
        "hours_used": ("database-instance-hour", "hour"),
        "storage_gb": ("database-storage", "gb-hour"),
        "requests": ("database-requests", "request"),
        "network_gb": ("database-network-egress", "gb"),
    },
    ServiceType.OBJECT_STORAGE: {
        "storage_gb": ("objstorage-storage", "gb-hour"),
        "requests": ("objstorage-requests", "request"),
        "network_gb": ("objstorage-network-egress", "gb"),
    },
    ServiceType.SERVERLESS: {
        "requests": ("serverless-invocation", "request"),
        "hours_used": ("serverless-duration", "hour"),
        "network_gb": ("serverless-network-egress", "gb"),
    },
}

# usage_type values that are gauges/monitoring signals, never priced.
NON_BILLABLE_USAGE_TYPES = {"cpu_utilization", "memory_utilization", "cost"}
