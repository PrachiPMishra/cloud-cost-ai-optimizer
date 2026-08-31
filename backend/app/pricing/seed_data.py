"""Reference pricing data for the `pricing` table.

These are illustrative, public-cloud-like reference rates (order of
magnitude only) meant to make the engine usable out of the box in
development/demo environments — they are not a live pricing feed. Adding a
real provider's actual rates, or a second provider, means adding more rows
here (or via any other loader) with a different `provider` value; nothing
in `app.pricing.calculator` or `app.pricing.repository` needs to change.

Regional variation is modeled as a flat multiplier over a single set of
base rates purely to keep this table readable — a real feed would carry
each region's real number directly, which the rest of the engine treats
identically either way (multipliers are baked into the stored rate, not
computed at price time).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.pricing import Pricing
from app.pricing.enums import PricingModel, ServiceType

PROVIDER = "aws"
SOURCE = "cloudpilot-reference-rates-v1"
EFFECTIVE_DATE = date(2026, 1, 1)

REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
REGION_MULTIPLIER = {
    "us-east-1": 1.00,
    "us-west-2": 1.02,
    "eu-west-1": 1.08,
    "ap-southeast-1": 1.15,
}

# Shared tiered egress schedule reused by every service (network is priced
# the same way regardless of what generated it).
_EGRESS_TIERS = [(0, 10240, 0.09), (10240, 51200, 0.085), (51200, None, 0.07)]

# (resource_type, sku, unit, pricing_model, commitment_term_months, tiers)
# tiers: list[(tier_min, tier_max_or_None, price_per_unit)]
BASE_RATE_DEFINITIONS: list[dict] = [
    dict(
        resource_type=ServiceType.COMPUTE.value,
        sku="compute-instance-hour",
        unit="hour",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[(0, None, 0.096)],
    ),
    dict(
        resource_type=ServiceType.COMPUTE.value,
        sku="compute-instance-hour",
        unit="hour",
        pricing_model=PricingModel.RESERVED.value,
        commitment_term_months=12,
        tiers=[(0, None, 0.067)],
    ),
    dict(
        resource_type=ServiceType.COMPUTE.value,
        sku="compute-instance-hour",
        unit="hour",
        pricing_model=PricingModel.RESERVED.value,
        commitment_term_months=36,
        tiers=[(0, None, 0.048)],
    ),
    dict(
        resource_type=ServiceType.COMPUTE.value,
        sku="compute-network-egress",
        unit="gb",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=_EGRESS_TIERS,
    ),
    dict(
        resource_type=ServiceType.DATABASE.value,
        sku="database-instance-hour",
        unit="hour",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[(0, None, 0.145)],
    ),
    dict(
        resource_type=ServiceType.DATABASE.value,
        sku="database-instance-hour",
        unit="hour",
        pricing_model=PricingModel.RESERVED.value,
        commitment_term_months=12,
        tiers=[(0, None, 0.101)],
    ),
    dict(
        resource_type=ServiceType.DATABASE.value,
        sku="database-instance-hour",
        unit="hour",
        pricing_model=PricingModel.RESERVED.value,
        commitment_term_months=36,
        tiers=[(0, None, 0.073)],
    ),
    dict(
        resource_type=ServiceType.DATABASE.value,
        sku="database-storage",
        unit="gb-hour",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[
            (0, 100, 0.000158),
            (100, 500, 0.000144),
            (500, None, 0.000126),
        ],
    ),
    dict(
        resource_type=ServiceType.DATABASE.value,
        sku="database-requests",
        unit="request",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[(0, None, 0.0000002)],
    ),
    dict(
        resource_type=ServiceType.DATABASE.value,
        sku="database-network-egress",
        unit="gb",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=_EGRESS_TIERS,
    ),
    dict(
        resource_type=ServiceType.OBJECT_STORAGE.value,
        sku="objstorage-storage",
        unit="gb-hour",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[
            (0, 51200, 0.0000315),
            (51200, 512000, 0.0000301),
            (512000, None, 0.0000288),
        ],
    ),
    dict(
        resource_type=ServiceType.OBJECT_STORAGE.value,
        sku="objstorage-requests",
        unit="request",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[(0, None, 0.0000004)],
    ),
    dict(
        resource_type=ServiceType.OBJECT_STORAGE.value,
        sku="objstorage-network-egress",
        unit="gb",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=_EGRESS_TIERS,
    ),
    dict(
        resource_type=ServiceType.SERVERLESS.value,
        sku="serverless-invocation",
        unit="request",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[(0, None, 0.0000002)],
    ),
    dict(
        resource_type=ServiceType.SERVERLESS.value,
        sku="serverless-duration",
        unit="hour",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=[(0, None, 0.03)],
    ),
    dict(
        resource_type=ServiceType.SERVERLESS.value,
        sku="serverless-network-egress",
        unit="gb",
        pricing_model=PricingModel.ON_DEMAND.value,
        commitment_term_months=None,
        tiers=_EGRESS_TIERS,
    ),
]


def build_seed_rows(
    provider: str = PROVIDER,
    effective_date: date = EFFECTIVE_DATE,
    source: str = SOURCE,
) -> list[Pricing]:
    rows: list[Pricing] = []
    for region in REGIONS:
        multiplier = REGION_MULTIPLIER[region]
        for definition in BASE_RATE_DEFINITIONS:
            for tier_min, tier_max, rate in definition["tiers"]:
                rows.append(
                    Pricing(
                        provider=provider,
                        region=region,
                        resource_type=definition["resource_type"],
                        sku=definition["sku"],
                        unit=definition["unit"],
                        pricing_model=definition["pricing_model"],
                        commitment_term_months=definition["commitment_term_months"],
                        tier_min_unit=tier_min,
                        tier_max_unit=tier_max,
                        price_per_unit=round(rate * multiplier, 10),
                        currency="USD",
                        effective_date=effective_date,
                        source=source,
                    )
                )
    return rows


def seed_pricing(
    db: Session,
    provider: str = PROVIDER,
    effective_date: date = EFFECTIVE_DATE,
    source: str = SOURCE,
    replace: bool = False,
) -> int:
    """Insert the reference pricing rows if this (provider, date, source)
    version isn't already present. Returns the number of rows inserted."""
    existing_query = db.query(Pricing).filter(
        Pricing.provider == provider,
        Pricing.effective_date == effective_date,
        Pricing.source == source,
    )
    existing_count = existing_query.count()
    if existing_count and not replace:
        return 0
    if existing_count and replace:
        existing_query.delete(synchronize_session=False)

    rows = build_seed_rows(provider, effective_date, source)
    db.add_all(rows)
    db.commit()
    return len(rows)


def main() -> None:
    from app.models.base import SessionLocal

    db = SessionLocal()
    try:
        inserted = seed_pricing(db)
        print(f"Inserted {inserted} pricing rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()
