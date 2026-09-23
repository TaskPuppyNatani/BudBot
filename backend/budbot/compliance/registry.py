"""Immutable catalog of declarative, versioned compliance profiles."""

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from budbot.compliance.types import (
    Capability,
    CapabilityPolicy,
    CapabilityRule,
    ComplianceCapability,
    ComplianceDomain,
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


@dataclass(frozen=True, slots=True)
class ComplianceCatalog:
    """An immutable profile package set with explicitly selected active versions."""

    profiles: tuple[ComplianceProfile, ...]
    _by_key: Mapping[tuple[str, str], ComplianceProfile] = field(
        init=False, repr=False, compare=False
    )
    _active_by_id: Mapping[str, ComplianceProfile] = field(
        init=False, repr=False, compare=False
    )
    _active_by_scope: Mapping[
        tuple[ComplianceDomain, str | None], ComplianceProfile
    ] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_key: dict[tuple[str, str], ComplianceProfile] = {}
        active_by_id: dict[str, ComplianceProfile] = {}
        active_by_scope: dict[
            tuple[ComplianceDomain, str | None], ComplianceProfile
        ] = {}
        for profile in self.profiles:
            key = _profile_key(profile.profile_id, profile.version)
            if key in by_key:
                raise ValueError(f"duplicate compliance profile package: {key}")
            by_key[key] = profile
            if not profile.active:
                continue
            if profile.profile_id in active_by_id:
                raise ValueError(f"multiple active versions for {profile.profile_id}")
            active_by_id[profile.profile_id] = profile
            scope = (
                ComplianceDomain(profile.compliance_domain),
                profile.jurisdiction_code,
            )
            if scope in active_by_scope:
                raise ValueError(f"multiple active profiles for applicability {scope}")
            active_by_scope[scope] = profile
        object.__setattr__(self, "profiles", tuple(self.profiles))
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))
        object.__setattr__(self, "_active_by_id", MappingProxyType(active_by_id))
        object.__setattr__(self, "_active_by_scope", MappingProxyType(active_by_scope))

    def exact(self, profile_id: str, version: str) -> ComplianceProfile | None:
        return self._by_key.get(_profile_key(profile_id, version))

    def active(self, profile_id: str) -> ComplianceProfile | None:
        return self._active_by_id.get(profile_id)

    def applicable(
        self, domain: ComplianceDomain, jurisdiction_code: str | None
    ) -> ComplianceProfile | None:
        return self._active_by_scope.get((domain, jurisdiction_code))

    def with_profile(
        self, profile: ComplianceProfile, *, activate: bool = False
    ) -> "ComplianceCatalog":
        """Return a staged or activated catalog; the existing catalog is untouched."""

        if self.exact(profile.profile_id, profile.version) is not None:
            raise ValueError("that profile ID/version is already registered")
        additions = list(self.profiles)
        if activate:
            scope = (ComplianceDomain(profile.compliance_domain), profile.jurisdiction_code)
            additions = [
                replace(item, active=False)
                if (ComplianceDomain(item.compliance_domain), item.jurisdiction_code) == scope
                else item
                for item in additions
            ]
            profile = replace(profile, active=True)
        else:
            profile = replace(profile, active=False)
        return ComplianceCatalog((*additions, profile))

    def activate(self, profile_id: str, version: str) -> "ComplianceCatalog":
        """Return a catalog with exactly this registered applicability active."""

        target = self.exact(profile_id, version)
        if target is None:
            raise _unknown_profile()
        scope = (ComplianceDomain(target.compliance_domain), target.jurisdiction_code)
        return ComplianceCatalog(
            tuple(
                replace(profile, active=(profile is target))
                if (ComplianceDomain(profile.compliance_domain), profile.jurisdiction_code)
                == scope
                else profile
                for profile in self.profiles
            )
        )


# Imports are intentionally below the shared types so catalog assembly is separate
# from the immutable profile dataclasses.
from budbot.compliance.profiles.general_retail import GENERAL_RETAIL_PROFILE  # noqa: E402
from budbot.compliance.profiles.new_mexico_cannabis import NEW_MEXICO_CANNABIS_PROFILE  # noqa: E402
from budbot.compliance.profiles.oregon_cannabis import OREGON_CANNABIS_PROFILE  # noqa: E402

COMPLIANCE_CATALOG = ComplianceCatalog(
    (
        GENERAL_RETAIL_PROFILE,
        OREGON_CANNABIS_PROFILE,
        NEW_MEXICO_CANNABIS_PROFILE,
    )
)
COMPLIANCE_PROFILES: Mapping[tuple[str, str], ComplianceProfile] = MappingProxyType(
    {
        _profile_key(profile.profile_id, profile.version): profile
        for profile in COMPLIANCE_CATALOG.profiles
    }
)
ACTIVE_PROFILE_VERSIONS: Mapping[str, str] = MappingProxyType(
    {
        profile.profile_id: profile.version
        for profile in COMPLIANCE_CATALOG.profiles
        if profile.active
    }
)


def get_catalog() -> ComplianceCatalog:
    """Return the built-in immutable catalog (swapped only by trusted app wiring)."""

    return COMPLIANCE_CATALOG


def get_profile(profile_id: str, version: str | None = None) -> ComplianceProfile:
    """Return one exact or active profile version; never fall back on unknown input."""

    catalog = get_catalog()
    profile = catalog.exact(profile_id, version) if version is not None else catalog.active(profile_id)
    if profile is None:
        raise _unknown_profile()
    return profile


def list_profiles() -> tuple[ComplianceProfile, ...]:
    """Return registered profiles in stable identifier/version order."""

    return tuple(
        sorted(
            get_catalog().profiles,
            key=lambda item: (item.profile_id, item.version),
        )
    )


__all__ = [
    "ACTIVE_PROFILE_VERSIONS",
    "COMPLIANCE_CATALOG",
    "COMPLIANCE_PROFILES",
    "Capability",
    "CapabilityPolicy",
    "CapabilityRule",
    "ComplianceCatalog",
    "ComplianceCapability",
    "ComplianceDomain",
    "ComplianceProfile",
    "get_catalog",
    "get_profile",
    "list_profiles",
]
