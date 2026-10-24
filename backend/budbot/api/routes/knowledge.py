"""Authenticated FAQ management; public consumption stays in customer commands."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.schemas.knowledge import FAQCreate, FAQRead, FAQUpdate
from budbot.services.admin_actions import AdminActions
from budbot.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/api/v1/businesses/{business_id}/faqs", tags=["knowledge"])
Session = Annotated[AsyncSession, Depends(get_session)]
ReadAccess = Annotated[AdminAccess, Depends(require_business_permission("faq.read"))]
WriteAccess = Annotated[AdminAccess, Depends(require_business_permission("faq.write", csrf=True))]


@router.get("", response_model=list[FAQRead])
async def list_faqs(business_id: UUID, session: Session, access: ReadAccess) -> object:
    return await KnowledgeService(session, access.tenant).list_admin_faqs()


@router.post("", response_model=FAQRead, status_code=status.HTTP_201_CREATED)
async def create_faq(business_id: UUID, payload: FAQCreate, session: Session, access: WriteAccess) -> FAQRead:
    return await AdminActions(session, access.tenant, access.user_id).create_faq(payload)


@router.patch("/{faq_id}", response_model=FAQRead)
async def update_faq(business_id: UUID, faq_id: UUID, payload: FAQUpdate, session: Session, access: WriteAccess) -> FAQRead:
    return await AdminActions(session, access.tenant, access.user_id).update_faq(faq_id, payload)
