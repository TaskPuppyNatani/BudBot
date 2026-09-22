"""Versioned compliance-profile types and the fail-closed registry."""

from budbot.compliance.types import (
    Capability,
    CapabilityPolicy,
    CapabilityRule,
    ComplianceCapability,
    ComplianceProfile,
)
from budbot.core.exceptions import ComplianceError


def _profile_key(profile_id: str, version: str) -> tuple[str, str]:
    return profile_id, version


def _unknown_profile() -> ComplianceError:
    return ComplianceError(
        "UNKNOWN_COMPLIANCE_PROFILE",
        "the active compliance profile is not recognized; protected behavior is disabled",
        status_code=422,
    )


# Imports are intentionally below the shared types so registry assembly is
# separate from the shared profile dataclasses.
from budbot.compliance.profiles.general_retail import GENERAL_RETAIL_PROFILE  # noqa: E402
from budbot.compliance.profiles.oregon_cannabis import OREGON_CANNABIS_PROFILE  # noqa: E402


COMPLIANCE_PROFILES: dict[tuple[str, str], ComplianceProfile] = {
    _profile_key(GENERAL_RETAIL_PROFILE.profile_id, GENERAL_RETAIL_PROFILE.version): GENERAL_RETAIL_PROFILE,
    _profile_key(OREGON_CANNABIS_PROFILE.profile_id, OREGON_CANNABIS_PROFILE.version): OREGON_CANNABIS_PROFILE,
}
ACTIVE_PROFILE_VERSIONS: dict[str, str] = {
    profile.profile_id: profile.version for profile in COMPLIANCE_PROFILES.values()
}


def get_profile(profile_id: str, version: str | None = None) -> ComplianceProfile:
    """Return one exact profile version; never fall back on unknown input."""

    active_version = (
        ACTIVE_PROFILE_VERSIONS.get(profile_id) if version is None else version
    )
    if active_version is None:
        raise _unknown_profile()
    profile = COMPLIANCE_PROFILES.get(_profile_key(profile_id, active_version))
    if profile is None:
        raise _unknown_profile()
    return profile


def list_profiles() -> tuple[ComplianceProfile, ...]:
    """Return registered profiles in stable identifier order."""

    return tuple(sorted(COMPLIANCE_PROFILES.values(), key=lambda item: item.profile_id))
