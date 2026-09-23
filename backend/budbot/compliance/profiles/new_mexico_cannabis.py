"""Initial New Mexico recreational website/session profile."""

from datetime import date

from budbot.compliance.types import (
    CapabilityPolicy,
    CapabilityRule,
    ComplianceCapability,
    ComplianceProfile,
)


NEW_MEXICO_CANNABIS_PROFILE = ComplianceProfile(
    profile_id="new_mexico_cannabis",
    version="1.0",
    jurisdiction="New Mexico, United States",
    effective_from=date(2022, 4, 1),
    reviewed_at=date(2026, 9, 23),
    source_references=(
        "https://www.rld.nm.gov/cannabis/cannabis-in-new-mexico/faqs/",
        "https://www.rld.nm.gov/wp-content/uploads/2025/10/25-15.pdf",
        "https://www.srca.nm.gov/parts/title16/16.008.0003.html",
    ),
    requires_age_gate=True,
    minimum_age=21,
    website_attestation_notice=(
        "This 21+ website/session attestation is for the adult-use flow only. "
        "It is not government-ID verification, legal proof of age, purchase "
        "authorization, or a replacement for retailer or point-of-sale checks."
    ),
    medical_eligibility_notice=(
        "New Mexico has a separate medical-cannabis pathway; qualifying patients "
        "age 18+ may be eligible subject to program requirements and required "
        "patient and government identification. BudBot does not verify medical "
        "eligibility, patient registry cards, or identity."
    ),
    compliance_domain="cannabis",
    jurisdiction_code="US-NM",
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
        ComplianceCapability.CANNABIS_PRODUCTS: CapabilityRule(
            CapabilityPolicy.AGE_GATED, "AGE_VERIFICATION_REQUIRED"
        ),
        ComplianceCapability.CANNABIS_SEARCH: CapabilityRule(
            CapabilityPolicy.AGE_GATED, "AGE_VERIFICATION_REQUIRED"
        ),
        ComplianceCapability.CANNABIS_DEALS: CapabilityRule(
            CapabilityPolicy.AGE_GATED, "AGE_VERIFICATION_REQUIRED"
        ),
        ComplianceCapability.MEDICAL_ADVICE: CapabilityRule(
            CapabilityPolicy.PROHIBITED, "CAPABILITY_PROHIBITED"
        ),
    },
)
