"""Pure deterministic M3 profile and age-state tests."""

from datetime import UTC, datetime

import pytest

from budbot.compliance.age_gate import (
    AgeGateStatus,
    initial_age_gate_status,
    transition_age_gate,
)
from budbot.compliance.registry import (
    CapabilityPolicy,
    ComplianceCapability,
    get_profile,
)
from budbot.core.exceptions import ComplianceError


def test_registry_is_versioned_and_fails_closed_for_unknown_values() -> None:
    general = get_profile("general_retail", "1.0")
    oregon = get_profile("oregon_cannabis", "1.0")
    assert general.requires_age_gate is False
    assert oregon.requires_age_gate is True
    assert oregon.minimum_age == 21
    assert (
        oregon.rule_for(ComplianceCapability.CANNABIS_PRODUCTS).policy
        is CapabilityPolicy.AGE_GATED
    )
    assert (
        oregon.rule_for(ComplianceCapability.CANNABIS_SEARCH).policy
        is CapabilityPolicy.AGE_GATED
    )
    assert (
        oregon.rule_for(ComplianceCapability.CANNABIS_DEALS).policy
        is CapabilityPolicy.AGE_GATED
    )
    assert (
        oregon.rule_for(ComplianceCapability.AGE_INFORMATION).policy
        is CapabilityPolicy.PUBLIC
    )

    with pytest.raises(ComplianceError, match="not recognized") as unknown_profile:
        get_profile("does_not_exist", "1.0")
    assert unknown_profile.value.code == "UNKNOWN_COMPLIANCE_PROFILE"

    with pytest.raises(ComplianceError) as unknown_capability:
        oregon.rule_for("future_unregistered_capability")
    assert unknown_capability.value.code == "UNKNOWN_CAPABILITY"


def test_age_gate_transitions_are_explicit_and_non_reversible() -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    assert (
        initial_age_gate_status(requires_age_gate=False)
        is AgeGateStatus.NOT_REQUIRED
    )
    assert (
        initial_age_gate_status(requires_age_gate=True)
        is AgeGateStatus.REQUIRED_UNVERIFIED
    )

    verified = transition_age_gate(
        AgeGateStatus.REQUIRED_UNVERIFIED,
        confirmed_21_or_older=True,
        requires_age_gate=True,
        now=now,
        previous_attested_at=None,
    )
    assert verified.status is AgeGateStatus.VERIFIED
    assert verified.attested_at == now

    with pytest.raises(ComplianceError) as downgrade:
        transition_age_gate(
            AgeGateStatus.VERIFIED,
            confirmed_21_or_older=False,
            requires_age_gate=True,
            now=now,
            previous_attested_at=now,
        )
    assert downgrade.value.code == "AGE_VERIFICATION_DENIED"

    with pytest.raises(ComplianceError) as expired:
        transition_age_gate(
            AgeGateStatus.EXPIRED,
            confirmed_21_or_older=True,
            requires_age_gate=True,
            now=now,
            previous_attested_at=None,
        )
    assert expired.value.code == "SESSION_EXPIRED"
