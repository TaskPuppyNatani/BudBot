"""Central administrative role and permission policy."""

from budbot.core.permissions import (
    AdminPermission,
    permissions_for_role,
    role_allows,
)


def test_roles_grant_only_the_documented_administrative_permissions() -> None:
    read = {
        AdminPermission.BUSINESS_READ.value,
        AdminPermission.LOCATION_READ.value,
        AdminPermission.ASSISTANT_READ.value,
        AdminPermission.COMPLIANCE_READ.value,
        AdminPermission.BRANDING_READ.value,
    }
    assert permissions_for_role("viewer") == frozenset(read)
    assert permissions_for_role("manager") == frozenset(
        read | {AdminPermission.LOCATION_WRITE.value}
    )

    admin = permissions_for_role("admin")
    assert read <= admin
    assert {
        AdminPermission.BUSINESS_WRITE.value,
        AdminPermission.LOCATION_WRITE.value,
        AdminPermission.ASSISTANT_WRITE.value,
        AdminPermission.BRANDING_WRITE.value,
    } <= admin
    assert AdminPermission.COMPLIANCE_WRITE.value not in admin
    assert AdminPermission.MEMBERSHIP_MANAGE.value not in admin
    assert AdminPermission.PROVIDER_WRITE.value not in admin

    owner = permissions_for_role("owner")
    assert owner == frozenset(permission.value for permission in AdminPermission)
    assert role_allows(" Owner ", AdminPermission.PROVIDER_WRITE)
    assert permissions_for_role("custom-role") == frozenset()
    assert not role_allows("custom-role", AdminPermission.BUSINESS_READ)
