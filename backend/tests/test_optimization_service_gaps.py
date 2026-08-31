import uuid

import pytest
from sqlalchemy import delete

from app.forecasting.enums import ForecastHorizon
from app.models.base import SessionLocal
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.pricing.enums import ServiceType
from app.pricing.seed_data import PROVIDER, seed_pricing
from app.services.optimization_service import (
    InsufficientDemandDataError,
    OptimizationRunNotFoundError,
    UnsupportedServiceError,
    build_context,
    get_latest_optimization_run,
    run_optimization,
)


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


def _make_resource(db, resource_type: str, prefix: str) -> Resource:
    external_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
    resource = Resource(
        external_id=external_id,
        name=external_id,
        resource_type=resource_type,
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


def test_run_optimization_rejects_unsupported_resource_type(db) -> None:
    resource = _make_resource(db, "Networking", "test-opt-unsupported")
    try:
        with pytest.raises(UnsupportedServiceError):
            run_optimization(
                db,
                provider=PROVIDER,
                resource_external_id=resource.external_id,
                horizon=ForecastHorizon.WEEK,
                max_latency_ms=100.0,
                min_availability=0.99,
                budget=100000.0,
            )
    finally:
        _cleanup(db, resource)


def test_build_context_raises_when_no_requests_history_for_compute(db) -> None:
    # No usage_records inserted at all -> demand forecast for "requests" is
    # impossible, and the optimizer must refuse rather than silently
    # optimizing against a phantom baseline.
    resource = _make_resource(db, ServiceType.COMPUTE.value, "test-opt-nohist-compute")
    try:
        with pytest.raises(InsufficientDemandDataError, match="requests"):
            build_context(
                db, PROVIDER, resource, ServiceType.COMPUTE, ForecastHorizon.WEEK, 100.0, 0.99, 100000.0
            )
    finally:
        _cleanup(db, resource)


def test_build_context_raises_when_no_storage_history_for_object_storage(db) -> None:
    resource = _make_resource(db, ServiceType.OBJECT_STORAGE.value, "test-opt-nohist-objstore")
    try:
        with pytest.raises(InsufficientDemandDataError, match="storage_gb"):
            build_context(
                db, PROVIDER, resource, ServiceType.OBJECT_STORAGE, ForecastHorizon.WEEK, 100.0, 0.99, 100000.0
            )
    finally:
        _cleanup(db, resource)


def test_get_latest_optimization_run_raises_when_none_exist(db) -> None:
    resource_id = f"test-opt-no-runs-{uuid.uuid4().hex[:8]}"
    with pytest.raises(OptimizationRunNotFoundError):
        get_latest_optimization_run(db, resource_external_id=resource_id)
