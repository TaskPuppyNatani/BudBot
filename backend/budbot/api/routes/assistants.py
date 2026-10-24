"""M2 assistant identity, override, and effective-configuration API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.schemas.assistant import (
    AssistantRead,
    AssistantUpdate,
    EffectiveAssistantConfiguration,
    LocationAssistantOverrideRead,
    LocationAssistantOverrideUpdate,
)
from budbot.services.admin_actions import AdminActions
from budbot.services.assistant_service import AssistantService

router = APIRouter(prefix="/api/v1/businesses/{business_id}", tags=["assistant"])
Session = Annotated[AsyncSession, Depends(get_session)]
ReadAccess = Annotated[
    AdminAccess, Depends(require_business_permission("assistant.read"))
]
WriteAccess = Annotated[
    AdminAccess,
    Depends(require_business_permission("assistant.write", csrf=True)),
]


@router.get("/assistant", response_model=AssistantRead)
async def get_assistant(
    business_id: UUID, session: Session, access: ReadAccess
) -> object:
    return await AssistantService(session, access.tenant).get(business_id)


@router.patch("/assistant", response_model=AssistantRead)
async def update_assistant(
    business_id: UUID,
    payload: AssistantUpdate,
    session: Session,
    access: WriteAccess,
) -> object:
    return await AdminActions(session, access.tenant, access.user_id).update_assistant(payload)


@router.get(
    "/locations/{location_id}/assistant-override",
    response_model=LocationAssistantOverrideRead | None,
)
async def get_location_assistant_override(
    business_id: UUID, location_id: UUID, session: Session, access: ReadAccess
) -> object:
    access.tenant.require_business(business_id)
    return await AssistantService(session, access.tenant).get_override(location_id)


@router.patch(
    "/locations/{location_id}/assistant-override",
    response_model=LocationAssistantOverrideRead,
)
async def update_location_assistant_override(
    business_id: UUID,
    location_id: UUID,
    payload: LocationAssistantOverrideUpdate,
    session: Session,
    access: WriteAccess,
) -> object:
    access.tenant.require_business(business_id)
    return await AdminActions(session, access.tenant, access.user_id).update_assistant_override(location_id, payload)


@router.get(
    "/locations/{location_id}/effective-assistant",
    response_model=EffectiveAssistantConfiguration,
)
async def resolve_effective_assistant(
    business_id: UUID,
    location_id: UUID,
    session: Session,
    access: ReadAccess,
) -> EffectiveAssistantConfiguration:
    return await AssistantService(session, access.tenant).resolve(
        business_id, location_id
    )
