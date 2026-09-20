"""M2 assistant identity, override, and effective-configuration API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.core.tenancy import TenantContext
from budbot.schemas.assistant import (
    AssistantRead,
    AssistantUpdate,
    EffectiveAssistantConfiguration,
    LocationAssistantOverrideRead,
    LocationAssistantOverrideUpdate,
)
from budbot.services.assistant_service import AssistantService

router = APIRouter(prefix="/api/v1/businesses/{business_id}", tags=["assistant"])
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


@router.get("/assistant", response_model=AssistantRead)
async def get_assistant(
    business_id: UUID, session: Session, tenant: Tenant
) -> object:
    return await AssistantService(session, tenant).get(business_id)


@router.patch("/assistant", response_model=AssistantRead)
async def update_assistant(
    business_id: UUID,
    payload: AssistantUpdate,
    session: Session,
    tenant: Tenant,
) -> object:
    return await AssistantService(session, tenant).update(business_id, payload)


@router.patch(
    "/locations/{location_id}/assistant-override",
    response_model=LocationAssistantOverrideRead,
)
async def update_location_assistant_override(
    business_id: UUID,
    location_id: UUID,
    payload: LocationAssistantOverrideUpdate,
    session: Session,
    tenant: Tenant,
) -> object:
    tenant.require_business(business_id)
    return await AssistantService(session, tenant).update_override(
        location_id, payload
    )


@router.get(
    "/locations/{location_id}/effective-assistant",
    response_model=EffectiveAssistantConfiguration,
)
async def resolve_effective_assistant(
    business_id: UUID,
    location_id: UUID,
    session: Session,
    tenant: Tenant,
) -> EffectiveAssistantConfiguration:
    return await AssistantService(session, tenant).resolve(
        business_id, location_id
    )
