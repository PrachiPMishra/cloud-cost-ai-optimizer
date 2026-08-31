import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.optimization.enums import ScenarioType
from app.pricing.enums import PricingModel, ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.tools.base import ToolError
from app.tools.cost_analysis import IdentifyCostDriversInput, identify_cost_drivers
from app.tools.forecasting import ForecastUsageInput, forecast_usage
from app.tools.knowledge import SearchOptimizationKnowledgeInput, search_optimization_knowledge
from app.tools.optimization import (
    CheckConstraintsInput,
    CompareScenariosInput,
    GenerateScenariosInput,
    SimulateScenarioInput,
    check_constraints,
    compare_scenarios,
    generate_scenarios,
    simulate_scenario,
)
from app.tools.pricing import (
    CalculateCurrentCostInput,
    CalculateForecastedCostInput,
    GetPricingInput,
    calculate_current_cost,
    calculate_forecasted_cost,
    get_pricing,
)
from app.tools.usage import GetCurrentResourcesInput, GetUsageHistoryInput, get_current_resources, get_usage_history
from app.forecasting.enums import ForecastHorizon

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
    external_id = f"test-tools-compute-{uuid.uuid4().hex[:8]}"
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

    rng = np.random.default_rng(42)
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


def _events_for(db, session_id: str, tool_name: str) -> list[AgentEvent]:
    return (
        db.query(AgentEvent)
        .filter(AgentEvent.session_id == session_id, AgentEvent.tool_name == tool_name)
        .all()
    )


def test_get_usage_history_logs_success_event(db, session_id, compute_resource) -> None:
    output = get_usage_history(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=GetUsageHistoryInput(resource_id=compute_resource.external_id, usage_type="requests"),
    )

    assert len(output.points) > 0

    events = _events_for(db, session_id, "get_usage_history")
    assert len(events) == 1
    assert events[0].agent_name == AGENT_NAME
    assert events[0].output["status"] == "success"
    assert events[0].latency_ms >= 0
    assert events[0].input["resource_id"] == compute_resource.external_id


def test_get_usage_history_logs_error_event_for_unknown_resource(db, session_id) -> None:
    with pytest.raises(ToolError):
        get_usage_history(
            db, agent_name=AGENT_NAME, session_id=session_id,
            input=GetUsageHistoryInput(resource_id="does-not-exist", usage_type="requests"),
        )

    events = _events_for(db, session_id, "get_usage_history")
    assert len(events) == 1
    assert events[0].output["status"] == "error"
    assert "does-not-exist" in events[0].output["error"]


def test_get_current_resources(db, session_id, compute_resource) -> None:
    output = get_current_resources(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=GetCurrentResourcesInput(provider=PROVIDER, service="Compute"),
    )
    assert any(r.resource_id == compute_resource.external_id for r in output.resources)
    assert len(_events_for(db, session_id, "get_current_resources")) == 1


def test_forecast_usage_logs_and_returns_points(db, session_id, compute_resource) -> None:
    output = forecast_usage(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=ForecastUsageInput(resource_id=compute_resource.external_id, usage_type="requests", horizon=ForecastHorizon.WEEK),
    )
    assert len(output.points) == 7
    assert len(_events_for(db, session_id, "forecast_usage")) == 1


def test_get_pricing_returns_tiers(db, session_id) -> None:
    output = get_pricing(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=GetPricingInput(provider=PROVIDER, region="us-east-1", service=ServiceType.COMPUTE, sku="compute-instance-hour"),
    )
    assert len(output.tiers) == 1
    assert output.tiers[0].price_per_unit == pytest.approx(0.096)


def test_get_pricing_errors_for_unknown_sku(db, session_id) -> None:
    with pytest.raises(ToolError):
        get_pricing(
            db, agent_name=AGENT_NAME, session_id=session_id,
            input=GetPricingInput(provider=PROVIDER, region="us-east-1", service=ServiceType.COMPUTE, sku="does-not-exist"),
        )


def test_calculate_current_cost(db, session_id, compute_resource) -> None:
    output = calculate_current_cost(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=CalculateCurrentCostInput(provider=PROVIDER, resource_id=compute_resource.external_id),
    )
    assert len(output.line_items) > 0
    assert len(_events_for(db, session_id, "calculate_current_cost")) == 1


def test_calculate_forecasted_cost(db, session_id, compute_resource) -> None:
    output = calculate_forecasted_cost(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=CalculateForecastedCostInput(provider=PROVIDER, resource_id=compute_resource.external_id, horizon=ForecastHorizon.DAY),
    )
    assert output.total_cost > 0


def test_identify_cost_drivers(db, session_id, compute_resource) -> None:
    output = identify_cost_drivers(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=IdentifyCostDriversInput(provider=PROVIDER, resource_id=compute_resource.external_id, source="current", top_n=3),
    )
    assert output.total_cost > 0
    assert len(output.drivers) > 0
    assert sum(d.pct_of_total for d in output.drivers) <= 100.0 + 1e-6


def test_identify_cost_drivers_requires_horizon_for_forecasted() -> None:
    with pytest.raises(ValueError):
        IdentifyCostDriversInput(provider=PROVIDER, source="forecasted")


def test_optimization_tools_full_workflow(db, session_id, compute_resource) -> None:
    scenarios_out = generate_scenarios(
        db, agent_name=AGENT_NAME, session_id=session_id, input=GenerateScenariosInput()
    )
    assert len(scenarios_out.scenarios) == 6

    results = []
    checks_by_type = {}
    for spec in scenarios_out.scenarios:
        result = simulate_scenario(
            db, agent_name=AGENT_NAME, session_id=session_id,
            input=SimulateScenarioInput(
                provider=PROVIDER, resource_id=compute_resource.external_id, scenario_type=spec.scenario_type,
                horizon=ForecastHorizon.WEEK, max_latency_ms=100.0, min_availability=0.99, budget=100000.0,
            ),
        )
        results.append(result)

        checks_out = check_constraints(
            db, agent_name=AGENT_NAME, session_id=session_id,
            input=CheckConstraintsInput(scenario_result=result, max_latency_ms=100.0, min_availability=0.99, budget=100000.0),
        )
        checks_by_type[result.scenario_type] = checks_out.checks

    comparison = compare_scenarios(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=CompareScenariosInput(
            scenario_results=results, max_latency_ms=100.0, min_availability=0.99, budget=100000.0,
            checks_by_scenario_type=checks_by_type,
        ),
    )

    assert len(comparison.ranked) == 6
    assert comparison.fully_feasible is True

    assert len(_events_for(db, session_id, "generate_scenarios")) == 1
    assert len(_events_for(db, session_id, "simulate_scenario")) == 6
    assert len(_events_for(db, session_id, "check_constraints")) == 6
    assert len(_events_for(db, session_id, "compare_scenarios")) == 1


def test_search_optimization_knowledge_returns_real_results(db, session_id) -> None:
    output = search_optimization_knowledge(
        db, agent_name=AGENT_NAME, session_id=session_id,
        input=SearchOptimizationKnowledgeInput(query="how should I choose an instance size?", top_k=2),
    )
    assert output.stub is False
    assert len(output.results) == 2
    assert "Right-Sizing" in output.results[0].source
    assert all(r.content for r in output.results)
    assert all(0.0 <= r.score <= 1.0 + 1e-6 for r in output.results)
    assert len(_events_for(db, session_id, "search_optimization_knowledge")) == 1
    assert len(_events_for(db, session_id, "search_optimization_knowledge")) == 1
