from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.base import get_db
from app.models.resource import Resource

router = APIRouter()


class ResourceOut(BaseModel):
    resource_id: str
    service: str
    provider: str
    region: str


class ResourceListResponse(BaseModel):
    resources: list[ResourceOut]


@router.get("", response_model=ResourceListResponse)
def list_resources(
    provider: str | None = None,
    service: str | None = None,
    db: Session = Depends(get_db),
) -> ResourceListResponse:
    query = db.query(Resource)
    if provider:
        query = query.filter(Resource.provider == provider)
    if service:
        query = query.filter(Resource.resource_type == service)

    rows = query.order_by(Resource.resource_type, Resource.external_id).all()
    return ResourceListResponse(
        resources=[
            ResourceOut(resource_id=r.external_id, service=r.resource_type, provider=r.provider, region=r.region)
            for r in rows
        ]
    )
