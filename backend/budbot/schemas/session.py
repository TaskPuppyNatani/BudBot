"""Customer-session request and response schemas."""

from datetime import datetime
from uuid import UUID

from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.resolver import ComplianceResolutionStatus
from budbot.schemas.common import DomainSchema


class CustomerSessionCreate(DomainSchema):
    """Start a session for the tenant selected by the development header."""

    selected_location_id: UUID | None = None


class SessionLocationUpdate(DomainSchema):
    """Select an active same-tenant location, or null to clear selection."""

    selected_location_id: UUID | None = None


class AgeAttestationRequest(DomainSchema):
    """Website/session attestation; it intentionally does not collect DOB."""

    confirmed_21_or_older: bool


class CustomerSessionRead(DomainSchema):
    id: UUID
    business_id: UUID
    selected_location_id: UUID | None
    compliance_domain: str
    compliance_jurisdiction_code: str | None
    compliance_profile_id: str | None
    compliance_profile_version: str | None
    compliance_resolution_status: ComplianceResolutionStatus
    age_gate_status: AgeGateStatus
    age_attested_at: datetime | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class SessionAgeGateRead(DomainSchema):
    """Minimal safe age-gate projection without identity or policy internals."""

    age_gate_status: AgeGateStatus
    age_attested_at: datetime | None
    expires_at: datetime


# Concise aliases for service and dependency callers.
SessionCreate = CustomerSessionCreate
SessionRead = CustomerSessionRead
