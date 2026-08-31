from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.services.data_ingestion import (
    IngestSummary,
    UnsupportedFileFormatError,
    parse_upload,
    persist_rows,
    validate_rows,
)

router = APIRouter()


@router.post("/upload", response_model=IngestSummary)
async def upload_usage_data(
    file: UploadFile, db: Session = Depends(get_db)
) -> IngestSummary:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        raw_rows = parse_upload(content, file.filename or "")
    except UnsupportedFileFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not parse file: {exc}"
        ) from exc

    if not raw_rows:
        raise HTTPException(status_code=400, detail="File contained no rows")

    valid_rows, errors = validate_rows(raw_rows)

    if not valid_rows:
        return IngestSummary(
            rows_received=len(raw_rows),
            rows_valid=0,
            rows_failed=len(errors),
            usage_records_inserted=0,
            resources_created=0,
            resources_updated=0,
            errors=errors[:50],
        )

    result = persist_rows(db, valid_rows)

    return IngestSummary(
        rows_received=len(raw_rows),
        rows_valid=len(valid_rows),
        rows_failed=len(errors),
        usage_records_inserted=result.usage_records_inserted,
        resources_created=result.resources_created,
        resources_updated=result.resources_updated,
        errors=errors[:50],
    )
