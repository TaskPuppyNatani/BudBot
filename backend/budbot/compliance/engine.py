"""Authoritative server-side capability authorization."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.resolver import (
    ComplianceResolutionStatus,
    ComplianceResolver,
    EffectiveComplianceResolution,
)
from budbot.compliance.types import (
    SAFE_PUBLIC_CAPABILITIES,
    CapabilityPolicy,
    ComplianceCapability,
)
from budbot.core.exceptions import ComplianceError, ResourceNotFound
from budbot.core.time import ensure_utc, utc_now
from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.business import Business
from budbot.models.session import CustomerSession
from budbot.services.business_service import BusinessService


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """A successful deterministic authorization result."""

    allowed: bool
    capability: ComplianceCapability
    profile_id: str | None
    profile_version: str | None
    reason_code: str
    compliance_domain: str
    jurisdiction_code: str | None
    resolution_status: ComplianceResolutionStatus


class ComplianceEngine:
    """The single policy gate for future routes, commands, and tools."""

    def __init__(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        *,
        clock: Callable[[], datetime] = utc_now,
        resolver: ComplianceResolver | None = None,
    ) -> None:
        self.session = session
        self.tenant = tenant
        self.clock = clock
        self.resolver = resolver or ComplianceResolver()
        self.sessions = TenantScopedRepository(session, CustomerSession, tenant)

    async def authorize(
        self,
        session_or_id: CustomerSession | UUID,
        capability: ComplianceCapability | str,
    ) -> AuthorizationDecision:
        """Authorize one capability or raise a normalized fail-closed error."""

        try:
            normalized_capability = ComplianceCapability(capability)
        except (TypeError, ValueError) as exc:
            raise ComplianceError(
                "UNKNOWN_CAPABILITY",
                "the requested capability is not recognized by the compliance registry",
            ) from exc

        customer_session = await self._resolve_session(session_or_id)
        business = await BusinessService(self.session).get(
            self.tenant,
            self.tenant.business_id,
            for_update=True,
        )
        if customer_session.business_id != self.tenant.business_id:
            raise ResourceNotFound("session")
        if ensure_utc(customer_session.expires_at) <= ensure_utc(self.clock()):
            customer_session.age_gate_status = AgeGateStatus.EXPIRED
            await self.session.flush()
            raise ComplianceError(
                "SESSION_EXPIRED",
                "the customer session has expired; create a new session",
                status_code=410,
            )

        resolution = await self.resolver.resolve_session(
            self.session,
            business,
            customer_session,
            lock_location=True,
        )
        if (
            not resolution.matches_session(customer_session)
            and normalized_capability not in SAFE_PUBLIC_CAPABILITIES
        ):
            raise ComplianceError(
                "COMPLIANCE_PROFILE_MISMATCH",
                "the session uses a stale compliance binding; select a different active location or create a new session",
                status_code=409,
            )

        if resolution.profile is None:
            if normalized_capability is ComplianceCapability.MEDICAL_ADVICE:
                raise ComplianceError(
                    "CAPABILITY_PROHIBITED",
                    "medical advice is prohibited by BudBot policy",
                )
            if normalized_capability in SAFE_PUBLIC_CAPABILITIES:
                return AuthorizationDecision(
                    allowed=True,
                    capability=normalized_capability,
                    profile_id=None,
                    profile_version=None,
                    reason_code="PUBLIC_CAPABILITY",
                    compliance_domain=resolution.compliance_domain,
                    jurisdiction_code=resolution.jurisdiction_code,
                    resolution_status=resolution.status,
                )
            self._raise_resolution_error(resolution)

        try:
            status = AgeGateStatus(customer_session.age_gate_status)
        except (TypeError, ValueError) as exc:
            raise ComplianceError(
                "COMPLIANCE_STATE_INVALID",
                "the session has an invalid age-gate state",
            ) from exc

        rule = resolution.profile.rule_for(normalized_capability)
        if rule.policy is CapabilityPolicy.PROHIBITED:
            raise ComplianceError(
                "CAPABILITY_PROHIBITED",
                "the requested capability is prohibited by the active compliance profile",
            )
        if rule.policy is CapabilityPolicy.AGE_GATED:
            if status is AgeGateStatus.DENIED:
                raise ComplianceError(
                    "AGE_VERIFICATION_DENIED",
                    "the session was denied by the age attestation",
                )
            if status is not AgeGateStatus.VERIFIED:
                minimum_age = resolution.profile.minimum_age or 21
                raise ComplianceError(
                    "AGE_VERIFICATION_REQUIRED",
                    f"a positive {minimum_age}+ website/session attestation is required",
                )

        return AuthorizationDecision(
            allowed=True,
            capability=normalized_capability,
            profile_id=resolution.profile.profile_id,
            profile_version=resolution.profile.version,
            reason_code=rule.reason_code,
            compliance_domain=resolution.compliance_domain,
            jurisdiction_code=resolution.jurisdiction_code,
            resolution_status=resolution.status,
        )

    async def _resolve_session(
        self, session_or_id: CustomerSession | UUID
    ) -> CustomerSession:
        if isinstance(session_or_id, CustomerSession):
            self.tenant.require_business(session_or_id.business_id)
            return await self.sessions.get(
                session_or_id.id,
                resource_name="session",
                for_update=True,
            )
        return await self.sessions.get(
            session_or_id,
            resource_name="session",
            for_update=True,
        )

    @staticmethod
    def _raise_resolution_error(
        resolution: EffectiveComplianceResolution,
    ) -> NoReturn:
        if resolution.status is ComplianceResolutionStatus.LOCATION_REQUIRED:
            raise ComplianceError(
                "COMPLIANCE_LOCATION_REQUIRED",
                "select an active location before using regulated cannabis capabilities",
                status_code=409,
            )
        raise ComplianceError(
            "COMPLIANCE_PROFILE_UNAVAILABLE",
            "compliance support is unavailable for the selected jurisdiction",
            status_code=403,
        )


def requires_capability(
    capability: ComplianceCapability | str,
) -> Callable[..., object]:
    """Create a reusable FastAPI dependency for a protected session route."""

    async def dependency(
        session_id: UUID,
        session: Annotated[AsyncSession, Depends(get_session)],
        tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    ) -> AuthorizationDecision:
        return await ComplianceEngine(session, tenant).authorize(
            session_id, capability
        )

    return dependency
