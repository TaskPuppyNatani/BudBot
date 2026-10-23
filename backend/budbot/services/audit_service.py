"""Small append-only audit writer with a secret-redaction boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.auth import AuditEvent
from budbot.schemas.audit import AuditEventRead, AuditHistoryRead
from budbot.schemas.provider import ProviderDiagnosticCode

_REDACTED_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "credential",
    "cookie",
    "authorization",
    "request_body",
    "payload",
    "csrf",
)

# Only field names, never field values or free-form historical details. Older
# audit rows are re-projected at read time as an additional disclosure boundary.
_AUDIT_CHANGE_FIELDS = frozenset({
    "display_name", "legal_name", "industry", "website_url", "main_phone",
    "default_timezone", "payment_methods", "store_policies", "active",
    "directions_enabled", "faq_enabled", "payments_info_enabled", "policies_info_enabled",
    "products_enabled", "promotions_enabled", "address_line_1", "address_line_2",
    "city", "region", "region_code", "postal_code", "country", "phone", "timezone",
    "maps_place_id", "maps_destination", "hours", "greeting", "fallback_message",
    "avatar_reference", "primary_color_override", "enabled", "question", "answer",
    "location_id", "is_public", "primary_brand_color", "assistant_display_name",
    "business_logo", "assistant_avatar", "remove_business_logo", "remove_assistant_avatar",
})


def audit_details_for_read(details: Mapping[str, Any] | None) -> dict[str, object]:
    """Expose only typed, recognized metadata, even for legacy/malformed rows."""

    safe = _safe_details(details) if isinstance(details, Mapping) else {}
    result: dict[str, object] = {}
    for key in ("enabled", "is_public"):
        if type(safe.get(key)) is bool:
            result[key] = safe[key]
    if "location_id" in safe:
        try:
            result["location_id"] = str(UUID(safe["location_id"])) if safe["location_id"] is not None else None
        except (ValueError, TypeError, AttributeError):
            pass
    changed = safe.get("changed_fields")
    if isinstance(changed, str):
        result["changed_fields"] = ",".join(sorted(set(changed.split(",")) & _AUDIT_CHANGE_FIELDS))
    if safe.get("provider_action") in {"configuration_updated", "credential_set", "credential_replaced", "credential_removed", "connection_tested"}:
        result["provider_action"] = safe["provider_action"]
    if safe.get("provider_action") == "connection_tested":
        if safe.get("provider") in {"openrouter", "openai_compatible", "openai", "anthropic"}:
            result["provider"] = safe["provider"]
        if safe.get("diagnostic_code") in {code.value for code in ProviderDiagnosticCode}:
            result["diagnostic_code"] = safe["diagnostic_code"]
        if type(safe.get("success")) is bool:
            result["success"] = safe["success"]
    if safe.get("method") == "local_cli":
        result["method"] = "local_cli"
    return result


class AuditHistoryService:
    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.events = TenantScopedRepository(session, AuditEvent, tenant)

    async def list_events(self, *, limit: int, offset: int) -> AuditHistoryRead:
        statement = self.events.select().order_by(
            AuditEvent.created_at.desc(), AuditEvent.id.desc()
        ).offset(offset).limit(limit + 1)
        rows = list((await self.events.session.scalars(statement)).all())
        return AuditHistoryRead(
            items=[AuditEventRead(
                id=row.id, business_id=row.business_id, actor_user_id=row.actor_user_id,
                event_type=row.event_type, resource_type=row.resource_type,
                resource_id=row.resource_id, created_at=row.created_at,
                details=audit_details_for_read(row.details),
            ) for row in rows[:limit]],
            next_offset=offset + limit if len(rows) > limit and offset + limit <= 10000 else None,
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
