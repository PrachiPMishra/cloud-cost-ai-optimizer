import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.models.base import SessionLocal
from app.models.resource import Resource
from app.models.usage_record import UsageRecord


@pytest.fixture()
def cleanup_resources():
    created_external_ids: list[str] = []
    yield created_external_ids

    db = SessionLocal()
    try:
        resources = (
            db.query(Resource)
            .filter(Resource.external_id.in_(created_external_ids))
            .all()
        )
        resource_ids = [r.id for r in resources]
        if resource_ids:
            db.execute(
                delete(UsageRecord).where(UsageRecord.resource_id.in_(resource_ids))
            )
            db.execute(delete(Resource).where(Resource.id.in_(resource_ids)))
            db.commit()
    finally:
        db.close()


def test_upload_csv_creates_usage_records(
    client: TestClient, cleanup_resources: list[str]
) -> None:
    resource_id = f"test-compute-{uuid.uuid4().hex[:8]}"
    cleanup_resources.append(resource_id)

    csv_content = (
        "timestamp,service,resource,region,cpu_utilization,memory_utilization,"
        "requests,storage_gb,network_gb,hours_used,current_cost\n"
        f"2026-01-01T00:00:00,Compute,{resource_id},us-east-1,45.2,60.1,120,80.5,1.2,1.0,0.15\n"
        f"2026-01-01T01:00:00,Compute,{resource_id},us-east-1,50.0,62.0,130,80.6,1.3,1.0,0.16\n"
    )

    response = client.post(
        "/api/data/upload",
        files={"file": ("usage.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rows_received"] == 2
    assert body["rows_valid"] == 2
    assert body["rows_failed"] == 0
    assert body["resources_created"] == 1
    # 6 metric fields + cost, per row = 7 usage_records per row
    assert body["usage_records_inserted"] == 14

    db = SessionLocal()
    try:
        resource = (
            db.query(Resource).filter(Resource.external_id == resource_id).first()
        )
        assert resource is not None
        assert resource.resource_type == "Compute"
        assert resource.region == "us-east-1"

        records = (
            db.query(UsageRecord).filter(UsageRecord.resource_id == resource.id).all()
        )
        assert len(records) == 14
        cost_records = [r for r in records if r.usage_type == "cost"]
        assert len(cost_records) == 2
        assert float(cost_records[0].cost) == pytest.approx(0.15)
    finally:
        db.close()


def test_upload_json_creates_usage_records(
    client: TestClient, cleanup_resources: list[str]
) -> None:
    resource_id = f"test-db-{uuid.uuid4().hex[:8]}"
    cleanup_resources.append(resource_id)

    payload = [
        {
            "timestamp": "2026-01-01T00:00:00",
            "service": "Database",
            "resource": resource_id,
            "region": "eu-west-1",
            "cpu_utilization": 55.0,
            "memory_utilization": 70.0,
            "requests": 4000,
            "storage_gb": 200.0,
            "network_gb": 3.0,
            "hours_used": 1.0,
            "current_cost": 0.2,
        }
    ]

    response = client.post(
        "/api/data/upload",
        files={
            "file": (
                "usage.json",
                io.BytesIO(json.dumps(payload).encode()),
                "application/json",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rows_valid"] == 1
    assert body["resources_created"] == 1
    assert body["usage_records_inserted"] == 7


def test_upload_rejects_invalid_service(
    client: TestClient, cleanup_resources: list[str]
) -> None:
    resource_id = f"test-bad-{uuid.uuid4().hex[:8]}"

    csv_content = (
        "timestamp,service,resource,region,cpu_utilization,memory_utilization,"
        "requests,storage_gb,network_gb,hours_used,current_cost\n"
        f"2026-01-01T00:00:00,NotAService,{resource_id},us-east-1,45.2,60.1,120,80.5,1.2,1.0,0.15\n"
    )

    response = client.post(
        "/api/data/upload",
        files={"file": ("usage.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rows_valid"] == 0
    assert body["rows_failed"] == 1
    assert body["usage_records_inserted"] == 0
    assert len(body["errors"]) == 1


def test_upload_rejects_unsupported_extension(client: TestClient) -> None:
    response = client.post(
        "/api/data/upload",
        files={"file": ("usage.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 400


def test_upload_rejects_empty_file(client: TestClient) -> None:
    response = client.post(
        "/api/data/upload",
        files={"file": ("usage.csv", io.BytesIO(b""), "text/csv")},
    )

    assert response.status_code == 400
