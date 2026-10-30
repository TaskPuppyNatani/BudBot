"""Bounded history rendered only from the existing sanitized read projection."""

from budbot.commands.admin.common import result
from budbot.commands.admin.display import diagnostic_label, provider_name
from budbot.core.exceptions import CommandError
from budbot.core.time import ensure_utc
from budbot.services.audit_service import AuditHistoryService
from budbot.services.location_service import LocationService

_EVENTS = {
    "admin.business.created": "Business added", "admin.business.updated": "Business settings changed",
    "admin.location.created": "Location added", "admin.location.updated": "Location settings changed",
    "admin.location.deactivated": "Location turned off", "admin.assistant.updated": "Assistant settings changed",
    "admin.assistant.location_override.updated": "Location assistant settings changed",
    "admin.faq.created": "FAQ added", "admin.faq.updated": "FAQ changed",
    "admin.faq.deleted": "FAQ deleted",
    "admin.branding.saved": "Branding saved", "admin.compliance_profile.updated": "Business rules changed",
    "admin.provider.configuration_updated": "AI provider settings changed",
    "admin.provider.credential_set": "AI key saved", "admin.provider.credential_replaced": "AI key replaced",
    "admin.provider.credential_removed": "AI key removed and AI turned off",
    "admin.provider.connection_tested": "AI connection checked",
    "admin.local_runtime.shutdown_requested": "BudBot shutdown requested",
}
_FIELDS = {
    "display_name": "name", "legal_name": "legal name", "industry": "business type",
    "website_url": "website", "main_phone": "phone", "default_timezone": "time zone",
    "payment_methods": "payment methods", "store_policies": "store policies", "active": "active setting",
    "directions_enabled": "directions", "faq_enabled": "FAQs", "payments_info_enabled": "payment information",
    "policies_info_enabled": "policy information", "products_enabled": "products", "promotions_enabled": "deals",
    "address_line_1": "address", "address_line_2": "address", "city": "city", "region": "region",
    "region_code": "region", "postal_code": "postal code", "country": "country", "phone": "phone",
    "timezone": "time zone", "maps_place_id": "map location", "maps_destination": "map destination",
    "hours": "hours", "greeting": "greeting", "fallback_message": "help message",
    "avatar_reference": "assistant picture", "primary_color_override": "color", "enabled": "on/off setting",
    "question": "question", "answer": "answer", "location_id": "location", "is_public": "customer visibility",
    "primary_brand_color": "brand color", "assistant_display_name": "assistant name",
    "business_logo": "business logo", "assistant_avatar": "assistant picture",
    "remove_business_logo": "business logo", "remove_assistant_avatar": "assistant picture",
}


def _details(event, locations):
    # Input is already the restricted AuditHistoryService projection. Unknown
    # fields/values still have no free-form fallback in this presentation layer.
    details = event.details
    parts = []
    fields = sorted({_FIELDS[name] for name in details.get("changed_fields", "").split(",") if name in _FIELDS})
    if fields:
        parts.append("Changed: " + ", ".join(fields))
    if "location_id" in details:
        parts.append("For: " + (locations.get(details["location_id"], "Location no longer listed") if details["location_id"] else "All locations"))
    if "enabled" in details:
        parts.append("On" if details["enabled"] else "Off")
    if "is_public" in details:
        parts.append("Visible to customers" if details["is_public"] else "Hidden from customers")
    if "provider" in details:
        parts.append(provider_name(details["provider"]))
    if "diagnostic_code" in details:
        parts.append(diagnostic_label(details["diagnostic_code"]))
    if "success" in details:
        parts.append("Successful" if details["success"] else "Failed")
    return "; ".join(parts)


async def audit(context, parsed):
    try:
        limit = int(parsed.raw_arguments) if parsed.raw_arguments else 10
        if not 1 <= limit <= 50:
            raise ValueError()
    except ValueError:
        raise CommandError("COMMAND_ARGUMENT_ERROR", "Use /audit [1-50].") from None
    history = await AuditHistoryService(context.session, context.tenant).list_events(limit=limit, offset=0)
    locations = {str(item.id): item.display_name for item in await LocationService(context.session, context.tenant).list_locations(include_inactive=True)}
    lines = [f"{ensure_utc(event.created_at).strftime('%Y-%m-%d %H:%M UTC')} — {_EVENTS.get(event.event_type, 'Settings updated')}\n{_details(event, locations)}".rstrip() for event in history.items]
    return result(context, parsed, "\n".join(lines) or "No audit events for this business.")
