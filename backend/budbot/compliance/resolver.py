"""Single location-aware resolver for effective compliance policy bindings."""

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.compliance import registry
from budbot.compliance.registry import ComplianceCatalog
from budbot.compliance.types import ComplianceDomain, ComplianceProfile

if TYPE_CHECKING:
    from budbot.models.business import Business
    from budbot.models.location import Location
    from budbot.models.session import CustomerSession


class ComplianceResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    LOCATION_REQUIRED = "location_required"
    PROFILE_UNAVAILABLE = "profile_unavailable"
    INVALID_OVERRIDE = "invalid_override"


@dataclass(frozen=True, slots=True)
class ComplianceProfileOverride:
    """Trusted future location override, explicitly bound to one tenant/location."""

    business_id: UUID
    location_id: UUID
    profile_id: str
    profile_version: str


_CANONICAL_REGION = re.compile(r"^[A-Z]{2}$")
_CANONICAL_COUNTRY = re.compile(r"^[A-Z]{2}$")


def canonical_jurisdiction_code(
    country: str | None, region_code: str | None
) -> str | None:
    """Derive ISO-style jurisdiction tokens only from explicit canonical codes."""

    if country is None or region_code is None:
        return None
    normalized_country = country.strip().upper()
    normalized_region = region_code.strip().upper()
    if (
        not _CANONICAL_COUNTRY.fullmatch(normalized_country)
        or not _CANONICAL_REGION.fullmatch(normalized_region)
    ):
        return None
    return f"{normalized_country}-{normalized_region}"


@dataclass(frozen=True, slots=True)
class EffectiveComplianceResolution:
    compliance_domain: str
    jurisdiction_code: str | None
    profile: ComplianceProfile | None
    status: ComplianceResolutionStatus
    reason_code: str | None = None

    @property
    def supported(self) -> bool:
        return self.status is ComplianceResolutionStatus.RESOLVED and self.profile is not None

    @property
    def profile_id(self) -> str | None:
        return self.profile.profile_id if self.profile is not None else None

    @property
    def profile_version(self) -> str | None:
        return self.profile.version if self.profile is not None else None

    @property
    def fingerprint(self) -> tuple[str, str | None, str | None, str | None]:
        return (
            self.compliance_domain,
            self.jurisdiction_code,
            self.profile_id,
            self.profile_version,
        )

    def matches_session(self, customer_session: "CustomerSession") -> bool:
        return self.fingerprint == (
            customer_session.compliance_domain,
            customer_session.compliance_jurisdiction_code,
            customer_session.compliance_profile_id,
            customer_session.compliance_profile_version,
        ) and self.status.value == customer_session.compliance_resolution_status

    def bind_session(self, customer_session: "CustomerSession") -> None:
        customer_session.compliance_domain = self.compliance_domain
        customer_session.compliance_jurisdiction_code = self.jurisdiction_code
        customer_session.compliance_profile_id = self.profile_id
        customer_session.compliance_profile_version = self.profile_version
        customer_session.compliance_resolution_status = self.status.value


class ComplianceResolver:
    """Resolve one active declarative profile from domain and selected location."""

    def __init__(self, catalog: ComplianceCatalog | None = None) -> None:
        self.catalog = catalog if catalog is not None else registry.get_catalog()

    def resolve(
        self,
        compliance_domain: str | ComplianceDomain,
        selected_location: "Location | None",
        *,
        business_id: UUID | None = None,
        profile_override: ComplianceProfileOverride | None = None,
    ) -> EffectiveComplianceResolution:
        domain_value = str(compliance_domain)
        try:
            domain = ComplianceDomain(domain_value)
        except ValueError:
            return self._unresolved(
                domain_value, None, ComplianceResolutionStatus.PROFILE_UNAVAILABLE
            )

        jurisdiction_code = (
            canonical_jurisdiction_code(
                selected_location.country, selected_location.region_code
            )
            if selected_location is not None and domain is ComplianceDomain.CANNABIS
            else None
        )

        if domain is ComplianceDomain.CANNABIS and selected_location is None:
            return self._unresolved(
                domain_value,
                None,
                ComplianceResolutionStatus.LOCATION_REQUIRED,
            )
        if domain is ComplianceDomain.CANNABIS and jurisdiction_code is None:
            return self._unresolved(
                domain_value,
                None,
                ComplianceResolutionStatus.PROFILE_UNAVAILABLE,
            )

        if profile_override is not None:
            if (
                selected_location is None
                or business_id is None
                or profile_override.business_id != business_id
                or profile_override.location_id != selected_location.id
            ):
                return self._unresolved(
                    domain_value,
                    jurisdiction_code,
                    ComplianceResolutionStatus.INVALID_OVERRIDE,
                )
            profile = self.catalog.active(profile_override.profile_id)
            if profile is None or profile.version != profile_override.profile_version:
                return self._unresolved(
                    domain_value,
                    jurisdiction_code,
                    ComplianceResolutionStatus.INVALID_OVERRIDE,
                )
            profile_domain = ComplianceDomain(profile.compliance_domain)
            expected_jurisdiction = (
                None if domain is ComplianceDomain.GENERAL_RETAIL else jurisdiction_code
            )
            if (
                profile_domain is not domain
                or profile.jurisdiction_code != expected_jurisdiction
            ):
                return self._unresolved(
                    domain_value,
                    jurisdiction_code,
                    ComplianceResolutionStatus.INVALID_OVERRIDE,
                )
        else:
            expected_jurisdiction = (
                None if domain is ComplianceDomain.GENERAL_RETAIL else jurisdiction_code
            )
            profile = self.catalog.applicable(domain, expected_jurisdiction)

        if profile is None:
            return self._unresolved(
                domain_value,
                jurisdiction_code,
                ComplianceResolutionStatus.PROFILE_UNAVAILABLE,
            )
        return EffectiveComplianceResolution(
            compliance_domain=domain_value,
            jurisdiction_code=jurisdiction_code,
            profile=profile,
            status=ComplianceResolutionStatus.RESOLVED,
        )

    async def resolve_session(
        self,
        session: AsyncSession,
        business: "Business",
        customer_session: "CustomerSession",
        *,
        lock_location: bool = False,
        profile_override: ComplianceProfileOverride | None = None,
    ) -> EffectiveComplianceResolution:
        """Load only an active same-tenant selected location, then resolve once."""

        from budbot.models.location import Location

        location = None
        if customer_session.selected_location_id is not None:
            statement = select(Location).where(
                Location.id == customer_session.selected_location_id,
                Location.business_id == business.id,
                Location.active.is_(True),
            )
            if lock_location:
                statement = statement.with_for_update().execution_options(
                    populate_existing=True
                )
            location = await session.scalar(statement)
        return self.resolve(
            business.compliance_domain,
            location,
            business_id=business.id,
            profile_override=profile_override,
        )

    @staticmethod
    def _unresolved(
        domain: str,
        jurisdiction_code: str | None,
        status: ComplianceResolutionStatus,
    ) -> EffectiveComplianceResolution:
        reason = {
            ComplianceResolutionStatus.LOCATION_REQUIRED: "COMPLIANCE_LOCATION_REQUIRED",
            ComplianceResolutionStatus.PROFILE_UNAVAILABLE: "COMPLIANCE_PROFILE_UNAVAILABLE",
            ComplianceResolutionStatus.INVALID_OVERRIDE: "COMPLIANCE_PROFILE_UNAVAILABLE",
        }[status]
        return EffectiveComplianceResolution(
            compliance_domain=domain,
            jurisdiction_code=jurisdiction_code,
            profile=None,
            status=status,
            reason_code=reason,
        )
