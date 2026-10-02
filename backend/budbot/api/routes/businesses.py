"""M2 business tenant API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import (
    AdminAccess,
    AdminPrincipal,
    get_session,
    require_business_creator,
    require_business_permission,
)
from budbot.models.user import BusinessMembership
from budbot.schemas.business import BusinessCreate, BusinessRead, BusinessUpdate
from budbot.services.audit_service import record_audit_event
from budbot.services.business_service import BusinessService

router = APIRouter(prefix="/api/v1/businesses", tags=["businesses"])
Session = Annotated[AsyncSession, Depends(get_session)]
Creator = Annotated[AdminPrincipal, Depends(require_business_creator)]


@router.post("", response_model=BusinessRead, status_code=status.HTTP_201_CREATED)
async def create_business(
    payload: BusinessCreate, session: Session, principal: Creator
) -> object:
    """Create a tenant for an authenticated owner and grant only that tenant."""

    business = await BusinessService(session).create(payload)
    session.add(
        BusinessMembership(
            user_id=principal.user_id,
            business_id=business.id,
            role="owner",
        )
    )
    await record_audit_event(
        session,
        "admin.business.created",
        actor_user_id=principal.user_id,
        business_id=business.id,
        resource_type="business",
        resource_id=business.id,
    )
    return business


@router.get("/{business_id}", response_model=BusinessRead)
async def get_business(
    business_id: UUID,
    session: Session,
    access: Annotated[
        AdminAccess, Depends(require_business_permission("business.read"))
    ],
) -> object:
    return await BusinessService(session).get(access.tenant, business_id)


@router.patch("/{business_id}", response_model=BusinessRead)
async def update_business(
    business_id: UUID,
    payload: BusinessUpdate,
    session: Session,
    access: Annotated[
        AdminAccess,
        Depends(require_business_permission("business.write", csrf=True)),
    ],
) -> object:
    business = await BusinessService(session).update(
        access.tenant, business_id, payload
    )
    await record_audit_event(
        session,
        "admin.business.updated",
        actor_user_id=access.user_id,
        business_id=business_id,
        resource_type="business",
        resource_id=business_id,
        details={"changed_fields": ",".join(sorted(payload.model_fields_set))},
    )
    return business
