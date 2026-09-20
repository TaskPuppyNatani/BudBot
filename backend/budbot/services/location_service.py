"""Tenant-scoped multi-location management."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.location import Location, LocationHours
from budbot.schemas.location import LocationCreate, LocationHoursInput, LocationUpdate
from budbot.services.business_service import BusinessService


class LocationService:
    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.session = session
        self.tenant = tenant
        self.locations = TenantScopedRepository(session, Location, tenant)

    async def create(self, business_id: UUID, payload: LocationCreate) -> Location:
        self.tenant.require_business(business_id)
        await BusinessService(self.session).get(self.tenant, business_id)
        values = payload.model_dump(exclude={"hours"}, mode="python")
        location = Location(business_id=self.tenant.business_id, **values)
        location.hours = self._hours(payload.hours)
        self.session.add(location)
        await self.session.flush()
        return location

    async def list_locations(
        self, *, include_inactive: bool = False
    ) -> list[Location]:
        statement = self.locations.select().options(selectinload(Location.hours))
        if not include_inactive:
            statement = statement.where(Location.active.is_(True))
        statement = statement.order_by(Location.display_name, Location.id)
        return list((await self.session.scalars(statement)).all())

    async def get(self, location_id: UUID) -> Location:
        return await self.locations.get(
            location_id,
            options=(selectinload(Location.hours),),
            resource_name="location",
        )

    async def update(
        self, location_id: UUID, payload: LocationUpdate
    ) -> Location:
        location = await self.get(location_id)
        values = payload.model_dump(exclude_unset=True, exclude={"hours"}, mode="python")
        for field, value in values.items():
            setattr(location, field, value)
        if "hours" in payload.model_fields_set:
            location.hours = []
            await self.session.flush()
            location.hours = self._hours(payload.hours or [])
        await self.session.flush()
        await self.session.refresh(location, attribute_names=["updated_at"])
        return location

    async def deactivate(self, location_id: UUID) -> Location:
        location = await self.get(location_id)
        location.active = False
        await self.session.flush()
        await self.session.refresh(location, attribute_names=["updated_at"])
        return location

    def _hours(self, values: list[LocationHoursInput]) -> list[LocationHours]:
        return [
            LocationHours(
                business_id=self.tenant.business_id,
                **hours.model_dump(mode="python"),
            )
            for hours in values
        ]
