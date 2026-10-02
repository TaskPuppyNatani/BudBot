"""Small append-only audit writer with a secret-redaction boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.models.auth import AuditEvent

_REDACTED_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "credential",
    "cookie",
    "authorization",
    "request_body",
    "payload",
)


def _safe_details(value: Mapping[str, Any] | None) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, item in (value or {}).items():
        normalized_key = str(key).casefold()
        if any(fragment in normalized_key for fragment in _REDACTED_KEY_FRAGMENTS):
            continue
        if item is None or isinstance(item, (bool, int)):
            safe[str(key)[:80]] = item
        elif isinstance(item, str):
            safe[str(key)[:80]] = item[:200]
    return safe


async def record_audit_event(
    session: AsyncSession,
    event_type: str,
    *,
    actor_user_id: UUID | None = None,
    business_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: UUID | str | None = None,
    details: Mapping[str, Any] | None = None,
) -> AuditEvent:
    """Add one sanitized event to the caller's transaction."""

    event = AuditEvent(
        actor_user_id=actor_user_id,
        business_id=business_id,
        event_type=event_type[:120],
        resource_type=resource_type[:80] if resource_type else None,
        resource_id=str(resource_id)[:80] if resource_id is not None else None,
        details=_safe_details(details),
    )
    session.add(event)
    await session.flush()
    return event
