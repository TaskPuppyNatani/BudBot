"""Useful local configuration status and customer-safe preview link."""

from budbot.commands.admin.common import result, runtime, selected_location
from budbot.services.assistant_service import AssistantService
from budbot.services.business_service import BusinessService
from budbot.services.provider_service import ProviderService


async def status(context, parsed):
    business = await BusinessService(context.session).get(context.tenant, context.tenant.business_id)
    location = await selected_location(context)
    assistants = AssistantService(context.session, context.tenant)
    assistant = await assistants.resolve(business.id, location.id) if location else await assistants.get(business.id)
    lines = [f"Business: {business.display_name}", f"Assistant: {assistant.display_name}",
        f"Assistant enabled: {assistant.enabled}", f"Working location: {location.display_name if location else 'business default'}"]
    if "provider.read" in context.permission_context.permissions:
        profile = await ProviderService(context.session, context.tenant, runtime(context).settings).read()
        lines.append(f"Provider: {profile.provider or 'unconfigured'} | {profile.runtime_status} (configuration status, not a live test)")
    return result(context, parsed, "\n".join(lines))


async def preview(context, parsed):
    url = f"/widget/?business_id={context.tenant.business_id}"
    return result(context, parsed, url + "\nThe preview creates a separate customer session with normal location and age checks.", preview_url=url)
