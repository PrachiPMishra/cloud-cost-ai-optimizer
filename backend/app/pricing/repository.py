"""DB-backed, versioned price lookup.

This module is the only place that touches the `pricing` table. The
calculator never embeds rates or provider specifics — it only consumes the
`Pricing` rows this module returns, keyed generically by
(provider, region, resource_type, sku, pricing_model[, commitment_term]).
Adding a new provider or region is purely a data change (insert more rows);
no code here or in the calculator needs to change.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.pricing import Pricing


def get_price_tiers(
    db: Session,
    *,
    provider: str,
    region: str,
    resource_type: str,
    sku: str,
    pricing_model: str,
    commitment_term_months: int | None = None,
    as_of: date | None = None,
) -> list[Pricing]:
    """Return all tier rows for the latest applicable pricing version.

    A "version" is identified by `effective_date`; tiers of the same
    version share that date. Returns an empty list if no pricing data
    matches — callers must treat that as a hard failure, not fall back to
    a guessed rate.
    """
    as_of = as_of or date.today()

    base_filters = [
        Pricing.provider == provider,
        Pricing.region == region,
        Pricing.resource_type == resource_type,
        Pricing.sku == sku,
        Pricing.pricing_model == pricing_model,
        Pricing.effective_date <= as_of,
    ]
    if commitment_term_months is not None:
        base_filters.append(Pricing.commitment_term_months == commitment_term_months)
    else:
        base_filters.append(Pricing.commitment_term_months.is_(None))

    latest_effective_date = (
        db.query(func.max(Pricing.effective_date)).filter(*base_filters).scalar()
    )
    if latest_effective_date is None:
        return []

    return (
        db.query(Pricing)
        .filter(*base_filters, Pricing.effective_date == latest_effective_date)
        .order_by(Pricing.tier_min_unit.asc())
        .all()
    )
