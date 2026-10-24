"""Informational compliance resolution; never changes mandatory controls."""

from budbot.commands.admin.common import result, selected_location
from budbot.compliance.resolver import ComplianceResolver
from budbot.services.business_service import BusinessService
from budbot.services.compliance_service import ComplianceService


async def compliance(context, parsed):
    item = await selected_location(context)
    business = await BusinessService(context.session).get(context.tenant, context.tenant.business_id)
    if item:
        resolution = ComplianceResolver().resolve(business.compliance_domain, item if item.active else None, business_id=business.id)
        profile = resolution.profile
        label = f"Location compliance: {resolution.status.value} | {resolution.reason_code or 'OK'}"
    else:
        profile = await ComplianceService(context.session, context.tenant).get_active_profile(business.id)
        label = "Business compliance profile"
    if profile is None:
        return result(context, parsed, label + "\nNo supported effective profile. Customer compliance continues to fail closed.")
    return result(context, parsed, f"{label}: {profile.profile_id} v{profile.version}\n"
        f"Age gate required: {profile.requires_age_gate}; minimum age: {profile.minimum_age}\n"
        f"{profile.website_attestation_notice}\nMandatory controls cannot be disabled through commands.")
