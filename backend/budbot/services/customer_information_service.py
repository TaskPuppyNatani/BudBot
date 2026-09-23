"""Effective public business/location information for customer commands."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.services.business_service import BusinessService


@dataclass(frozen=True, slots=True)
class PublicContact:
    address: str
    phone: str | None
    website: str | None


class CustomerInformationService:
    """Resolve configured customer-facing information without inference."""

    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.tenant = tenant
        self.businesses = BusinessService(session)

    async def get_business(self) -> Business:
        return await self.businesses.get(self.tenant, self.tenant.business_id)

    async def resolve_contact(self, location: Location) -> PublicContact:
        self.tenant.require_business(location.business_id)
        business = await self.get_business()
        region_postal = " ".join(
            part
            for part in (location.region.strip(), location.postal_code.strip())
            if part
        )
        address = ", ".join(
            part.strip()
            for part in (
                location.address_line_1,
                location.address_line_2,
                location.city,
                region_postal,
                location.country,
            )
            if part and part.strip()
        )
        return PublicContact(
            address=address,
            phone=location.phone or business.main_phone,
            website=str(business.website_url) if business.website_url else None,
        )
