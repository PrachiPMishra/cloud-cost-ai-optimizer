from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.pricing.enums import PricingModel, ServiceType, UsageMode


class UsageSample(BaseModel):
    """One (quantity, duration) sample used for time-weighted quantity."""

    quantity: float = Field(ge=0)
    duration_hours: float = Field(gt=0)


class CostCalculationRequest(BaseModel):
    provider: str
    region: str
    service: ServiceType
    sku: str
    unit: str
    pricing_model: PricingModel = PricingModel.ON_DEMAND
    commitment_term_months: int | None = Field(default=None, ge=1)
    usage_mode: UsageMode = UsageMode.FLAT
    quantity: float | None = Field(default=None, ge=0)
    usage_series: list[UsageSample] | None = None
    resource_id: str | None = None
    as_of: date | None = None

    @model_validator(mode="after")
    def validate_quantity_matches_mode(self) -> "CostCalculationRequest":
        if self.usage_mode == UsageMode.FLAT:
            if self.quantity is None:
                raise ValueError("quantity is required when usage_mode is 'flat'")
            if self.usage_series:
                raise ValueError("usage_series must not be set when usage_mode is 'flat'")
        else:
            if not self.usage_series:
                raise ValueError(
                    "usage_series is required and must be non-empty when "
                    "usage_mode is 'autoscaling'"
                )
            if self.quantity is not None:
                raise ValueError(
                    "quantity must not be set when usage_mode is 'autoscaling'"
                )

        if self.pricing_model == PricingModel.RESERVED and not self.commitment_term_months:
            raise ValueError(
                "commitment_term_months is required when pricing_model is 'reserved'"
            )

        return self


class TierBreakdown(BaseModel):
    tier_min: float
    tier_max: float | None
    quantity: float
    rate: float
    subtotal: float


class CostCalculationResult(BaseModel):
    provider: str
    region: str
    service: ServiceType
    sku: str
    unit: str
    pricing_model: PricingModel
    commitment_term_months: int | None
    resource_id: str | None
    resolved_quantity: float
    cost: float
    currency: str
    effective_date: date
    tiers_applied: list[TierBreakdown]
