"""M2 tenant-scoped location API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.schemas.location import LocationCreate, LocationRead, LocationUpdate
from budbot.services.audit_service import record_audit_event
from budbot.services.location_service import LocationService

router = APIRouter(
    prefix="/api/v1/businesses/{business_id}/locations", tags=["locations"]
)
Session = Annotated[AsyncSession, Depends(get_session)]
ReadAccess = Annotated[
    AdminAccess, Depends(require_business_permission("location.read"))
]
WriteAccess = Annotated[
    AdminAccess,
    Depends(require_business_permission("location.write", csrf=True)),
]


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
async def create_location(
    business_id: UUID,
    payload: LocationCreate,
    session: Session,
    access: WriteAccess,
) -> object:
    location = await LocationService(session, access.tenant).create(
        business_id, payload
    )
    await record_audit_event(
        session,
        "admin.location.created",
        actor_user_id=access.user_id,
        business_id=business_id,
        resource_type="location",
        resource_id=location.id,
    )
    return location


@router.get("", response_model=list[LocationRead])
async def list_locations(
    business_id: UUID,
    session: Session,
    access: ReadAccess,
    include_inactive: Annotated[bool, Query()] = False,
) -> object:
    access.tenant.require_business(business_id)
    return await LocationService(session, access.tenant).list_locations(
        include_inactive=include_inactive
    )


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(
    business_id: UUID,
    location_id: UUID,
    session: Session,
    access: ReadAccess,
) -> object:
    access.tenant.require_business(business_id)
    return await LocationService(session, access.tenant).get(location_id)


@router.patch("/{location_id}", response_model=LocationRead)
async def update_location(
    business_id: UUID,
    location_id: UUID,
    payload: LocationUpdate,
    session: Session,
    access: WriteAccess,
) -> object:
    access.tenant.require_business(business_id)
    location = await LocationService(session, access.tenant).update(
        location_id, payload
    )
    await record_audit_event(
        session,
        "admin.location.updated",
        actor_user_id=access.user_id,
        business_id=business_id,
        resource_type="location",
        resource_id=location_id,
        details={"changed_fields": ",".join(sorted(payload.model_fields_set))},
    )
    return location


@router.post("/{location_id}/deactivate", response_model=LocationRead)
async def deactivate_location(
    business_id: UUID,
    location_id: UUID,
    session: Session,
    access: WriteAccess,
) -> object:
    access.tenant.require_business(business_id)
    location = await LocationService(session, access.tenant).deactivate(location_id)
    await record_audit_event(
        session,
        "admin.location.deactivated",
        actor_user_id=access.user_id,
        business_id=business_id,
        resource_type="location",
        resource_id=location_id,
    )
    return location
