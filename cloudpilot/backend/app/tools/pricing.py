from datetime import date

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.enums import ForecastHorizon
from app.pricing.enums import PricingModel, ServiceType
from app.pricing.repository import get_price_tiers
from app.services.cost_calculation import PriceUsageResult, price_usage_records
from app.services.cost_prediction import (
    CostPredictionSummary,
    NoForecastableLineItemsError,
    NoResourcesInScopeError,
    predict_bill,
)
from app.tools.base import ToolError, run_tool

TOOL_GET_PRICING = "get_pricing"
TOOL_CALCULATE_CURRENT_COST = "calculate_current_cost"
TOOL_CALCULATE_FORECASTED_COST = "calculate_forecasted_cost"


class GetPricingInput(BaseModel):
    provider: str
    region: str
    service: ServiceType
    sku: str
    pricing_model: PricingModel = PricingModel.ON_DEMAND
    commitment_term_months: int | None = None


class PriceTierOut(BaseModel):
    tier_min: float
    tier_max: float | None
    price_per_unit: float
    unit: str
    currency: str
    effective_date: date


class GetPricingOutput(BaseModel):
    tiers: list[PriceTierOut]


def get_pricing(
    db: Session, *, agent_name: str, session_id: str, input: GetPricingInput
) -> GetPricingOutput:
    def _impl() -> GetPricingOutput:
        rows = get_price_tiers(
            db,
            provider=input.provider,
            region=input.region,
            resource_type=input.service.value,
            sku=input.sku,
            pricing_model=input.pricing_model.value,
            commitment_term_months=input.commitment_term_months,
        )
        if not rows:
            raise ToolError(
                f"No pricing found for provider={input.provider!r} region={input.region!r} "
                f"service={input.service.value!r} sku={input.sku!r} "
                f"pricing_model={input.pricing_model.value!r}"
            )
        return GetPricingOutput(
            tiers=[
                PriceTierOut(
                    tier_min=float(r.tier_min_unit),
                    tier_max=float(r.tier_max_unit) if r.tier_max_unit is not None else None,
                    price_per_unit=float(r.price_per_unit),
                    unit=r.unit,
                    currency=r.currency,
                    effective_date=r.effective_date,
                )
                for r in rows
            ]
        )

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_GET_PRICING,
        input_model=input, fn=_impl,
    )


class CalculateCurrentCostInput(BaseModel):
    provider: str
    resource_id: str | None = None
    service: ServiceType | None = None
    pricing_model: PricingModel = PricingModel.ON_DEMAND


def calculate_current_cost(
    db: Session, *, agent_name: str, session_id: str, input: CalculateCurrentCostInput
) -> PriceUsageResult:
    def _impl() -> PriceUsageResult:
        result = price_usage_records(
            db,
            provider=input.provider,
            pricing_model=input.pricing_model,
            resource_external_id=input.resource_id,
            service=input.service,
        )
        if not result.line_items:
            raise ToolError("No priceable current usage found for the given scope")
        return result

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_CALCULATE_CURRENT_COST,
        input_model=input, fn=_impl,
    )


class CalculateForecastedCostInput(BaseModel):
    provider: str
    resource_id: str | None = None
    service: ServiceType | None = None
    horizon: ForecastHorizon
    pricing_model: PricingModel = PricingModel.ON_DEMAND
    commitment_term_months: int | None = None


def calculate_forecasted_cost(
    db: Session, *, agent_name: str, session_id: str, input: CalculateForecastedCostInput
) -> CostPredictionSummary:
    def _impl() -> CostPredictionSummary:
        try:
            return predict_bill(
                db,
                provider=input.provider,
                horizon=input.horizon,
                pricing_model=input.pricing_model,
                commitment_term_months=input.commitment_term_months,
                resource_external_id=input.resource_id,
                service=input.service,
            )
        except (NoResourcesInScopeError, NoForecastableLineItemsError) as exc:
            raise ToolError(str(exc)) from exc

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_CALCULATE_FORECASTED_COST,
        input_model=input, fn=_impl,
    )
