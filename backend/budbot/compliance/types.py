"""Shared immutable compliance-policy types."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Mapping

from budbot.core.exceptions import ComplianceError


class CapabilityPolicy(StrEnum):
    """How a profile classifies a capability."""

    PUBLIC = "public"
    AGE_GATED = "age_gated"
    PROHIBITED = "prohibited"


class ComplianceDomain(StrEnum):
    """Small stable policy domains, deliberately separate from industry text."""

    GENERAL_RETAIL = "general_retail"
    CANNABIS = "cannabis"


class ComplianceCapability(StrEnum):
    """Stable capability identifiers used by future routes and tools."""

    BUSINESS_HOURS = "business_hours"
    LOCATIONS = "locations"
    LOCATION_INFO = "locations"
    CONTACT = "contact"
    AGE_INFORMATION = "age_information"
    CANNABIS_PRODUCTS = "cannabis_products"
    CANNABIS_PRODUCT_BROWSING = "cannabis_products"
    CANNABIS_SEARCH = "cannabis_search"
    CANNABIS_PRODUCT_SEARCH = "cannabis_search"
    CANNABIS_DEALS = "cannabis_deals"
    CANNABIS_PROMOTIONS = "cannabis_deals"
    MEDICAL_ADVICE = "medical_advice"
    PERSONALIZED_CANNABIS_MEDICAL_ADVICE = "medical_advice"


Capability = ComplianceCapability

SAFE_PUBLIC_CAPABILITIES = frozenset(
    {
        ComplianceCapability.BUSINESS_HOURS,
        ComplianceCapability.LOCATIONS,
        ComplianceCapability.CONTACT,
        ComplianceCapability.AGE_INFORMATION,
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityRule:
    """Deterministic policy and stable reason code for one capability."""

    policy: CapabilityPolicy
    reason_code: str


@dataclass(frozen=True, slots=True)
class ComplianceProfile:
    """Immutable, inspectable policy metadata for one profile version."""

    profile_id: str
    version: str
    jurisdiction: str
    effective_from: date
    reviewed_at: date
    source_references: tuple[str, ...]
    requires_age_gate: bool
    minimum_age: int | None
    website_attestation_notice: str
    capability_rules: Mapping[ComplianceCapability, CapabilityRule]
    medical_eligibility_notice: str | None = None
    compliance_domain: ComplianceDomain = ComplianceDomain.GENERAL_RETAIL
    jurisdiction_code: str | None = None
    format_version: int = 1
    active: bool = True

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.version.strip():
            raise ValueError("compliance profile ID and version are required")
        if self.format_version < 1:
            raise ValueError("compliance profile format version must be positive")
        if self.requires_age_gate and self.minimum_age is None:
            raise ValueError("age-gated profiles must declare a minimum age")
        if not self.requires_age_gate and self.minimum_age is not None:
            raise ValueError("profiles without an age gate cannot declare a minimum age")
        domain = ComplianceDomain(self.compliance_domain)
        if domain is ComplianceDomain.GENERAL_RETAIL and self.jurisdiction_code is not None:
            raise ValueError("general-retail profiles must be jurisdiction-neutral")
        if domain is ComplianceDomain.CANNABIS and (
            self.jurisdiction_code is None
            or not re.fullmatch(r"[A-Z]{2}-[A-Z]{2}", self.jurisdiction_code)
        ):
            raise ValueError("cannabis profiles require a canonical jurisdiction code")
        if self.reviewed_at < self.effective_from:
            raise ValueError("profile review date cannot precede its effective date")
        if not self.source_references:
            raise ValueError("compliance profiles require source metadata")
        object.__setattr__(self, "compliance_domain", domain)
        object.__setattr__(self, "source_references", tuple(self.source_references))
        object.__setattr__(
            self, "capability_rules", MappingProxyType(dict(self.capability_rules))
        )

    def initial_age_gate_status(self) -> str:
        """Return the initial persisted age state without importing the model."""

        return "REQUIRED_UNVERIFIED" if self.requires_age_gate else "NOT_REQUIRED"

    def rule_for(self, capability: ComplianceCapability | str) -> CapabilityRule:
        """Resolve a capability and fail closed when it is not registered."""

        try:
            normalized = ComplianceCapability(capability)
        except (TypeError, ValueError) as exc:
            raise ComplianceError(
                "UNKNOWN_CAPABILITY",
                "the requested capability is not recognized by the compliance registry",
            ) from exc

        try:
            return self.capability_rules[normalized]
        except KeyError as exc:
            raise ComplianceError(
                "UNKNOWN_CAPABILITY",
                "the requested capability is not recognized by the compliance registry",
            ) from exc
