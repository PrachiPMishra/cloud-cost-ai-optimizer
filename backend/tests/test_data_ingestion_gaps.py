import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.models.base import SessionLocal
from app.models.resource import Resource
from app.models.usage_record import UsageRecord
from app.services.data_ingestion import (
    UnsupportedFileFormatError,
    UsageRowIngest,
    parse_upload,
    persist_rows,
    validate_rows,
)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_parse_upload_json_wrapped_in_records_key() -> None:
    payload = {"records": [{"a": 1}, {"a": 2}]}
    rows = parse_upload(json.dumps(payload).encode(), "usage.json")
    assert rows == [{"a": 1}, {"a": 2}]


def test_parse_upload_json_wrapped_in_data_key() -> None:
    payload = {"data": [{"a": 1}]}
    rows = parse_upload(json.dumps(payload).encode(), "usage.json")
    assert rows == [{"a": 1}]


def test_parse_upload_json_single_object_is_wrapped_in_a_list() -> None:
    payload = {"a": 1, "b": 2}
    rows = parse_upload(json.dumps(payload).encode(), "usage.json")
    assert rows == [{"a": 1, "b": 2}]


def test_parse_upload_json_non_list_non_dict_raises() -> None:
    with pytest.raises(UnsupportedFileFormatError, match="must be a list of records"):
        parse_upload(json.dumps(42).encode(), "usage.json")


def test_validate_rows_preserves_timezone_aware_timestamp() -> None:
    raw = [
        {
            "timestamp": "2026-01-01T00:00:00+05:00",
            "service": "Compute",
            "resource": "r1",
            "region": "us-east-1",
        }
    ]
    valid, errors = validate_rows(raw)
    assert errors == []
    assert valid[0].timestamp.utcoffset().total_seconds() == 5 * 3600


def test_get_or_create_resource_updates_region_and_type_on_conflict(db) -> None:
    external_id = f"test-ingest-conflict-{uuid.uuid4().hex[:8]}"
    try:
        first_row = UsageRowIngest(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            service="Compute",
            resource=external_id,
            region="us-east-1",
            hours_used=1.0,
        )
        result_1 = persist_rows(db, [first_row])
        assert result_1.resources_created == 1
        assert result_1.resources_updated == 0

        second_row = UsageRowIngest(
            timestamp=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            service="Database",
            resource=external_id,
            region="eu-west-1",
            hours_used=1.0,
        )
        result_2 = persist_rows(db, [second_row])
        assert result_2.resources_created == 0
        assert result_2.resources_updated == 1

        resource = db.query(Resource).filter(Resource.external_id == external_id).first()
        assert resource.region == "eu-west-1"
        assert resource.resource_type == "Database"
    finally:
        resource = db.query(Resource).filter(Resource.external_id == external_id).first()
        if resource is not None:
            db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
            db.execute(delete(Resource).where(Resource.id == resource.id))
            db.commit()


def test_persist_rows_skips_absent_metric_fields(db) -> None:
    external_id = f"test-ingest-partial-{uuid.uuid4().hex[:8]}"
    try:
        row = UsageRowIngest(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            service="Compute",
            resource=external_id,
            region="us-east-1",
            requests=100.0,
            # every other metric field left as None
        )
        result = persist_rows(db, [row])
        # only "requests" is set -> exactly one usage_records row, no "cost" row
        assert result.usage_records_inserted == 1

        resource = db.query(Resource).filter(Resource.external_id == external_id).first()
        records = db.query(UsageRecord).filter(UsageRecord.resource_id == resource.id).all()
        assert len(records) == 1
        assert records[0].usage_type == "requests"
    finally:
        resource = db.query(Resource).filter(Resource.external_id == external_id).first()
        if resource is not None:
            db.execute(delete(UsageRecord).where(UsageRecord.resource_id == resource.id))
            db.execute(delete(Resource).where(Resource.id == resource.id))
            db.commit()
