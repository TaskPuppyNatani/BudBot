"""Safe tenant audit-history projection; never serialize ORM details directly."""

from datetime import datetime
from uuid import UUID

from budbot.schemas.common import DomainSchema


class AuditEventRead(DomainSchema):
    id: UUID
    business_id: UUID
    actor_user_id: UUID | None
    event_type: str
    resource_type: str | None
    resource_id: str | None
    created_at: datetime
    details: dict[str, str | bool | int | None]


class AuditHistoryRead(DomainSchema):
    items: list[AuditEventRead]
    next_offset: int | None
