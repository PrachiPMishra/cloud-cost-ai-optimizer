"""Tier catalogs for the optimizer.

Every tier's cost is expressed as a **multiplier on the base on-demand (or
reserved) rate looked up from the real pricing engine** — not a separate
price. This keeps every scenario's cost genuinely priced by
`app.pricing.calculator.calculate_cost` while letting the tier catalog stay
a plain data table with no pricing data of its own to keep in sync.

`capacity_per_hour` / `base_latency_ms` / `base_failure_rate` are
illustrative, documented reference numbers (see `app.optimization.heuristics`
for how they're used) — not measured telemetry.
"""

from __future__ import annotations

from app.optimization.enums import InstanceTier, ServerlessMemoryTier, StorageTier
from app.pricing.enums import ServiceType

# capacity_per_hour: requests/queries one instance of this tier can serve
#   per hour at `base_latency_ms` (i.e. near-idle).
# cost_multiplier: multiplier on the base on-demand/reserved instance-hour
#   rate for this resource's service.
# base_latency_ms: latency heuristic's idle-latency term (see heuristics.py).
# base_failure_rate: probability a single instance of this tier is
#   unavailable at any given time (see heuristics.py's redundancy model).
INSTANCE_TIER_CATALOG: dict[ServiceType, dict[InstanceTier, dict]] = {
    ServiceType.COMPUTE: {
        InstanceTier.SMALL: dict(
            capacity_per_hour=100.0, cost_multiplier=0.5, base_latency_ms=40.0, base_failure_rate=0.02
        ),
        InstanceTier.MEDIUM: dict(
            capacity_per_hour=300.0, cost_multiplier=1.0, base_latency_ms=30.0, base_failure_rate=0.01
        ),
        InstanceTier.LARGE: dict(
            capacity_per_hour=900.0, cost_multiplier=2.2, base_latency_ms=20.0, base_failure_rate=0.005
        ),
    },
    ServiceType.DATABASE: {
        InstanceTier.SMALL: dict(
            capacity_per_hour=1500.0, cost_multiplier=0.5, base_latency_ms=15.0, base_failure_rate=0.02
        ),
        InstanceTier.MEDIUM: dict(
            capacity_per_hour=4000.0, cost_multiplier=1.0, base_latency_ms=10.0, base_failure_rate=0.01
        ),
        InstanceTier.LARGE: dict(
            capacity_per_hour=10000.0, cost_multiplier=2.2, base_latency_ms=6.0, base_failure_rate=0.005
        ),
    },
}

# sku_multiplier: multiplier on the base objstorage-storage / database-storage
#   on-demand rate. base_latency_ms / availability: fixed per-tier constants
#   (object storage tiers don't get faster with more "instances" — redundancy
#   is provider-managed and identical across tiers in this model except for
#   the documented availability figure below).
STORAGE_TIER_CATALOG: dict[StorageTier, dict] = {
    StorageTier.STANDARD: dict(sku_multiplier=1.0, base_latency_ms=10.0, availability=0.9999),
    StorageTier.INFREQUENT_ACCESS: dict(sku_multiplier=0.45, base_latency_ms=80.0, availability=0.999),
}

# duration_multiplier: multiplier on a fixed reference invocation duration —
#   more memory finishes CPU-bound work faster (a common, documented
#   real-world serverless tuning pattern).
# cost_multiplier: multiplier on the base serverless-duration on-demand rate
#   — more memory costs more per unit of time billed.
SERVERLESS_MEMORY_TIER_CATALOG: dict[ServerlessMemoryTier, dict] = {
    ServerlessMemoryTier.MEM_128: dict(memory_gb=0.125, duration_multiplier=3.5, cost_multiplier=0.45),
    ServerlessMemoryTier.MEM_512: dict(memory_gb=0.5, duration_multiplier=1.0, cost_multiplier=1.0),
    ServerlessMemoryTier.MEM_1024: dict(memory_gb=1.0, duration_multiplier=0.55, cost_multiplier=1.9),
    ServerlessMemoryTier.MEM_2048: dict(memory_gb=2.0, duration_multiplier=0.32, cost_multiplier=3.6),
}

# Fixed heuristic constants for services without a tunable capacity/latency
# knob in this model (serverless duration is billed as an hours_used-style
# quantity per invocation).
SERVERLESS_BASE_DURATION_HOURS = 0.0003  # ~1.1s reference invocation duration
SERVERLESS_BASE_LATENCY_MS = 200.0  # reference end-to-end invocation latency at baseline memory
SERVERLESS_BASE_AVAILABILITY = 0.9995  # fixed managed-service SLA figure

RESERVED_COMMITMENT_TERMS_MONTHS = (12, 36)
