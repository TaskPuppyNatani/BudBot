"""M3 business compliance-profile configuration API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.compliance.registry import ComplianceProfile
from budbot.core.tenancy import TenantContext
from budbot.schemas.compliance import (
    ComplianceProfileRead,
    ComplianceProfileUpdate,
)
from budbot.services.compliance_service import ComplianceService

router = APIRouter(
    prefix="/api/v1/businesses/{business_id}/compliance-profile",
    tags=["compliance"],
)
Session = Annotated[AsyncSession, Depends(get_session)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]


def _read(profile: ComplianceProfile) -> ComplianceProfileRead:
    # The registry object is immutable and internal; this explicit projection
    # keeps future policy implementation details out of the public API.
    return ComplianceProfileRead(
        profile_id=profile.profile_id,
        version=profile.version,
        jurisdiction=profile.jurisdiction,
        compliance_domain=str(profile.compliance_domain),
        jurisdiction_code=profile.jurisdiction_code,
        format_version=profile.format_version,
        effective_from=profile.effective_from,
        reviewed_at=profile.reviewed_at,
        source_references=list(profile.source_references),
        requires_age_gate=profile.requires_age_gate,
        minimum_age=profile.minimum_age,
        website_attestation_notice=profile.website_attestation_notice,
        medical_eligibility_notice=profile.medical_eligibility_notice,
    )


@router.get("", response_model=ComplianceProfileRead)
async def get_compliance_profile(
    business_id: UUID, session: Session, tenant: Tenant
) -> ComplianceProfileRead:
    profile = await ComplianceService(session, tenant).get_active_profile(business_id)
    return _read(profile)


@router.patch("", response_model=ComplianceProfileRead)
async def configure_compliance_profile(
    business_id: UUID,
    payload: ComplianceProfileUpdate,
    session: Session,
    tenant: Tenant,
) -> ComplianceProfileRead:
    profile = await ComplianceService(session, tenant).configure(business_id, payload)
    return _read(profile)
