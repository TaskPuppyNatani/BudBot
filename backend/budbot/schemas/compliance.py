"""Safe API representations for compliance profile configuration."""

from datetime import date

from pydantic import Field, StringConstraints
from typing import Annotated

from budbot.schemas.common import DomainSchema

ComplianceProfileId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9_]+$",
    ),
]


class ComplianceProfileUpdate(DomainSchema):
    """The only ordinary configuration input: select a known profile."""

    profile_id: ComplianceProfileId


class ComplianceProfileRead(DomainSchema):
    profile_id: str
    version: str
    jurisdiction: str
    compliance_domain: str
    jurisdiction_code: str | None
    format_version: int
    effective_from: date
    reviewed_at: date
    source_references: list[str] = Field(default_factory=list)
    requires_age_gate: bool
    minimum_age: int | None
    website_attestation_notice: str
    medical_eligibility_notice: str | None
