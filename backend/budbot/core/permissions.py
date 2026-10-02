"""Central administrative role-to-permission policy."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType


class AdminPermission(StrEnum):
    BUSINESS_READ = "business.read"
    BUSINESS_WRITE = "business.write"
    BUSINESS_CREATE = "business.create"
    LOCATION_READ = "location.read"
    LOCATION_WRITE = "location.write"
    ASSISTANT_READ = "assistant.read"
    ASSISTANT_WRITE = "assistant.write"
    COMPLIANCE_READ = "compliance.read"
    COMPLIANCE_WRITE = "compliance.write"
    BRANDING_READ = "branding.read"
    BRANDING_WRITE = "branding.write"
    MEMBERSHIP_MANAGE = "membership.manage"
    AUDIT_READ = "audit.read"
    PROVIDER_READ = "provider.read"
    PROVIDER_WRITE = "provider.write"


_READ_PERMISSIONS = frozenset(
    {
        AdminPermission.BUSINESS_READ.value,
        AdminPermission.LOCATION_READ.value,
        AdminPermission.ASSISTANT_READ.value,
        AdminPermission.COMPLIANCE_READ.value,
        AdminPermission.BRANDING_READ.value,
    }
)

ROLE_PERMISSIONS = MappingProxyType(
    {
        "owner": frozenset(permission.value for permission in AdminPermission),
        "admin": _READ_PERMISSIONS
        | frozenset(
            {
                AdminPermission.BUSINESS_WRITE.value,
                AdminPermission.LOCATION_WRITE.value,
                AdminPermission.ASSISTANT_WRITE.value,
                AdminPermission.BRANDING_WRITE.value,
            }
        ),
        "manager": _READ_PERMISSIONS
        | frozenset({AdminPermission.LOCATION_WRITE.value}),
        "viewer": _READ_PERMISSIONS,
    }
)


def permissions_for_role(role: str) -> frozenset[str]:
    """Return no permissions for unknown or malformed legacy role labels."""

    return ROLE_PERMISSIONS.get(role.strip().casefold(), frozenset())


def role_allows(role: str, permission: str | AdminPermission) -> bool:
    return str(permission) in permissions_for_role(role)
