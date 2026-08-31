from typing import Literal

from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.forecasting.enums import ForecastHorizon
from app.pricing.enums import ServiceType
from app.services.cost_calculation import price_usage_records
from app.services.cost_drivers import CostDriverReport, rank_cost_drivers
from app.services.cost_prediction import (
    NoForecastableLineItemsError,
    NoResourcesInScopeError,
    predict_bill,
)
from app.tools.base import ToolError, run_tool

TOOL_IDENTIFY_COST_DRIVERS = "identify_cost_drivers"


class IdentifyCostDriversInput(BaseModel):
    provider: str
    resource_id: str | None = None
    service: ServiceType | None = None
    source: Literal["current", "forecasted"] = "current"
    horizon: ForecastHorizon | None = None
    top_n: int = 5

    @model_validator(mode="after")
    def validate_horizon(self) -> "IdentifyCostDriversInput":
        if self.source == "forecasted" and self.horizon is None:
            raise ValueError("horizon is required when source='forecasted'")
        return self


def identify_cost_drivers(
    db: Session, *, agent_name: str, session_id: str, input: IdentifyCostDriversInput
) -> CostDriverReport:
    def _impl() -> CostDriverReport:
        if input.source == "current":
            result = price_usage_records(
                db, provider=input.provider, resource_external_id=input.resource_id, service=input.service
            )
            items = [(f"{li.resource_id}:{li.sku}", li.cost) for li in result.line_items]
        else:
            try:
                summary = predict_bill(
                    db,
                    provider=input.provider,
                    horizon=input.horizon,
                    resource_external_id=input.resource_id,
                    service=input.service,
                )
            except (NoResourcesInScopeError, NoForecastableLineItemsError) as exc:
                raise ToolError(str(exc)) from exc
            items = [(f"{li.resource_id}:{li.sku}", li.predicted_cost) for li in summary.line_items]

        if not items:
            raise ToolError("No cost line items found to rank")

        return rank_cost_drivers(items, top_n=input.top_n)

    return run_tool(
        db, agent_name=agent_name, session_id=session_id, tool_name=TOOL_IDENTIFY_COST_DRIVERS,
        input_model=input, fn=_impl,
    )
