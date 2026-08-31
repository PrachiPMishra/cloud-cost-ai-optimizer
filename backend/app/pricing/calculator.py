"""Pricing calculation logic.

Deliberately provider-agnostic: everything here operates on `Pricing` rows
returned by `app.pricing.repository`, never on hardcoded rates or
provider-specific branches. Supporting a new provider is a data change
(insert rows via `app.pricing.seed_data` or any other loader), not a code
change here.
"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.models.pricing import Pricing
from app.pricing.enums import UsageMode
from app.pricing.repository import get_price_tiers
from app.pricing.schemas import CostCalculationRequest, CostCalculationResult, TierBreakdown


class PricingNotFoundError(Exception):
    """Raised when no pricing data matches the request. Never silently guessed."""


def _resolve_quantity(request: CostCalculationRequest) -> float:
    if request.usage_mode == UsageMode.FLAT:
        assert request.quantity is not None  # enforced by schema validator
        return request.quantity

    return sum(sample.quantity * sample.duration_hours for sample in request.usage_series)


def _apply_tiered_pricing(
    quantity: float, tiers: list[Pricing]
) -> tuple[float, list[TierBreakdown]]:
    total_cost = 0.0
    breakdown: list[TierBreakdown] = []

    for tier in tiers:
        lower = float(tier.tier_min_unit)
        upper = float(tier.tier_max_unit) if tier.tier_max_unit is not None else math.inf

        if quantity <= lower:
            continue

        amount_in_tier = min(quantity, upper) - lower
        if amount_in_tier <= 0:
            continue

        rate = float(tier.price_per_unit)
        subtotal = amount_in_tier * rate
        total_cost += subtotal
        breakdown.append(
            TierBreakdown(
                tier_min=lower,
                tier_max=None if math.isinf(upper) else upper,
                quantity=amount_in_tier,
                rate=rate,
                subtotal=subtotal,
            )
        )

    return total_cost, breakdown


def calculate_cost(
    request: CostCalculationRequest, db: Session
) -> CostCalculationResult:
    tiers = get_price_tiers(
        db,
        provider=request.provider,
        region=request.region,
        resource_type=request.service.value,
        sku=request.sku,
        pricing_model=request.pricing_model.value,
        commitment_term_months=request.commitment_term_months,
        as_of=request.as_of,
    )
    if not tiers:
        raise PricingNotFoundError(
            f"No pricing found for provider={request.provider!r} "
            f"region={request.region!r} service={request.service.value!r} "
            f"sku={request.sku!r} pricing_model={request.pricing_model.value!r} "
            f"commitment_term_months={request.commitment_term_months!r}"
        )

    quantity = _resolve_quantity(request)
    cost, breakdown = _apply_tiered_pricing(quantity, tiers)

    return CostCalculationResult(
        provider=request.provider,
        region=request.region,
        service=request.service,
        sku=request.sku,
        unit=request.unit,
        pricing_model=request.pricing_model,
        commitment_term_months=request.commitment_term_months,
        resource_id=request.resource_id,
        resolved_quantity=quantity,
        cost=cost,
        currency=tiers[0].currency,
        effective_date=tiers[0].effective_date,
        tiers_applied=breakdown,
    )
