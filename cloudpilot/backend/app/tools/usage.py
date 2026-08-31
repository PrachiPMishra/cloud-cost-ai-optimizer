from datetime import date

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.data import NoHistoricalDataError, load_daily_series
from app.models.resource import Resource
from app.tools.base import ToolError, run_tool

TOOL_GET_USAGE_HISTORY = "get_usage_history"
TOOL_GET_CURRENT_RESOURCES = "get_current_resources"


class GetUsageHistoryInput(BaseModel):
    resource_id: str
    usage_type: str


class UsagePoint(BaseModel):
    date: date
    quantity: float


class GetUsageHistoryOutput(BaseModel):
    resource_id: str
    usage_type: str
    points: list[UsagePoint]


def get_usage_history(
    db: Session, *, agent_name: str, session_id: str, input: GetUsageHistoryInput
) -> GetUsageHistoryOutput:
    def _impl() -> GetUsageHistoryOutput:
        resource = db.query(Resource).filter(Resource.external_id == input.resource_id).first()
        if resource is None:
            raise ToolError(f"No resource with external_id={input.resource_id!r}")
        try:
            series = load_daily_series(db, resource, input.usage_type)
        except NoHistoricalDataError as exc:
            raise ToolError(str(exc)) from exc

        return GetUsageHistoryOutput(
            resource_id=input.resource_id,
            usage_type=input.usage_type,
            points=[UsagePoint(date=d.date(), quantity=float(q)) for d, q in series.items()],
        )

    return run_tool(
        db,
        agent_name=agent_name,
        session_id=session_id,
        tool_name=TOOL_GET_USAGE_HISTORY,
        input_model=input,
        fn=_impl,
    )


class GetCurrentResourcesInput(BaseModel):
    provider: str
    service: str | None = None


class ResourceSummary(BaseModel):
    resource_id: str
    service: str
    region: str
    provider: str


class GetCurrentResourcesOutput(BaseModel):
    resources: list[ResourceSummary]


def get_current_resources(
    db: Session, *, agent_name: str, session_id: str, input: GetCurrentResourcesInput
) -> GetCurrentResourcesOutput:
    def _impl() -> GetCurrentResourcesOutput:
        query = db.query(Resource).filter(Resource.provider == input.provider)
        if input.service:
            query = query.filter(Resource.resource_type == input.service)
        rows = query.all()

        return GetCurrentResourcesOutput(
            resources=[
                ResourceSummary(
                    resource_id=r.external_id,
                    service=r.resource_type,
                    region=r.region,
                    provider=r.provider,
                )
                for r in rows
            ]
        )

    return run_tool(
        db,
        agent_name=agent_name,
        session_id=session_id,
        tool_name=TOOL_GET_CURRENT_RESOURCES,
        input_model=input,
        fn=_impl,
    )
