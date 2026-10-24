"""Shared audited actions for dashboard routes and authenticated commands.

Callers authorize the action before entering here. Domain services retain their
tenant boundaries and validation; no command text or field values enter audit.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.tenancy import TenantContext
from budbot.schemas.assistant import AssistantUpdate, LocationAssistantOverrideUpdate
from budbot.schemas.knowledge import FAQCreate, FAQRead, FAQUpdate
from budbot.schemas.location import LocationUpdate
from budbot.schemas.provider import ProviderDiagnosticCode
from budbot.services.assistant_service import AssistantService
from budbot.services.audit_service import record_audit_event
from budbot.services.knowledge_service import KnowledgeService
from budbot.services.location_service import LocationService
from budbot.services.provider_service import ProviderService


class AdminActions:
    def __init__(self, session: AsyncSession, tenant: TenantContext, user_id: UUID):
        self.session, self.tenant, self.user_id = session, tenant, user_id

    async def _audit(self, event_type, resource_type, resource_id, details):
        await record_audit_event(
            self.session, event_type, actor_user_id=self.user_id,
            business_id=self.tenant.business_id, resource_type=resource_type,
            resource_id=resource_id, details=details,
        )

    async def update_assistant(self, payload: AssistantUpdate):
        assistant = await AssistantService(self.session, self.tenant).update(
            self.tenant.business_id, payload
        )
        await self._audit("admin.assistant.updated", "assistant", assistant.id,
            {"changed_fields": ",".join(sorted(payload.model_fields_set))})
        return assistant

    async def update_assistant_override(self, location_id: UUID, payload: LocationAssistantOverrideUpdate):
        override = await AssistantService(self.session, self.tenant).update_override(location_id, payload)
        await self._audit("admin.assistant.location_override.updated", "location_assistant_override", override.id,
            {"changed_fields": ",".join(sorted(payload.model_fields_set))})
        return override

    async def update_location(self, location_id: UUID, payload: LocationUpdate):
        location = await LocationService(self.session, self.tenant).update(location_id, payload)
        await self._audit("admin.location.updated", "location", location_id,
            {"changed_fields": ",".join(sorted(payload.model_fields_set))})
        return location

    async def _publish_faq(self, entry, event_type, fields):
        await self._audit(event_type, "faq", entry.id, {
            "location_id": str(entry.location_id) if entry.location_id else None,
            "enabled": entry.enabled, "is_public": entry.is_public,
            "changed_fields": ",".join(sorted(fields)),
        })
        result = FAQRead.model_validate(entry)
        await self.session.commit()
        return result

    async def create_faq(self, payload: FAQCreate):
        entry = await KnowledgeService(self.session, self.tenant).create_admin_faq(payload)
        return await self._publish_faq(entry, "admin.faq.created", payload.model_fields_set)

    async def update_faq(self, faq_id: UUID, payload: FAQUpdate):
        entry = await KnowledgeService(self.session, self.tenant).update_admin_faq(faq_id, payload)
        return await self._publish_faq(entry, "admin.faq.updated", payload.model_fields_set)

    async def test_provider(self, settings, providers, harnesses):
        result = await ProviderService(self.session, self.tenant, settings).test_connection(providers, harnesses)
        await self._audit("admin.provider.connection_tested", "provider", self.tenant.business_id, {
            "provider_action": "connection_tested", "provider": result.provider,
            "success": result.code == ProviderDiagnosticCode.OK, "diagnostic_code": result.code.value,
        })
        await self.session.commit()
        return result
