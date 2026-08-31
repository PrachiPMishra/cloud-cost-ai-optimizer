from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.base import get_db
from app.services.currency import get_usd_to_inr_rate

router = APIRouter()


class SettingsResponse(BaseModel):
    app_name: str
    gemini_model: str
    gemini_configured: bool
    database_connected: bool
    # Display-only — see app/services/currency.py. Every monetary value in
    # every other response from this API is USD; the frontend uses this
    # rate to reformat those already-fetched figures for display.
    usd_to_inr_rate: float


@router.get("", response_model=SettingsResponse)
def get_settings_endpoint(db: Session = Depends(get_db)) -> SettingsResponse:
    settings = get_settings()

    try:
        db.execute(text("SELECT 1"))
        database_connected = True
    except Exception:
        database_connected = False

    return SettingsResponse(
        app_name=settings.app_name,
        gemini_model=settings.gemini_model,
        gemini_configured=bool(settings.gemini_api_key),
        database_connected=database_connected,
        usd_to_inr_rate=get_usd_to_inr_rate(),
    )
