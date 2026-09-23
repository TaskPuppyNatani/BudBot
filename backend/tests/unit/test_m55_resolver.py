"""Deterministic jurisdiction/domain resolution tests for M5.5."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from budbot.compliance.profiles.general_retail import GENERAL_RETAIL_PROFILE
from budbot.compliance.profiles.oregon_cannabis import OREGON_CANNABIS_PROFILE
from budbot.compliance.registry import get_catalog
from budbot.compliance.resolver import (
    ComplianceResolutionStatus,
    ComplianceProfileOverride,
    ComplianceResolver,
    canonical_jurisdiction_code,
)
from budbot.compliance.types import ComplianceCapability


def _location(country: str, region_code: str | None):
    return SimpleNamespace(country=country, region_code=region_code)


def test_general_retail_is_global_and_never_uses_a_cannabis_profile() -> None:
    resolver = ComplianceResolver()

    without_location = resolver.resolve("general_retail", None)
    with_location = resolver.resolve("general_retail", _location("US", "NM"))

    assert without_location.supported
    assert with_location.supported
    assert without_location.profile_id == "general_retail"
    assert with_location.profile_id == "general_retail"
    assert with_location.jurisdiction_code is None
    assert not with_location.profile.requires_age_gate
    assert (
        with_location.profile.rule_for(ComplianceCapability.CANNABIS_PRODUCTS).policy.value
        == "prohibited"
    )


def test_cannabis_resolves_by_explicit_canonical_jurisdiction() -> None:
    resolver = ComplianceResolver()

    oregon = resolver.resolve("cannabis", _location("us", "or"))
    new_mexico = resolver.resolve("cannabis", _location("US", "NM"))

    assert oregon.supported
    assert oregon.fingerprint == ("cannabis", "US-OR", "oregon_cannabis", "1.0")
    assert new_mexico.supported
    assert new_mexico.fingerprint == (
        "cannabis",
        "US-NM",
        "new_mexico_cannabis",
        "1.0",
    )
    assert new_mexico.profile.minimum_age == 21
    assert "does not verify" in new_mexico.profile.medical_eligibility_notice


def test_unresolved_and_unsupported_cannabis_never_fall_back_to_oregon() -> None:
    resolver = ComplianceResolver()

    no_location = resolver.resolve("cannabis", None)
    unsupported = resolver.resolve("cannabis", _location("US", "AZ"))
    unconfigured = resolver.resolve("cannabis", _location("US", None))

    assert no_location.profile is None
    assert no_location.status is ComplianceResolutionStatus.LOCATION_REQUIRED
    assert no_location.reason_code == "COMPLIANCE_LOCATION_REQUIRED"
    assert unsupported.profile is None
    assert unsupported.jurisdiction_code == "US-AZ"
    assert unsupported.status is ComplianceResolutionStatus.PROFILE_UNAVAILABLE
    assert unsupported.reason_code == "COMPLIANCE_PROFILE_UNAVAILABLE"
    assert unconfigured.profile is None
    assert unconfigured.reason_code == "COMPLIANCE_PROFILE_UNAVAILABLE"


def test_override_requires_an_installed_compatible_profile() -> None:
    resolver = ComplianceResolver()
    business_id, location_id = uuid4(), uuid4()
    location = SimpleNamespace(
        id=location_id,
        country="US",
        region_code="NM",
    )

    invalid = resolver.resolve(
        "cannabis",
        location,
        business_id=business_id,
        profile_override=ComplianceProfileOverride(
            business_id, location_id, "made_up", "1.0"
        ),
    )
    wrong_state = resolver.resolve(
        "cannabis",
        location,
        business_id=business_id,
        profile_override=ComplianceProfileOverride(
            business_id, location_id, "oregon_cannabis", "1.0"
        ),
    )
    compatible = resolver.resolve(
        "cannabis",
        location,
        business_id=business_id,
        profile_override=ComplianceProfileOverride(
            business_id, location_id, "new_mexico_cannabis", "1.0"
        ),
    )
    cross_tenant = resolver.resolve(
        "cannabis",
        location,
        business_id=uuid4(),
        profile_override=ComplianceProfileOverride(
            business_id, location_id, "new_mexico_cannabis", "1.0"
        ),
    )

    assert invalid.status is ComplianceResolutionStatus.INVALID_OVERRIDE
    assert wrong_state.status is ComplianceResolutionStatus.INVALID_OVERRIDE
    assert compatible.profile_id == "new_mexico_cannabis"
    assert cross_tenant.status is ComplianceResolutionStatus.INVALID_OVERRIDE


def test_catalog_activation_returns_a_new_immutable_catalog() -> None:
    staged = replace(
        OREGON_CANNABIS_PROFILE,
        profile_id="oregon_cannabis",
        version="1.1",
        active=False,
    )
    original = get_catalog()
    with_staged = original.with_profile(staged)
    activated_catalog = with_staged.activate("oregon_cannabis", "1.1")
    assert original.applicable(
        OREGON_CANNABIS_PROFILE.compliance_domain, "US-OR"
    ).version == "1.0"
    assert ComplianceResolver(activated_catalog).resolve(
        "cannabis", _location("US", "OR")
    ).profile.version == "1.1"
    assert isinstance(get_catalog().profiles, tuple)
    assert GENERAL_RETAIL_PROFILE.active


def test_jurisdiction_code_never_uses_display_region() -> None:
    assert canonical_jurisdiction_code("us", " nm ") == "US-NM"
    assert canonical_jurisdiction_code("US", None) is None
    assert canonical_jurisdiction_code("United States", "New Mexico") is None
