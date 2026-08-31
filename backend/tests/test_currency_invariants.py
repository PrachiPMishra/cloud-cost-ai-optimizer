"""Value-level currency invariants, complementing the import-level check in
test_currency_boundary.py: persisted pricing rows are tagged USD, and
changing the display-only USD->INR rate to an absurd value must not move a
single computed cost figure — pricing, cost prediction, and optimization
must all be provably rate-independent, not just "currency.py isn't
imported" (which wouldn't catch a careless inline `* rate` mistake).
"""

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.config import get_settings
from app.forecasting.enums import ForecastHorizon
from app.models.base import SessionLocal
from app.models.pricing import Pricing
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.pricing.enums import PricingModel, ServiceType, UsageMode
from app.pricing.calculator import calculate_cost
from app.pricing.schemas import CostCalculationRequest
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.services.cost_prediction import predict_bill
from app.services.optimization_service import run_optimization

WILD_RATE = 999_999.0
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
def wild_inr_rate():
    """Temporarily set the display-only rate to an absurd value. Any
    computation that leaked this into a cost figure would be immediately,
    obviously wrong (~6 orders of magnitude off) rather than subtly wrong."""
    settings = get_settings()
    original = settings.usd_to_inr_rate
    settings.usd_to_inr_rate = WILD_RATE
    yield
    settings.usd_to_inr_rate = original


def test_all_seeded_pricing_rows_are_usd(db) -> None:
    currencies = {c for (c,) in db.query(Pricing.currency).distinct()}
    assert currencies == {"USD"}


def test_calculate_cost_is_independent_of_display_rate(db, wild_inr_rate) -> None:
    request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-instance-hour",
        unit="hour",
        pricing_model=PricingModel.ON_DEMAND,
        usage_mode=UsageMode.FLAT,
        quantity=100.0,
        resource_id="test-currency-calc",
    )
    with_wild_rate = calculate_cost(request, db).cost

    get_settings().usd_to_inr_rate = 1.0
    with_normal_rate = calculate_cost(request, db).cost

    assert with_wild_rate == with_normal_rate
    assert with_wild_rate > 0


def _insert_hourly_history(db, resource: Resource, usage_type: str, base: float, seed: int) -> None:
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=1),
        periods=HISTORY_DAYS * 24,
        freq="h",
    )
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


@pytest.fixture()
def compute_resource(db):
    external_id = f"test-currency-compute-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id, name=external_id, resource_type=ServiceType.COMPUTE.value,
        provider=PROVIDER, region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    _insert_hourly_history(db, resource, "requests", 200.0, seed=1)
    _insert_hourly_history(db, resource, "hours_used", 1.0, seed=2)
    _insert_hourly_history(db, resource, "network_gb", 2.0, seed=3)
    yield resource
    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_predict_bill_is_independent_of_display_rate(db, compute_resource, wild_inr_rate) -> None:
    summary = predict_bill(
        db, provider=PROVIDER, horizon=ForecastHorizon.WEEK, resource_external_id=compute_resource.external_id
    )
    total_with_wild_rate = summary.total_cost

    get_settings().usd_to_inr_rate = 1.0
    summary_normal = predict_bill(
        db, provider=PROVIDER, horizon=ForecastHorizon.WEEK, resource_external_id=compute_resource.external_id
    )

    assert total_with_wild_rate == pytest.approx(summary_normal.total_cost)
    assert total_with_wild_rate > 0


def test_run_optimization_is_independent_of_display_rate(db, compute_resource, wild_inr_rate) -> None:
    from app.models.constraint import Constraint
    from app.models.optimization_run import OptimizationRun
    from app.models.scenario import Scenario

    def _run():
        return run_optimization(
            db, provider=PROVIDER, resource_external_id=compute_resource.external_id,
            horizon=ForecastHorizon.WEEK, max_latency_ms=100.0, min_availability=0.99, budget=100000.0,
        )

    summary_wild = _run()

    get_settings().usd_to_inr_rate = 1.0
    summary_normal = _run()

    costs_wild = sorted(s.predicted_cost for s in summary_wild.scenarios)
    costs_normal = sorted(s.predicted_cost for s in summary_normal.scenarios)
    assert costs_wild == pytest.approx(costs_normal)
    assert all(c > 0 for c in costs_wild)

    for summary in (summary_wild, summary_normal):
        run = db.get(OptimizationRun, summary.optimization_run_id)
        db.delete(run)
    db.commit()
    db.execute(
        delete(Constraint).where(
            Constraint.scenario_id.in_(
                [s.scenario_id for summary in (summary_wild, summary_normal) for s in summary.scenarios]
            )
        )
    )
    db.execute(
        delete(Scenario).where(
            Scenario.id.in_(
                [s.scenario_id for summary in (summary_wild, summary_normal) for s in summary.scenarios]
            )
        )
    )
    db.commit()
