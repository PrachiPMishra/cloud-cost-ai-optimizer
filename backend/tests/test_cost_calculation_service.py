import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.models.base import SessionLocal
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.pricing.enums import PricingModel, ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.services.cost_calculation import price_usage_records


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
    external_id = f"test-price-compute-{uuid.uuid4().hex[:8]}"
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

    rows = [
        UsageRecord(
            resource_id=resource.id,
            timestamp=datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
            usage_type="hours_used",
            quantity=1.0,
            unit="hours",
            provider=PROVIDER,
            region="us-east-1",
        )
        for hour in range(5)
    ] + [
        UsageRecord(
            resource_id=resource.id,
            timestamp=datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
            usage_type="network_gb",
            quantity=2.0,
            unit="gb",
            provider=PROVIDER,
            region="us-east-1",
        )
        for hour in range(5)
    ] + [
        UsageRecord(
            resource_id=resource.id,
            timestamp=datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
            usage_type="cpu_utilization",
            quantity=40.0,
            unit="percent",
            provider=PROVIDER,
            region="us-east-1",
        )
        for hour in range(5)
    ]
    db.add_all(rows)
    db.commit()

    yield resource

    db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
    db.execute(delete(Resource).where(Resource.id == resource.id))
    db.commit()


def test_price_usage_records_prices_hours_and_network_not_cpu(db, compute_resource) -> None:
    result = price_usage_records(
        db,
        provider=PROVIDER,
        pricing_model=PricingModel.ON_DEMAND,
        resource_external_id=compute_resource.external_id,
    )

    assert result.skipped == []
    skus_priced = {item.sku for item in result.line_items}
    assert skus_priced == {"compute-instance-hour", "compute-network-egress"}

    hours_item = next(i for i in result.line_items if i.sku == "compute-instance-hour")
    assert hours_item.resolved_quantity == pytest.approx(5.0)
    assert hours_item.cost == pytest.approx(5.0 * 0.096, rel=1e-6)

    network_item = next(i for i in result.line_items if i.sku == "compute-network-egress")
    assert network_item.resolved_quantity == pytest.approx(10.0)


def test_price_usage_records_storage_gauge_is_time_weighted(db) -> None:
    external_id = f"test-price-db-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type=ServiceType.DATABASE.value,
        provider=PROVIDER,
        region="us-east-1",
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    rows = [
        UsageRecord(
            resource_id=resource.id,
            timestamp=datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
            usage_type="storage_gb",
            quantity=50.0,
            unit="gb",
            provider=PROVIDER,
            region="us-east-1",
        )
        for hour in range(10)
    ]
    db.add_all(rows)
    db.commit()

    try:
        result = price_usage_records(
            db, provider=PROVIDER, resource_external_id=external_id
        )
        storage_item = next(i for i in result.line_items if i.sku == "database-storage")
        # 10 hourly samples at 50 GB each -> 500 GB-hours
        assert storage_item.resolved_quantity == pytest.approx(500.0)
    finally:
        db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
        db.execute(delete(Resource).where(Resource.id == resource.id))
        db.commit()
