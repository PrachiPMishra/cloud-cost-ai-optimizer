from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.data import NoHistoricalDataError, load_daily_series
from app.forecasting.engine import InsufficientHistoryError, run_forecast
from app.forecasting.enums import ForecastHorizon
from app.forecasting.schemas import ForecastRunResult
from app.models.resource import Resource
from app.tools.base import ToolError, run_tool

TOOL_FORECAST_USAGE = "forecast_usage"


class ForecastUsageInput(BaseModel):
    resource_id: str
    usage_type: str
    horizon: ForecastHorizon


def forecast_usage(
    db: Session, *, agent_name: str, session_id: str, input: ForecastUsageInput
) -> ForecastRunResult:
    def _impl() -> ForecastRunResult:
        resource = db.query(Resource).filter(Resource.external_id == input.resource_id).first()
        if resource is None:
            raise ToolError(f"No resource with external_id={input.resource_id!r}")
        try:
            series = load_daily_series(db, resource, input.usage_type)
            return run_forecast(series, resource.external_id, input.usage_type, input.horizon)
        except (NoHistoricalDataError, InsufficientHistoryError) as exc:
            raise ToolError(str(exc)) from exc

    return run_tool(
        db,
        agent_name=agent_name,
        session_id=session_id,
        tool_name=TOOL_FORECAST_USAGE,
        input_model=input,
        fn=_impl,
    )
