import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.agents.critic import CriticVerdict
from app.agents.graph import run_agent_session
from app.agents.optimization_agent import MAX_CRITIC_ATTEMPTS
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
    external_id = f"test-graph-compute-{uuid.uuid4().hex[:8]}"
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

    rng = np.random.default_rng(9)
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
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_full_agent_session_runs_all_nodes_and_logs_tool_calls(db, compute_resource) -> None:
    final_state = run_agent_session(
        db,
        user_query="How much will this Compute resource cost next week, and how can I save money?",
        provider=PROVIDER,
        resource_id=compute_resource.external_id,
        usage_type="requests",
        horizon=ForecastHorizon.WEEK,
        max_latency_ms=100.0,
        min_availability=0.99,
        budget=100000.0,
    )

    assert final_state["plan"]["run_forecast"] is True
    assert final_state["forecast_narrative"]
    assert final_state["cost_narrative"]
    assert final_state["optimization_narrative"]
    assert final_state["critic_notes"]
    assert final_state["final_report"]

    session_id = final_state["session_id"]
    events = db.query(AgentEvent).filter(AgentEvent.session_id == session_id).all()

    tool_names = {e.tool_name for e in events}
    assert "forecast_usage" in tool_names
    assert "calculate_current_cost" in tool_names
    assert "calculate_forecasted_cost" in tool_names
    assert "identify_cost_drivers" in tool_names
    assert "generate_scenarios" in tool_names
    assert "simulate_scenario" in tool_names
    assert "check_constraints" in tool_names
    assert "compare_scenarios" in tool_names

    agent_names = {e.agent_name for e in events}
    assert "forecast_agent" in agent_names
    assert "cost_analysis_agent" in agent_names
    assert "optimization_agent" in agent_names

    for e in events:
        assert e.latency_ms is not None and e.latency_ms >= 0
        assert e.output["status"] in ("success", "error")

    db.execute(delete(AgentEvent).where(AgentEvent.session_id == session_id))
    db.commit()


def test_agent_session_handles_unknown_resource_gracefully(db) -> None:
    final_state = run_agent_session(
        db,
        user_query="What's the forecast for this resource?",
        provider=PROVIDER,
        resource_id="does-not-exist",
        usage_type="requests",
        horizon=ForecastHorizon.DAY,
        max_latency_ms=100.0,
        min_availability=0.99,
        budget=1000.0,
    )

    assert final_state["forecast_data"].get("error")
    assert final_state["final_report"]  # still produces a report, not a crash

    session_id = final_state["session_id"]
    db.execute(delete(AgentEvent).where(AgentEvent.session_id == session_id))
    db.commit()


def _make_verdict(approved: bool, reason: str = "forced for test") -> CriticVerdict:
    from app.agents.critic import CriticFinding

    return CriticVerdict(
        approved=approved,
        findings=[CriticFinding(check="forced", passed=approved, detail=reason)],
        rejection_reason=None if approved else reason,
    )


def test_optimization_retries_after_rejection_then_approves(db, compute_resource) -> None:
    """Critic rejects the first two candidates and approves the third —
    verifies the agent actually walks the ranked list rather than giving
    up or looping forever, and never re-runs the solver to do it."""
    verdicts = [_make_verdict(False, "rejected attempt 1"), _make_verdict(False, "rejected attempt 2"), _make_verdict(True)]

    with patch("app.agents.graph.evaluate_scenario", side_effect=verdicts):
        final_state = run_agent_session(
            db,
            user_query="Optimize this resource",
            provider=PROVIDER,
            resource_id=compute_resource.external_id,
            usage_type="requests",
            horizon=ForecastHorizon.WEEK,
            max_latency_ms=100.0,
            min_availability=0.99,
            budget=100000.0,
        )

    assert final_state["optimization_attempt"] == 3
    assert len(final_state["rejected_scenario_types"]) == 2
    assert final_state["critic_verdict"]["approved"] is True
    assert len(final_state["critic_history"]) == 3
    # the solver ran exactly once (6 simulate_scenario calls), not once per attempt
    session_id = final_state["session_id"]
    simulate_calls = (
        db.query(AgentEvent)
        .filter(AgentEvent.session_id == session_id, AgentEvent.tool_name == "simulate_scenario")
        .count()
    )
    assert simulate_calls == 6

    db.execute(delete(AgentEvent).where(AgentEvent.session_id == session_id))
    db.commit()


def test_optimization_reports_honestly_when_every_candidate_is_rejected(db, compute_resource) -> None:
    """If the critic rejects every candidate within the retry budget, the
    final report must say so plainly rather than presenting a rejected
    scenario as an approved recommendation."""
    with patch("app.agents.graph.evaluate_scenario", return_value=_make_verdict(False, "always rejected for test")):
        final_state = run_agent_session(
            db,
            user_query="Optimize this resource",
            provider=PROVIDER,
            resource_id=compute_resource.external_id,
            usage_type="requests",
            horizon=ForecastHorizon.WEEK,
            max_latency_ms=100.0,
            min_availability=0.99,
            budget=100000.0,
        )

    assert final_state["optimization_attempt"] == MAX_CRITIC_ATTEMPTS
    assert len(final_state["rejected_scenario_types"]) == MAX_CRITIC_ATTEMPTS
    assert final_state["critic_verdict"]["approved"] is False
    assert final_state["optimization_data"]["approved"] is False
    assert final_state["optimization_data"]["exhausted_without_approval"] is True
    assert "No scenario passed validation" in final_state["optimization_narrative"]
    assert "always rejected for test" in final_state["optimization_narrative"]
    # honesty must survive into the final synthesized report too
    assert "template fallback" in final_state["final_report"] or "No scenario passed validation" in final_state["final_report"]

    session_id = final_state["session_id"]
    db.execute(delete(AgentEvent).where(AgentEvent.session_id == session_id))
    db.commit()
