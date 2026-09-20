"""M2 business tenant API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.core.tenancy import TenantContext
from budbot.schemas.business import BusinessCreate, BusinessRead, BusinessUpdate
from budbot.services.business_service import BusinessService

router = APIRouter(prefix="/api/v1/businesses", tags=["businesses"])
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


@router.post("", response_model=BusinessRead, status_code=status.HTTP_201_CREATED)
async def create_business(payload: BusinessCreate, session: Session) -> object:
    """Development bootstrap route; intentionally has no pretend authentication."""

    return await BusinessService(session).create(payload)


@router.get("/{business_id}", response_model=BusinessRead)
async def get_business(
    business_id: UUID, session: Session, tenant: Tenant
) -> object:
    return await BusinessService(session).get(tenant, business_id)


@router.patch("/{business_id}", response_model=BusinessRead)
async def update_business(
    business_id: UUID,
    payload: BusinessUpdate,
    session: Session,
    tenant: Tenant,
) -> object:
    return await BusinessService(session).update(tenant, business_id, payload)
