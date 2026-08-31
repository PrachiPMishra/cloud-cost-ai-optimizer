from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.data import NoHistoricalDataError, load_daily_series
from app.models.base import get_db
from app.models.resource import Resource

router = APIRouter()


class UsagePointOut(BaseModel):
    date: date
    quantity: float


class UsageHistoryResponse(BaseModel):
    resource_id: str
    usage_type: str
    points: list[UsagePointOut]


@router.get("/history", response_model=UsageHistoryResponse)
def get_usage_history_endpoint(
    resource_id: str, usage_type: str, db: Session = Depends(get_db)
) -> UsageHistoryResponse:
    resource = db.query(Resource).filter(Resource.external_id == resource_id).first()
    if resource is None:
        raise HTTPException(status_code=404, detail=f"No resource with external_id={resource_id!r}")

    try:
        series = load_daily_series(db, resource, usage_type)
    except NoHistoricalDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return UsageHistoryResponse(
        resource_id=resource_id,
        usage_type=usage_type,
        points=[UsagePointOut(date=d.date(), quantity=float(q)) for d, q in series.items()],
    )
