from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.enums import ForecastHorizon
from app.models.base import get_db
from app.pricing.enums import PricingModel, ServiceType
from app.services.cost_calculation import PriceUsageResult, price_usage_records
from app.services.cost_drivers import CostDriverReport, rank_cost_drivers
from app.services.cost_prediction import (
    BillNotFoundError,
    CostPredictionSummary,
    NoForecastableLineItemsError,
    NoResourcesInScopeError,
    get_stored_breakdown,
    predict_bill,
)

router = APIRouter()


class CostPredictRequest(BaseModel):
    provider: str
    horizon: ForecastHorizon
    pricing_model: PricingModel = PricingModel.ON_DEMAND
    commitment_term_months: int | None = None
    resource_id: str | None = None
    service: ServiceType | None = None


@router.post("/predict", response_model=CostPredictionSummary)
def predict_cost_endpoint(
    request: CostPredictRequest, db: Session = Depends(get_db)
) -> CostPredictionSummary:
    try:
        return predict_bill(
            db,
            provider=request.provider,
            horizon=request.horizon,
            pricing_model=request.pricing_model,
            commitment_term_months=request.commitment_term_months,
            resource_external_id=request.resource_id,
            service=request.service,
        )
    except NoResourcesInScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoForecastableLineItemsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/breakdown", response_model=CostPredictionSummary)
def get_cost_breakdown_endpoint(
    forecast_id: int | None = None, db: Session = Depends(get_db)
) -> CostPredictionSummary:
    try:
        return get_stored_breakdown(db, forecast_id)
    except BillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/current", response_model=PriceUsageResult)
def get_current_cost_endpoint(
    provider: str,
    resource_id: str | None = None,
    service: ServiceType | None = None,
    pricing_model: PricingModel = PricingModel.ON_DEMAND,
    db: Session = Depends(get_db),
) -> PriceUsageResult:
    return price_usage_records(
        db,
        provider=provider,
        pricing_model=pricing_model,
        resource_external_id=resource_id,
        service=service,
    )


@router.get("/drivers", response_model=CostDriverReport)
def get_cost_drivers_endpoint(
    provider: str,
    resource_id: str | None = None,
    service: ServiceType | None = None,
    source: Literal["current", "forecasted"] = "current",
    horizon: ForecastHorizon | None = None,
    top_n: int = 5,
    db: Session = Depends(get_db),
) -> CostDriverReport:
    if source == "current":
        result = price_usage_records(db, provider=provider, resource_external_id=resource_id, service=service)
        items = [(f"{li.resource_id}:{li.sku}", li.cost) for li in result.line_items]
    else:
        if horizon is None:
            raise HTTPException(status_code=422, detail="horizon is required when source='forecasted'")
        try:
            summary = predict_bill(
                db, provider=provider, horizon=horizon, resource_external_id=resource_id, service=service
            )
        except (NoResourcesInScopeError, NoForecastableLineItemsError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        items = [(f"{li.resource_id}:{li.sku}", li.predicted_cost) for li in summary.line_items]

    if not items:
        raise HTTPException(status_code=404, detail="No cost line items found to rank")

    return rank_cost_drivers(items, top_n=top_n)
