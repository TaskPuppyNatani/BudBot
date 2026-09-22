"""Initial Oregon recreational website/session profile."""

from datetime import date

from budbot.compliance.types import (
    CapabilityPolicy,
    ComplianceCapability,
    ComplianceProfile,
    CapabilityRule,
)


OREGON_CANNABIS_PROFILE = ComplianceProfile(
    profile_id="oregon_cannabis",
    version="1.0",
    jurisdiction="Oregon, United States",
    effective_from=date(2026, 9, 19),
    reviewed_at=date(2026, 9, 19),
    source_references=(
        "docs/compliance.md",
        "https://www.oregon.gov/olcc/marijuana/pages/frequently-asked-questions.aspx",
        "https://secure.sos.state.or.us/oard/viewSingleRule.action?ruleVrsnRsn=255959",
    ),
    requires_age_gate=True,
    minimum_age=21,
    website_attestation_notice=(
        "This 21+ website/session attestation is not government-ID verification, "
        "legal proof of age, purchase authorization, or a replacement for retailer "
        "or POS identification checks. OMMP verification is not implemented."
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
