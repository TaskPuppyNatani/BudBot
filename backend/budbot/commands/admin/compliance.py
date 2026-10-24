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
        label = f"Rules for {item.display_name}"
    else:
        profile = await ComplianceService(context.session, context.tenant).get_active_profile(business.id)
        label = "Business rules"
    if profile is None:
        return result(context, parsed, label + "\nThe rules for this location could not be confirmed. Check its address and region in Locations. Customer restrictions remain in place.")
    age = f"Required ({profile.minimum_age}+)" if profile.requires_age_gate else "Not required"
    return result(context, parsed, f"{label}: {profile.jurisdiction}\nAge check: {age}\n"
        f"{profile.website_attestation_notice}\nRequired customer protections cannot be turned off with commands.")
