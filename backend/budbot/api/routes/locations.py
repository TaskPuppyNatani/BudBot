"""M2 tenant-scoped location API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.core.tenancy import TenantContext
from budbot.schemas.location import LocationCreate, LocationRead, LocationUpdate
from budbot.services.location_service import LocationService

router = APIRouter(
    prefix="/api/v1/businesses/{business_id}/locations", tags=["locations"]
)
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
async def create_location(
    business_id: UUID,
    payload: LocationCreate,
    session: Session,
    tenant: Tenant,
) -> object:
    return await LocationService(session, tenant).create(business_id, payload)


@router.get("", response_model=list[LocationRead])
async def list_locations(
    business_id: UUID,
    session: Session,
    tenant: Tenant,
    include_inactive: Annotated[bool, Query()] = False,
) -> object:
    tenant.require_business(business_id)
    return await LocationService(session, tenant).list_locations(
        include_inactive=include_inactive
    )


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(
    business_id: UUID,
    location_id: UUID,
    session: Session,
    tenant: Tenant,
) -> object:
    tenant.require_business(business_id)
    return await LocationService(session, tenant).get(location_id)


@router.patch("/{location_id}", response_model=LocationRead)
async def update_location(
    business_id: UUID,
    location_id: UUID,
    payload: LocationUpdate,
    session: Session,
    tenant: Tenant,
) -> object:
    tenant.require_business(business_id)
    return await LocationService(session, tenant).update(location_id, payload)


@router.post("/{location_id}/deactivate", response_model=LocationRead)
async def deactivate_location(
    business_id: UUID,
    location_id: UUID,
    session: Session,
    tenant: Tenant,
) -> object:
    tenant.require_business(business_id)
    return await LocationService(session, tenant).deactivate(location_id)
