"""Business tenant management behavior."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.exceptions import ResourceNotFound
from budbot.core.tenancy import TenantContext
from budbot.models.assistant import AssistantConfiguration
from budbot.models.business import Business
from budbot.schemas.business import BusinessCreate, BusinessUpdate


class BusinessService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: BusinessCreate) -> Business:
        values = payload.model_dump(exclude={"assistant"}, mode="json")
        business = Business(**values)
        assistant = AssistantConfiguration(
            **payload.assistant.model_dump(mode="json"), business=business
        )
        self.session.add_all([business, assistant])
        await self.session.flush()
        await self.session.refresh(business)
        return business

    async def get(self, tenant: TenantContext, business_id: UUID) -> Business:
        tenant.require_business(business_id)
        business = await self.session.scalar(
            select(Business).where(Business.id == tenant.business_id)
        )
        if business is None:
            raise ResourceNotFound("business")
        return business

    async def update(
        self,
        tenant: TenantContext,
        business_id: UUID,
        payload: BusinessUpdate,
    ) -> Business:
        business = await self.get(tenant, business_id)
        values = payload.model_dump(exclude_unset=True, mode="json")
        for field, value in values.items():
            setattr(business, field, value)
        await self.session.flush()
        await self.session.refresh(business)
        return business
