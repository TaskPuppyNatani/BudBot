"""The industry-neutral, non-cannabis default profile."""

from datetime import date

from budbot.compliance.types import (
    CapabilityPolicy,
    ComplianceCapability,
    ComplianceProfile,
    CapabilityRule,
)


GENERAL_RETAIL_PROFILE = ComplianceProfile(
    profile_id="general_retail",
    version="1.0",
    jurisdiction="general",
    effective_from=date(2026, 9, 19),
    reviewed_at=date(2026, 9, 19),
    source_references=("docs/compliance.md",),
    requires_age_gate=False,
    minimum_age=None,
    website_attestation_notice=(
        "This general-retail profile does not require a cannabis age attestation."
    ),
    capability_rules={
        ComplianceCapability.BUSINESS_HOURS: CapabilityRule(
            CapabilityPolicy.PUBLIC, "PUBLIC_CAPABILITY"
        ),
        ComplianceCapability.LOCATIONS: CapabilityRule(
            CapabilityPolicy.PUBLIC, "PUBLIC_CAPABILITY"
        ),
        ComplianceCapability.CONTACT: CapabilityRule(
            CapabilityPolicy.PUBLIC, "PUBLIC_CAPABILITY"
        ),
        ComplianceCapability.AGE_INFORMATION: CapabilityRule(
            CapabilityPolicy.PUBLIC, "PUBLIC_CAPABILITY"
        ),
        # A general-retail tenant must not inherit Oregon's age gate. Cannabis
        # capabilities are still unavailable unless a cannabis profile is active.
        ComplianceCapability.CANNABIS_PRODUCTS: CapabilityRule(
            CapabilityPolicy.PROHIBITED, "CAPABILITY_PROHIBITED"
        ),
        ComplianceCapability.CANNABIS_SEARCH: CapabilityRule(
            CapabilityPolicy.PROHIBITED, "CAPABILITY_PROHIBITED"
        ),
        ComplianceCapability.CANNABIS_DEALS: CapabilityRule(
            CapabilityPolicy.PROHIBITED, "CAPABILITY_PROHIBITED"
        ),
        ComplianceCapability.MEDICAL_ADVICE: CapabilityRule(
            CapabilityPolicy.PROHIBITED, "CAPABILITY_PROHIBITED"
        ),
    },
)
