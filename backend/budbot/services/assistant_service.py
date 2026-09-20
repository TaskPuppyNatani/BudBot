"""Tenant-scoped assistant configuration and inheritance."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.exceptions import ResourceNotFound
from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.assistant import AssistantConfiguration, LocationAssistantOverride
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.schemas.assistant import (
    AssistantUpdate,
    EffectiveAssistantConfiguration,
    LocationAssistantOverrideUpdate,
)


class AssistantService:
    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.session = session
        self.tenant = tenant
        self.assistants = TenantScopedRepository(
            session, AssistantConfiguration, tenant
        )
        self.locations = TenantScopedRepository(session, Location, tenant)
        self.overrides = TenantScopedRepository(
            session, LocationAssistantOverride, tenant
        )

    async def get(self, business_id: UUID) -> AssistantConfiguration:
        self.tenant.require_business(business_id)
        assistant = await self.session.scalar(self.assistants.select())
        if assistant is None:
            raise ResourceNotFound("assistant configuration")
        return assistant

    async def update(
        self,
        business_id: UUID,
        payload: AssistantUpdate,
    ) -> AssistantConfiguration:
        assistant = await self.get(business_id)
        values = payload.model_dump(exclude_unset=True, mode="python")
        for field, value in values.items():
            setattr(assistant, field, value)
        await self.session.flush()
        await self.session.refresh(assistant)
        return assistant

    async def update_override(
        self,
        location_id: UUID,
        payload: LocationAssistantOverrideUpdate,
    ) -> LocationAssistantOverride:
        await self.locations.get(
            location_id, resource_name="location", for_update=True
        )
        override = await self.session.scalar(
            self.overrides.select().where(
                LocationAssistantOverride.location_id == location_id
            )
        )
        if override is None:
            override = LocationAssistantOverride(
                business_id=self.tenant.business_id,
                location_id=location_id,
            )
            self.session.add(override)
        for field in payload.model_fields_set:
            setattr(override, field, getattr(payload, field))
        await self.session.flush()
        await self.session.refresh(override)
        return override

    async def resolve(
        self, business_id: UUID, location_id: UUID
    ) -> EffectiveAssistantConfiguration:
        self.tenant.require_business(business_id)
        await self.locations.get(location_id, resource_name="location")
        assistant = await self.get(business_id)
        override = await self.session.scalar(
            self.overrides.select().where(
                LocationAssistantOverride.location_id == location_id
            )
        )
        business = await self.session.get(Business, business_id)
        if business is None:
            raise ResourceNotFound("business")

        return EffectiveAssistantConfiguration(
            assistant_id=assistant.id,
            business_id=business_id,
            location_id=location_id,
            display_name=(
                override.display_name
                if override and override.display_name is not None
                else assistant.display_name
            ),
            greeting=(
                override.greeting
                if override and override.greeting is not None
                else assistant.greeting
            ),
            fallback_message=(
                override.fallback_message
                if override and override.fallback_message is not None
                else assistant.fallback_message
            ),
            avatar_reference=assistant.avatar_reference,
            primary_color=assistant.primary_color_override
            or business.primary_brand_color,
            enabled=(
                override.enabled
                if override and override.enabled is not None
                else assistant.enabled
            ),
        )
