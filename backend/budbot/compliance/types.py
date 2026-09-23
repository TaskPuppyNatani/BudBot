"""Shared immutable compliance-policy types."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Mapping

from budbot.core.exceptions import ComplianceError


class CapabilityPolicy(StrEnum):
    """How a profile classifies a capability."""

    PUBLIC = "public"
    AGE_GATED = "age_gated"
    PROHIBITED = "prohibited"


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
