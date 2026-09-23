"""Tenant-scoped customer-session lifecycle and compliance binding behavior."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NoReturn
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.compliance.age_gate import (
    AgeGateStatus,
    initial_age_gate_status,
    transition_age_gate,
)
from budbot.compliance.resolver import (
    ComplianceResolutionStatus,
    ComplianceResolver,
    EffectiveComplianceResolution,
)
from budbot.core.exceptions import ComplianceError, ResourceNotFound
from budbot.core.time import ensure_utc, utc_now
from budbot.core.tenancy import TenantContext
from budbot.database.tenant import TenantScopedRepository
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.models.session import CustomerSession
from budbot.schemas.session import (
    AgeAttestationRequest,
    CustomerSessionCreate,
    SessionLocationUpdate,
)
from budbot.services.business_service import BusinessService


class SessionService:
    """Create, rebind, and mutate customer sessions without leaving tenant scope."""

    def __init__(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        *,
        ttl_seconds: int = 86_400,
        clock: Callable[[], datetime] = utc_now,
        resolver: ComplianceResolver | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("session TTL must be positive")
        self.session = session
        self.tenant = tenant
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.resolver = resolver or ComplianceResolver()
        self.sessions = TenantScopedRepository(session, CustomerSession, tenant)
        self.locations = TenantScopedRepository(session, Location, tenant)

    async def create(self, payload: CustomerSessionCreate) -> CustomerSession:
        business = await BusinessService(self.session).get(
            self.tenant, self.tenant.business_id, for_update=True
        )
        location = await self._validate_location(payload.selected_location_id)
        resolution = self.resolver.resolve(business.compliance_domain, location)
        now = self.clock()
        customer_session = CustomerSession(
            business_id=self.tenant.business_id,
            selected_location_id=location.id if location else None,
            age_gate_status=self._initial_age_state(resolution),
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        resolution.bind_session(customer_session)
        self.session.add(customer_session)
        await self.session.flush()
        await self.session.refresh(customer_session)
        return customer_session

    async def get(
        self, session_id: UUID, *, validate_binding: bool = True
    ) -> CustomerSession:
        customer_session = await self._get(session_id)
        await self._expire_if_needed(customer_session)
        if (
            validate_binding
            and customer_session.age_gate_status != AgeGateStatus.EXPIRED
        ):
            await self._current_resolution(customer_session, require_match=True)
        return customer_session

    async def set_location(
        self, session_id: UUID, payload: SessionLocationUpdate
    ) -> CustomerSession:
        # Lock order is session -> business -> location, matching authorization and
        # preventing a concurrent switch/configuration from authorizing stale state.
        customer_session = await self._get_live(
            session_id, for_update=True, validate_binding=False
        )
        business = await BusinessService(self.session).get(
            self.tenant, self.tenant.business_id, for_update=True
        )
        location = await self._validate_location(payload.selected_location_id)
        resolution = self.resolver.resolve(business.compliance_domain, location)
        old_fingerprint = self._stored_fingerprint(customer_session)
        old_domain, old_jurisdiction, old_profile, old_version = old_fingerprint
        new_domain, new_jurisdiction, new_profile, new_version = resolution.fingerprint
        version_only_change = (
            old_domain == new_domain
            and old_jurisdiction == new_jurisdiction
            and old_profile == new_profile
            and old_version != new_version
        )
        if (
            location is not None
            and location.id == customer_session.selected_location_id
            and version_only_change
        ):
            # Re-selecting the same location is not an opt-in to a changed legal
            # profile version. Start a fresh session after a version-only update.
            raise self._stale_binding_error()

        customer_session.selected_location_id = location.id if location else None
        if resolution.fingerprint != old_fingerprint:
            customer_session.age_gate_status = self._initial_age_state(resolution)
            customer_session.age_attested_at = None
        resolution.bind_session(customer_session)
        await self.session.flush()
        await self.session.refresh(customer_session)
        return customer_session

    async def attest(
        self, session_id: UUID, payload: AgeAttestationRequest
    ) -> CustomerSession:
        customer_session = await self._get_live(session_id, for_update=True)
        resolution = await self._current_resolution(
            customer_session,
            require_match=True,
            lock_business=True,
            lock_location=True,
        )
        profile = resolution.profile
        if profile is None:
            self._raise_resolution_error(resolution)
        try:
            current_status = AgeGateStatus(customer_session.age_gate_status)
        except ValueError as exc:
            raise ComplianceError(
                "COMPLIANCE_STATE_INVALID",
                "the session has an invalid age-gate state",
            ) from exc

        transition = transition_age_gate(
            current_status,
            confirmed_21_or_older=payload.confirmed_21_or_older,
            requires_age_gate=profile.requires_age_gate,
            now=self.clock(),
            previous_attested_at=customer_session.age_attested_at,
        )
        customer_session.age_gate_status = transition.status
        customer_session.age_attested_at = transition.attested_at
        await self.session.flush()
        await self.session.refresh(customer_session)
        return customer_session

    async def resolve_current(
        self, customer_session: CustomerSession, *, require_match: bool = True
    ) -> EffectiveComplianceResolution:
        """Share the authoritative resolver with customer information handlers."""

        return await self._current_resolution(
            customer_session, require_match=require_match
        )

    async def _get(
        self, session_id: UUID, *, for_update: bool = False
    ) -> CustomerSession:
        return await self.sessions.get(
            session_id,
            resource_name="session",
            for_update=for_update,
        )

    async def _get_live(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
        validate_binding: bool = True,
    ) -> CustomerSession:
        customer_session = await self._get(session_id, for_update=for_update)
        await self._expire_if_needed(customer_session)
        if customer_session.age_gate_status == AgeGateStatus.EXPIRED:
            raise ComplianceError(
                "SESSION_EXPIRED",
                "the customer session has expired; create a new session",
                status_code=410,
            )
        if validate_binding:
            await self._current_resolution(customer_session, require_match=True)
        return customer_session

    async def _expire_if_needed(self, customer_session: CustomerSession) -> None:
        if customer_session.age_gate_status == AgeGateStatus.EXPIRED:
            return
        if ensure_utc(customer_session.expires_at) <= ensure_utc(self.clock()):
            customer_session.age_gate_status = AgeGateStatus.EXPIRED
            await self.session.flush()

    async def _validate_location(self, location_id: UUID | None) -> Location | None:
        if location_id is None:
            return None
        location = await self.locations.get(
            location_id,
            resource_name="location",
            for_update=True,
        )
        if not location.active:
            raise ComplianceError(
                "LOCATION_INACTIVE",
                "inactive locations cannot be selected for a customer session",
                status_code=409,
            )
        return location

    async def _current_resolution(
        self,
        customer_session: CustomerSession,
        *,
        require_match: bool,
        lock_business: bool = False,
        lock_location: bool = False,
    ) -> EffectiveComplianceResolution:
        business = await BusinessService(self.session).get(
            self.tenant,
            self.tenant.business_id,
            for_update=lock_business,
        )
        resolution = await self.resolver.resolve_session(
            self.session,
            business,
            customer_session,
            lock_location=lock_location,
        )
        if require_match and not resolution.matches_session(customer_session):
            raise self._stale_binding_error()
        return resolution

    @staticmethod
    def _stored_fingerprint(
        customer_session: CustomerSession,
    ) -> tuple[str, str | None, str | None, str | None]:
        return (
            customer_session.compliance_domain,
            customer_session.compliance_jurisdiction_code,
            customer_session.compliance_profile_id,
            customer_session.compliance_profile_version,
        )

    @staticmethod
    def _initial_age_state(
        resolution: EffectiveComplianceResolution,
    ) -> AgeGateStatus:
        if resolution.profile is not None:
            return AgeGateStatus(
                initial_age_gate_status(
                    requires_age_gate=resolution.profile.requires_age_gate
                )
            )
        if resolution.compliance_domain == "cannabis":
            return AgeGateStatus.REQUIRED_UNVERIFIED
        return AgeGateStatus.NOT_REQUIRED

    @staticmethod
    def _raise_resolution_error(
        resolution: EffectiveComplianceResolution,
    ) -> NoReturn:
        if resolution.reason_code == "COMPLIANCE_LOCATION_REQUIRED":
            raise ComplianceError(
                "COMPLIANCE_LOCATION_REQUIRED",
                "select an active location before completing the cannabis age attestation",
                status_code=409,
            )
        raise ComplianceError(
            "COMPLIANCE_PROFILE_UNAVAILABLE",
            "compliance support is unavailable for the selected jurisdiction",
            status_code=403,
        )

    @staticmethod
    def _stale_binding_error() -> ComplianceError:
        return ComplianceError(
            "COMPLIANCE_PROFILE_MISMATCH",
            "the session uses a stale compliance binding; select a different active location or create a new session",
            status_code=409,
        )
