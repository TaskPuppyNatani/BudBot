"""Read-only, bounded administrative history for an authorized business."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.schemas.audit import AuditHistoryRead
from budbot.services.audit_service import AuditHistoryService

router = APIRouter(prefix="/api/v1/businesses/{business_id}/audit", tags=["audit"])
Session = Annotated[AsyncSession, Depends(get_session)]
ReadAccess = Annotated[AdminAccess, Depends(require_business_permission("audit.read"))]


@router.get("", response_model=AuditHistoryRead)
async def get_audit_history(
    business_id: UUID, session: Session, access: ReadAccess,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> AuditHistoryRead:
    return await AuditHistoryService(session, access.tenant).list_events(limit=limit, offset=offset)
