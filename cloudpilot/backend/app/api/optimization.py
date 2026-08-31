from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.forecasting.enums import ForecastHorizon
from app.models.base import get_db
from app.services.optimization_service import (
    InsufficientDemandDataError,
    OptimizationRunNotFoundError,
    OptimizationRunSummary,
    ResourceNotFoundError,
    UnsupportedServiceError,
    get_latest_optimization_run,
    get_optimization_run,
    run_optimization,
)

router = APIRouter()


class OptimizationRunRequest(BaseModel):
    provider: str
    resource_id: str
    horizon: ForecastHorizon
    max_latency_ms: float = Field(gt=0)
    min_availability: float = Field(gt=0, le=1)
    budget: float = Field(gt=0)


@router.post("/run", response_model=OptimizationRunSummary)
def run_optimization_endpoint(
    request: OptimizationRunRequest, db: Session = Depends(get_db)
) -> OptimizationRunSummary:
    try:
        return run_optimization(
            db,
            provider=request.provider,
            resource_external_id=request.resource_id,
            horizon=request.horizon,
            max_latency_ms=request.max_latency_ms,
            min_availability=request.min_availability,
            budget=request.budget,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (UnsupportedServiceError, InsufficientDemandDataError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/latest", response_model=OptimizationRunSummary)
def get_latest_optimization_run_endpoint(
    resource_id: str | None = None, db: Session = Depends(get_db)
) -> OptimizationRunSummary:
    try:
        return get_latest_optimization_run(db, resource_id)
    except OptimizationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{optimization_run_id}", response_model=OptimizationRunSummary)
def get_optimization_run_endpoint(
    optimization_run_id: int, db: Session = Depends(get_db)
) -> OptimizationRunSummary:
    try:
        return get_optimization_run(db, optimization_run_id)
    except OptimizationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
