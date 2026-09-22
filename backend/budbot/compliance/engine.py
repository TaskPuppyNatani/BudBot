"""Authoritative server-side capability authorization."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import get_session, get_tenant_context
from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.registry import (
    CapabilityPolicy,
    ComplianceCapability,
    ComplianceProfile,
    get_profile,
)
from budbot.core.exceptions import ComplianceError, ResourceNotFound
from budbot.core.time import ensure_utc, utc_now
from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.business import Business
from budbot.models.session import CustomerSession


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """A successful deterministic authorization result."""

    allowed: bool
    capability: ComplianceCapability
    profile_id: str
    profile_version: str
    reason_code: str


class ComplianceEngine:
    """The single policy gate for future routes, commands, and tools."""

    def __init__(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session = session
        self.tenant = tenant
        self.clock = clock
        self.sessions = TenantScopedRepository(session, CustomerSession, tenant)

    async def authorize(
        self,
        session_or_id: CustomerSession | UUID,
        capability: ComplianceCapability | str,
    ) -> AuthorizationDecision:
        """Authorize one capability or raise a normalized fail-closed error."""

        customer_session = await self._resolve_session(session_or_id)
        business = await self.session.scalar(
            select(Business).where(Business.id == self.tenant.business_id)
        )
        if business is None:
            raise ResourceNotFound("business")

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

        active_profile = self._profile(
            business.compliance_profile_id,
            business.compliance_profile_version,
        )
        stored_profile = self._profile(
            customer_session.compliance_profile_id,
            customer_session.compliance_profile_version,
        )
        if (
            active_profile.profile_id != stored_profile.profile_id
            or active_profile.version != stored_profile.version
        ):
            raise ComplianceError(
                "COMPLIANCE_PROFILE_MISMATCH",
                "the session uses a stale compliance profile; create a new session",
                status_code=409,
            )

        try:
            normalized_capability = ComplianceCapability(capability)
        except (TypeError, ValueError) as exc:
            raise ComplianceError(
                "UNKNOWN_CAPABILITY",
                "the requested capability is not recognized by the compliance registry",
            ) from exc
        try:
            status = AgeGateStatus(customer_session.age_gate_status)
        except (TypeError, ValueError) as exc:
            raise ComplianceError(
                "COMPLIANCE_STATE_INVALID",
                "the session has an invalid age-gate state",
            ) from exc

        rule = active_profile.rule_for(normalized_capability)
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
                raise ComplianceError(
                    "AGE_VERIFICATION_REQUIRED",
                    "a positive 21+ website/session attestation is required",
                )

        return AuthorizationDecision(
            allowed=True,
            capability=normalized_capability,
            profile_id=active_profile.profile_id,
            profile_version=active_profile.version,
            reason_code=rule.reason_code,
        )

    async def _resolve_session(
        self, session_or_id: CustomerSession | UUID
    ) -> CustomerSession:
        if isinstance(session_or_id, CustomerSession):
            self.tenant.require_business(session_or_id.business_id)
            return session_or_id
        return await self.sessions.get(session_or_id, resource_name="session")

    @staticmethod
    def _profile(profile_id: str, version: str) -> ComplianceProfile:
        return get_profile(profile_id, version)


def requires_capability(
    capability: ComplianceCapability | str,
) -> Callable[..., object]:
    """Create a reusable FastAPI dependency for a protected session route.

    A future route can declare ``Depends(requires_capability(Capability...))``
    while retaining the existing tenant header and session path parameter.
    """

    async def dependency(
        session_id: UUID,
        session: Annotated[AsyncSession, Depends(get_session)],
        tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    ) -> AuthorizationDecision:
        return await ComplianceEngine(session, tenant).authorize(
            session_id, capability
        )

    return dependency


require_capability = requires_capability
