import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.forecasting.enums import ForecastHorizon
from app.models.base import SessionLocal
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.optimization.enums import ScenarioType
from app.optimization.scenarios import generate_scenarios
from app.optimization.simulator import ScenarioContext, simulate_scenario
from app.pricing.enums import ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.services.optimization_service import build_context

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


def _hourly_history(base: float, amp: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
    hour = timestamps.hour.to_numpy()
    day_of_week = timestamps.dayofweek.to_numpy()
    daily = 1.0 + 0.3 * np.sin(2 * np.pi * (hour - 9) / 24)
    weekly = np.where(day_of_week >= 5, 0.6, 1.0)
    noise = rng.normal(0, amp * 0.05, len(timestamps))
    values = np.clip(base * daily * weekly + noise, 0, None)
    return pd.Series(values, index=timestamps)


def _insert_history(db, resource: Resource, usage_type: str, series: pd.Series) -> None:
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
        for ts, v in series.items()
    )
    db.commit()


def _make_resource(db, service: ServiceType, prefix: str) -> Resource:
    external_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type=service.value,
        provider=PROVIDER,
        region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


def _cleanup(db, resource: Resource) -> None:
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


@pytest.fixture()
def compute_resource(db):
    resource = _make_resource(db, ServiceType.COMPUTE, "test-opt-compute")
    _insert_history(db, resource, "requests", _hourly_history(base=200.0, amp=100.0, seed=1))
    _insert_history(db, resource, "network_gb", _hourly_history(base=2.0, amp=1.0, seed=2))
    yield resource
    _cleanup(db, resource)


@pytest.fixture()
def database_resource(db):
    resource = _make_resource(db, ServiceType.DATABASE, "test-opt-database")
    _insert_history(db, resource, "requests", _hourly_history(base=5000.0, amp=2000.0, seed=3))
    _insert_history(db, resource, "network_gb", _hourly_history(base=3.0, amp=1.0, seed=4))
    _insert_history(db, resource, "storage_gb", _hourly_history(base=200.0, amp=5.0, seed=5))
    yield resource
    _cleanup(db, resource)


@pytest.fixture()
def object_storage_resource(db):
    resource = _make_resource(db, ServiceType.OBJECT_STORAGE, "test-opt-objstore")
    _insert_history(db, resource, "requests", _hourly_history(base=8000.0, amp=3000.0, seed=6))
    _insert_history(db, resource, "network_gb", _hourly_history(base=5.0, amp=2.0, seed=7))
    _insert_history(db, resource, "storage_gb", _hourly_history(base=1000.0, amp=10.0, seed=8))
    yield resource
    _cleanup(db, resource)


@pytest.fixture()
def serverless_resource(db):
    resource = _make_resource(db, ServiceType.SERVERLESS, "test-opt-serverless")
    _insert_history(db, resource, "requests", _hourly_history(base=2000.0, amp=1000.0, seed=9))
    _insert_history(db, resource, "network_gb", _hourly_history(base=0.8, amp=0.3, seed=10))
    yield resource
    _cleanup(db, resource)


def _build_ctx(db, resource, service, horizon=ForecastHorizon.WEEK, **overrides):
    kwargs = dict(
        max_latency_ms=100.0,
        min_availability=0.99,
        budget=100000.0,
    )
    kwargs.update(overrides)
    return build_context(db, PROVIDER, resource, service, horizon, kwargs["max_latency_ms"], kwargs["min_availability"], kwargs["budget"])


def test_compute_current_and_right_sizing_differ_or_match_honestly(db, compute_resource) -> None:
    ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE)
    specs = {s.scenario_type: s for s in generate_scenarios()}

    current = simulate_scenario(db, ctx, specs[ScenarioType.CURRENT])
    right_sized = simulate_scenario(db, ctx, specs[ScenarioType.RIGHT_SIZING])

    assert current.predicted_cost > 0
    assert right_sized.predicted_cost <= current.predicted_cost + 1e-6
    assert right_sized.capacity_provisioned >= right_sized.predicted_demand_peak
    assert current.configuration["tier"] == "medium"


def test_compute_autoscaling_never_costs_more_than_current(db, compute_resource) -> None:
    ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE)
    specs = {s.scenario_type: s for s in generate_scenarios()}

    current = simulate_scenario(db, ctx, specs[ScenarioType.CURRENT])
    autoscaling = simulate_scenario(db, ctx, specs[ScenarioType.AUTOSCALING])

    assert autoscaling.predicted_cost <= current.predicted_cost + 1e-6
    assert autoscaling.configuration["autoscaling"] is True


def test_compute_reserved_never_costs_more_than_current(db, compute_resource) -> None:
    ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE)
    specs = {s.scenario_type: s for s in generate_scenarios()}

    current = simulate_scenario(db, ctx, specs[ScenarioType.CURRENT])
    reserved = simulate_scenario(db, ctx, specs[ScenarioType.RESERVED])

    assert reserved.predicted_cost <= current.predicted_cost + 1e-6


def test_compute_combined_is_cheapest_or_equal_to_all_others(db, compute_resource) -> None:
    ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE)
    specs = generate_scenarios()
    results = {s.scenario_type: simulate_scenario(db, ctx, s) for s in specs}

    combined_cost = results[ScenarioType.COMBINED].predicted_cost
    for scenario_type, result in results.items():
        if scenario_type == ScenarioType.STORAGE_OPTIMIZATION:
            continue  # storage optimization is a no-op for Compute (no storage SKU)
        assert combined_cost <= result.predicted_cost + 1e-6, scenario_type


