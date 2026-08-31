import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.forecasting.enums import ForecastHorizon
from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.pricing.enums import ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.tools.base import ToolError
from app.tools.cost_analysis import IdentifyCostDriversInput, identify_cost_drivers

HISTORY_DAYS = 60
AGENT_NAME = "test_agent"


@pytest.fixture(scope="module", autouse=True)
def _ensure_seed_data():
    db = SessionLocal()
    try:
        seed_pricing(db)
    finally:
        db.close()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def session_id():
    return str(uuid.uuid4())


@pytest.fixture()
def compute_resource(db):
    external_id = f"test-driver-compute-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type=ServiceType.COMPUTE.value,
        provider=PROVIDER,
        region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    rng = np.random.default_rng(7)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
    for usage_type, base in (("requests", 200.0), ("hours_used", 1.0), ("network_gb", 2.0)):
        values = np.clip(base + rng.normal(0, base * 0.05, len(timestamps)), 0, None)
        db.add_all(
            UsageRecord(
                resource_id=resource.id,
                timestamp=ts.to_pydatetime(),
                usage_type=usage_type,
                quantity=float(v),
                unit="unit",
                provider=resource.provider,
                region=resource.region,
            )
            for ts, v in zip(timestamps, values)
        )
    db.commit()

    yield resource

    forecast_ids = [f.id for f in db.query(Forecast).all() if f.resource_id == resource.id]
    if forecast_ids:
        db.execute(delete(CostPrediction).where(CostPrediction.forecast_id.in_(forecast_ids)))
        db.execute(delete(Forecast).where(Forecast.id.in_(forecast_ids)))
    db.execute(delete(AgentEvent).where(AgentEvent.session_id.like("test-%")))
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_identify_cost_drivers_forecasted_source(db, session_id, compute_resource) -> None:
    output = identify_cost_drivers(
        db,
        agent_name=AGENT_NAME,
        session_id=session_id,
        input=IdentifyCostDriversInput(
            provider=PROVIDER,
            resource_id=compute_resource.external_id,
            source="forecasted",
            horizon=ForecastHorizon.WEEK,
        ),
    )

    assert len(output.drivers) > 0
    assert all(d.cost >= 0 for d in output.drivers)

    events = (
        db.query(AgentEvent)
        .filter(AgentEvent.session_id == session_id, AgentEvent.tool_name == "identify_cost_drivers")
        .all()
    )
    assert len(events) == 1
    assert events[0].output["status"] == "success"


def test_identify_cost_drivers_forecasted_requires_horizon() -> None:
    with pytest.raises(ValueError, match="horizon is required"):
        IdentifyCostDriversInput(provider=PROVIDER, source="forecasted")


def test_identify_cost_drivers_forecasted_unknown_resource_raises_tool_error(db, session_id) -> None:
    with pytest.raises(ToolError):
        identify_cost_drivers(
            db,
            agent_name=AGENT_NAME,
            session_id=session_id,
            input=IdentifyCostDriversInput(
                provider=PROVIDER,
                resource_id="does-not-exist",
                source="forecasted",
                horizon=ForecastHorizon.WEEK,
            ),
        )

    events = (
        db.query(AgentEvent)
        .filter(AgentEvent.session_id == session_id, AgentEvent.tool_name == "identify_cost_drivers")
        .all()
    )
    assert len(events) == 1
    assert events[0].output["status"] == "error"
