"""Tenant-scoped customer-session lifecycle behavior."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.compliance.age_gate import (
    AgeGateStatus,
    initial_age_gate_status,
    transition_age_gate,
)
from budbot.compliance.registry import ComplianceProfile, get_profile
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
    """Create and mutate sessions without ever leaving tenant scope."""

    def __init__(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        *,
        ttl_seconds: int = 86_400,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("session TTL must be positive")
        self.session = session
        self.tenant = tenant
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.sessions = TenantScopedRepository(session, CustomerSession, tenant)
        self.locations = TenantScopedRepository(session, Location, tenant)

    async def create(self, payload: CustomerSessionCreate) -> CustomerSession:
        business = await BusinessService(self.session).get(
            self.tenant, self.tenant.business_id
        )
        profile = self._profile_for_business(business)
        selected_location_id = await self._validate_location(
            payload.selected_location_id
        )
        now = self.clock()
        customer_session = CustomerSession(
            business_id=self.tenant.business_id,
            selected_location_id=selected_location_id,
            compliance_profile_id=profile.profile_id,
            compliance_profile_version=profile.version,
            age_gate_status=AgeGateStatus(
                initial_age_gate_status(
                    requires_age_gate=profile.requires_age_gate
                )
            ),
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        self.session.add(customer_session)
        await self.session.flush()
        await self.session.refresh(customer_session)
        return customer_session

    async def get(self, session_id: UUID) -> CustomerSession:
        customer_session = await self._get(session_id)
        await self._expire_if_needed(customer_session)
        if customer_session.age_gate_status != AgeGateStatus.EXPIRED:
            await self._current_profile_for_session(customer_session)
        return customer_session

    async def set_location(
        self, session_id: UUID, payload: SessionLocationUpdate
    ) -> CustomerSession:
        customer_session = await self._get_live(session_id)
        customer_session.selected_location_id = await self._validate_location(
            payload.selected_location_id
        )
        await self.session.flush()
        await self.session.refresh(customer_session)
        return customer_session

    async def attest(
        self, session_id: UUID, payload: AgeAttestationRequest
    ) -> CustomerSession:
        # Serialize competing attestations on PostgreSQL so a stale read
        # cannot upgrade or overwrite a state transition after another request.
        customer_session = await self._get_live(session_id, for_update=True)
        profile = await self._current_profile_for_session(customer_session)
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

    async def _get(
        self, session_id: UUID, *, for_update: bool = False
    ) -> CustomerSession:
        return await self.sessions.get(
            session_id, resource_name="session", for_update=for_update
        )

    async def _get_live(
        self, session_id: UUID, *, for_update: bool = False
    ) -> CustomerSession:
        customer_session = await self._get(session_id, for_update=for_update)
        await self._expire_if_needed(customer_session)
        if customer_session.age_gate_status == AgeGateStatus.EXPIRED:
            raise ComplianceError(
                "SESSION_EXPIRED",
                "the customer session has expired; create a new session",
                status_code=410,
            )
        await self._current_profile_for_session(customer_session)
        return customer_session

    async def _expire_if_needed(self, customer_session: CustomerSession) -> None:
        if customer_session.age_gate_status == AgeGateStatus.EXPIRED:
            return
        if ensure_utc(customer_session.expires_at) <= ensure_utc(self.clock()):
            customer_session.age_gate_status = AgeGateStatus.EXPIRED
            await self.session.flush()

    async def _validate_location(self, location_id: UUID | None) -> UUID | None:
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
        return location.id

    def _profile_for_business(self, business: Business) -> ComplianceProfile:
        return get_profile(
            business.compliance_profile_id,
            business.compliance_profile_version,
        )

    async def _current_profile_for_session(
        self, customer_session: CustomerSession
    ) -> ComplianceProfile:
        business = await self.session.scalar(
            select(Business).where(Business.id == self.tenant.business_id)
        )
        if business is None:
            raise ResourceNotFound("business")
        active_profile = self._profile_for_business(business)
        stored_profile = get_profile(
            customer_session.compliance_profile_id,
            customer_session.compliance_profile_version,
        )
        if (
            stored_profile.profile_id != active_profile.profile_id
            or stored_profile.version != active_profile.version
        ):
            raise ComplianceError(
                "COMPLIANCE_PROFILE_MISMATCH",
                "the session uses a stale compliance profile; create a new session",
                status_code=409,
            )
        return active_profile
