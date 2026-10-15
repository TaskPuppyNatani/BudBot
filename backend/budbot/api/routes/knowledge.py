"""Authenticated FAQ management; public consumption stays in customer commands."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.models.knowledge import FAQEntry
from budbot.schemas.knowledge import FAQCreate, FAQRead, FAQUpdate
from budbot.services.audit_service import record_audit_event
from budbot.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/api/v1/businesses/{business_id}/faqs", tags=["knowledge"])
Session = Annotated[AsyncSession, Depends(get_session)]
ReadAccess = Annotated[AdminAccess, Depends(require_business_permission("faq.read"))]
WriteAccess = Annotated[AdminAccess, Depends(require_business_permission("faq.write", csrf=True))]


@router.get("", response_model=list[FAQRead])
async def list_faqs(business_id: UUID, session: Session, access: ReadAccess) -> object:
    return await KnowledgeService(session, access.tenant).list_admin_faqs()


async def _publish_faq(
    session: AsyncSession, access: AdminAccess, entry: FAQEntry,
    event_type: str, changed_fields: set[str],
) -> FAQRead:
    await record_audit_event(
        session, event_type, actor_user_id=access.user_id,
        business_id=access.business_id, resource_type="faq", resource_id=entry.id,
        details={
            "location_id": str(entry.location_id) if entry.location_id else None,
            "enabled": entry.enabled, "is_public": entry.is_public,
            "changed_fields": ",".join(sorted(changed_fields)),
        },
    )
    result = FAQRead.model_validate(entry)
    # Both FAQ state and its audit event must be visible to immediate dashboard
    # reload/customer requests; yield-dependency cleanup can follow delivery.
    await session.commit()
    return result


@router.post("", response_model=FAQRead, status_code=status.HTTP_201_CREATED)
async def create_faq(business_id: UUID, payload: FAQCreate, session: Session, access: WriteAccess) -> FAQRead:
    entry = await KnowledgeService(session, access.tenant).create_admin_faq(payload)
    return await _publish_faq(session, access, entry, "admin.faq.created", payload.model_fields_set)


@router.patch("/{faq_id}", response_model=FAQRead)
async def update_faq(business_id: UUID, faq_id: UUID, payload: FAQUpdate, session: Session, access: WriteAccess) -> FAQRead:
    entry = await KnowledgeService(session, access.tenant).update_admin_faq(faq_id, payload)
    return await _publish_faq(session, access, entry, "admin.faq.updated", payload.model_fields_set)