def test_compute_tight_latency_forces_more_capacity(db, compute_resource) -> None:
    loose_ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE, max_latency_ms=1000.0)
    tight_ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE, max_latency_ms=25.0)
    spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.CURRENT)

    loose_result = simulate_scenario(db, loose_ctx, spec)
    tight_result = simulate_scenario(db, tight_ctx, spec)

    assert tight_result.capacity_provisioned >= loose_result.capacity_provisioned
    assert tight_result.predicted_cost >= loose_result.predicted_cost - 1e-6


def test_compute_high_availability_target_forces_more_instances(db, compute_resource) -> None:
    low_avail_ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE, min_availability=0.5)
    high_avail_ctx = _build_ctx(db, compute_resource, ServiceType.COMPUTE, min_availability=0.999999)
    spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.CURRENT)

    low_result = simulate_scenario(db, low_avail_ctx, spec)
    high_result = simulate_scenario(db, high_avail_ctx, spec)

    assert high_result.availability >= low_result.availability
    assert high_result.predicted_cost >= low_result.predicted_cost - 1e-6


def test_database_scenarios_all_produce_positive_cost(db, database_resource) -> None:
    ctx = _build_ctx(db, database_resource, ServiceType.DATABASE)
    for spec in generate_scenarios():
        result = simulate_scenario(db, ctx, spec)
        assert result.predicted_cost > 0, spec.scenario_type


def test_object_storage_storage_optimization_saves_money(db, object_storage_resource) -> None:
    ctx = _build_ctx(db, object_storage_resource, ServiceType.OBJECT_STORAGE)
    specs = {s.scenario_type: s for s in generate_scenarios()}

    current = simulate_scenario(db, ctx, specs[ScenarioType.CURRENT])
    storage_opt = simulate_scenario(db, ctx, specs[ScenarioType.STORAGE_OPTIMIZATION])

    assert current.configuration["storage_tier"] == "standard"
    assert storage_opt.predicted_cost <= current.predicted_cost + 1e-6


def test_object_storage_capacity_trivially_satisfied(db, object_storage_resource) -> None:
    ctx = _build_ctx(db, object_storage_resource, ServiceType.OBJECT_STORAGE)
    spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.CURRENT)
    result = simulate_scenario(db, ctx, spec)

    assert result.capacity_provisioned >= result.predicted_demand_peak


def test_serverless_right_sizing_chooses_a_memory_tier(db, serverless_resource) -> None:
    # Loose enough that the baseline 512mb tier (200ms) already complies,
    # so right-sizing has no latency reason to move off the cost-minimal tier.
    ctx = _build_ctx(db, serverless_resource, ServiceType.SERVERLESS, max_latency_ms=250.0)
    specs = {s.scenario_type: s for s in generate_scenarios()}

    current = simulate_scenario(db, ctx, specs[ScenarioType.CURRENT])
    right_sized = simulate_scenario(db, ctx, specs[ScenarioType.RIGHT_SIZING])

    assert current.configuration["memory_tier"] == "512mb"
    assert right_sized.predicted_cost <= current.predicted_cost + 1e-6
    assert right_sized.availability == pytest.approx(current.availability)


def test_serverless_right_sizing_trades_cost_for_latency_compliance(db, serverless_resource) -> None:
    # 512mb (200ms) violates this tight target; right-sizing must move to a
    # faster (1024mb=110ms or 2048mb=64ms), pricier tier to comply, even
    # though 512mb is the raw cost-minimum among all tiers.
    ctx = _build_ctx(db, serverless_resource, ServiceType.SERVERLESS, max_latency_ms=120.0)
    spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.RIGHT_SIZING)

    result = simulate_scenario(db, ctx, spec)

    assert result.latency_ms <= 120.0
    assert result.configuration["memory_tier"] != "512mb"


def test_serverless_falls_back_to_cheapest_when_no_tier_can_comply(db, serverless_resource) -> None:
    # Even the fastest tier (2048mb=64ms) can't hit an impossibly tight target;
    # the simulator must still return a concrete (cost-minimal) answer rather
    # than raising, leaving the violation for check_constraints to flag.
    ctx = _build_ctx(db, serverless_resource, ServiceType.SERVERLESS, max_latency_ms=1.0)
    spec = next(s for s in generate_scenarios() if s.scenario_type == ScenarioType.RIGHT_SIZING)

    result = simulate_scenario(db, ctx, spec)

    assert result.latency_ms > 1.0
    assert result.configuration["memory_tier"] == "512mb"  # still the cheapest overall


def test_serverless_autoscaling_and_reserved_are_noops_matching_current(db, serverless_resource) -> None:
    ctx = _build_ctx(db, serverless_resource, ServiceType.SERVERLESS)
    specs = {s.scenario_type: s for s in generate_scenarios()}

    current = simulate_scenario(db, ctx, specs[ScenarioType.CURRENT])
    autoscaling = simulate_scenario(db, ctx, specs[ScenarioType.AUTOSCALING])
    reserved = simulate_scenario(db, ctx, specs[ScenarioType.RESERVED])

    assert autoscaling.predicted_cost == pytest.approx(current.predicted_cost)
    assert reserved.predicted_cost == pytest.approx(current.predicted_cost)
