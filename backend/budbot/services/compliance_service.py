"""Tenant-scoped business compliance-profile configuration."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.compliance.registry import ComplianceProfile, get_profile
from budbot.core.tenancy import TenantContext
from budbot.schemas.compliance import ComplianceProfileUpdate
from budbot.services.business_service import BusinessService


class ComplianceService:
    """Read and change the explicit active profile for one business."""

    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.session = session
        self.tenant = tenant

    async def get_active_profile(self, business_id: UUID) -> ComplianceProfile:
        business = await BusinessService(self.session).get(self.tenant, business_id)
        return get_profile(
            business.compliance_profile_id,
            business.compliance_profile_version,
        )

    async def configure(
        self, business_id: UUID, payload: ComplianceProfileUpdate
    ) -> ComplianceProfile:
        business = await BusinessService(self.session).get(
            self.tenant, business_id, for_update=True
        )
        profile = get_profile(payload.profile_id)
        business.compliance_profile_id = profile.profile_id
        business.compliance_profile_version = profile.version
        business.compliance_domain = str(profile.compliance_domain)
        await self.session.flush()
        await self.session.refresh(business)
        return profile
