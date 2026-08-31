import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.agents.cost_analysis_agent import run_cost_analysis_agent
from app.agents.forecast_agent import run_forecast_agent
from app.agents.optimization_agent import (
    build_optimization_narrative,
    pick_next_candidate,
    run_optimization_scenarios,
)
from app.agents.planner import DEFAULT_PLAN, Plan, plan_request
from app.optimization.enums import ScenarioType
from app.agents.report import run_report_agent
from app.forecasting.enums import ForecastHorizon
from app.models.agent_event import AgentEvent
from app.models.base import SessionLocal
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.pricing.enums import ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing

HISTORY_DAYS = 60


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
def compute_resource(db):
    external_id = f"test-agents-compute-{uuid.uuid4().hex[:8]}"
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

    rng = np.random.default_rng(5)
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


# ---- Planner ----


def test_plan_request_falls_back_to_default_without_api_key() -> None:
    plan = plan_request("What will my compute costs look like next month?")
    assert plan == DEFAULT_PLAN


def test_plan_request_uses_llm_when_available() -> None:
    fake_plan = Plan(run_forecast=True, run_cost_analysis=False, run_optimization=False, reasoning="only forecast requested")
    with patch("app.agents.planner.generate_structured", return_value=fake_plan):
        plan = plan_request("just tell me the forecast")
    assert plan.run_cost_analysis is False
    assert plan.reasoning == "only forecast requested"


# ---- Forecast agent ----


def test_forecast_agent_fallback_narrative_without_api_key(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    result = run_forecast_agent(
        db, session_id=session_id, resource_id=compute_resource.external_id,
        usage_type="requests", horizon=ForecastHorizon.WEEK,
    )
    assert "forecast" in result
    assert "[template fallback" in result["narrative"]


def test_forecast_agent_uses_llm_narrative_when_available(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    with patch("app.agents.forecast_agent.generate_text", return_value="The trend is stable."):
        result = run_forecast_agent(
            db, session_id=session_id, resource_id=compute_resource.external_id,
            usage_type="requests", horizon=ForecastHorizon.WEEK,
        )
    assert result["narrative"] == "The trend is stable."


def test_forecast_agent_handles_unknown_resource(db) -> None:
    session_id = f"test-{uuid.uuid4()}"
    result = run_forecast_agent(
        db, session_id=session_id, resource_id="does-not-exist", usage_type="requests", horizon=ForecastHorizon.DAY
    )
    assert "error" in result


# ---- Cost analysis agent ----


def test_cost_analysis_agent_fallback_narrative(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    result = run_cost_analysis_agent(
        db, session_id=session_id, provider=PROVIDER, resource_id=compute_resource.external_id,
        horizon=ForecastHorizon.WEEK,
    )
    assert result["current_cost"] is not None
    assert result["forecasted_cost"] is not None
    assert "[template fallback" in result["narrative"]


def test_cost_analysis_agent_uses_llm_narrative_when_available(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    with patch("app.agents.cost_analysis_agent.generate_text", return_value="Costs are dominated by compute hours."):
        result = run_cost_analysis_agent(
            db, session_id=session_id, provider=PROVIDER, resource_id=compute_resource.external_id,
            horizon=ForecastHorizon.WEEK,
        )
    assert result["narrative"] == "Costs are dominated by compute hours."


# ---- Optimization agent ----


def test_run_optimization_scenarios_produces_full_bundle(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    bundle = run_optimization_scenarios(
        db, session_id=session_id, provider=PROVIDER, resource_id=compute_resource.external_id,
        horizon=ForecastHorizon.WEEK, max_latency_ms=100.0, min_availability=0.99, budget=100000.0,
    )
    assert len(bundle.ranked_types) == 6
    assert set(bundle.results_by_type.keys()) == set(ScenarioType)
    assert bundle.current_cost is not None
    assert bundle.forecast_uncertainty_ratio is not None


def test_pick_next_candidate_skips_rejected() -> None:
    ranked = [ScenarioType.COMBINED, ScenarioType.RESERVED, ScenarioType.CURRENT]
    assert pick_next_candidate(ranked, []) == ScenarioType.COMBINED
    assert pick_next_candidate(ranked, [ScenarioType.COMBINED.value]) == ScenarioType.RESERVED
    assert pick_next_candidate(ranked, [ScenarioType.COMBINED.value, ScenarioType.RESERVED.value, ScenarioType.CURRENT.value]) is None


def test_build_optimization_narrative_cites_knowledge_source_in_fallback(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    bundle = run_optimization_scenarios(
        db, session_id=session_id, provider=PROVIDER, resource_id=compute_resource.external_id,
        horizon=ForecastHorizon.WEEK, max_latency_ms=100.0, min_availability=0.99, budget=100000.0,
    )
    candidate = bundle.results_by_type[ScenarioType.RIGHT_SIZING]

    data, narrative = build_optimization_narrative(
        db, session_id=session_id, candidate=candidate, approved=True, rejection_history=[], exhausted=False,
    )
    assert data["knowledge_sources"]
    assert "Sources:" in narrative
    assert any(k["source"] in narrative for k in data["knowledge_sources"])


def test_build_optimization_narrative_uses_llm_when_available(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    bundle = run_optimization_scenarios(
        db, session_id=session_id, provider=PROVIDER, resource_id=compute_resource.external_id,
        horizon=ForecastHorizon.WEEK, max_latency_ms=100.0, min_availability=0.99, budget=100000.0,
    )
    candidate = bundle.results_by_type[ScenarioType.RIGHT_SIZING]

    with patch("app.agents.optimization_agent.generate_text", return_value="Switch to a smaller instance to save money."):
        _, narrative = build_optimization_narrative(
            db, session_id=session_id, candidate=candidate, approved=True, rejection_history=[], exhausted=False,
        )
    assert narrative == "Switch to a smaller instance to save money."


def test_build_optimization_narrative_honest_when_none_approved(db, compute_resource) -> None:
    session_id = f"test-{uuid.uuid4()}"
    bundle = run_optimization_scenarios(
        db, session_id=session_id, provider=PROVIDER, resource_id=compute_resource.external_id,
        horizon=ForecastHorizon.WEEK, max_latency_ms=100.0, min_availability=0.99, budget=100000.0,
    )
    candidate = bundle.results_by_type[ScenarioType.CURRENT]
    rejection_history = [
        {"scenario_type": "current", "verdict": {"approved": False, "rejection_reason": "forecast_uncertainty: too uncertain"}}
    ]

    _, narrative = build_optimization_narrative(
        db, session_id=session_id, candidate=candidate, approved=False,
        rejection_history=rejection_history, exhausted=True,
    )
    assert "No scenario passed validation" in narrative
    assert "forecast_uncertainty" in narrative


# ---- Report agent ----


def test_report_agent_fallback_template() -> None:
    report = run_report_agent(
        forecast_narrative="F", cost_narrative="C", optimization_narrative="O", critic_notes="R"
    )
    assert "template fallback" in report
    assert "F" in report and "C" in report and "O" in report and "R" in report


def test_report_agent_uses_llm_when_available() -> None:
    with patch("app.agents.report.generate_text", return_value="Final combined report."):
        report = run_report_agent(
            forecast_narrative="F", cost_narrative="C", optimization_narrative="O", critic_notes="R"
        )
    assert report == "Final combined report."
