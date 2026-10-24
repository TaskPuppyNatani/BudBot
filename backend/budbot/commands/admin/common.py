"""Helpers for authenticated commands; no customer-session or secret state."""

from pydantic import ValidationError

from budbot.commands.types import CommandResult
from budbot.core.exceptions import CommandError
from budbot.schemas.assistant import AssistantUpdate, LocationAssistantOverrideUpdate
from budbot.services.admin_actions import AdminActions
from budbot.services.assistant_service import AssistantService
from budbot.services.location_service import LocationService


def runtime(context):
    if context.admin_runtime is None or not context.permission_context.authenticated_admin:
        raise CommandError("COMMAND_PERMISSION_DENIED", "Sign in to use these commands.", status_code=403)
    return context.admin_runtime


def require_permission(context, permission):
    if permission not in context.permission_context.permissions:
        raise CommandError("COMMAND_PERMISSION_DENIED", "You do not have permission to perform this action.", status_code=403)


def result(context, parsed, output, **options):
    options.setdefault("selected_location_id", runtime(context).location_id)
    return CommandResult(parsed.canonical_name, parsed.requested_name, output, **options)


def actions(context):
    return AdminActions(context.session, context.tenant, runtime(context).user_id)


async def selected_location(context, *, required=False, for_update=False):
    location_id = runtime(context).location_id
    if location_id is None:
        if required:
            raise CommandError("COMMAND_LOCATION_REQUIRED", "Choose a location in Command location, or run /locations followed by /location Main.", status_code=409)
        return None
    return await LocationService(context.session, context.tenant).get(location_id, for_update=for_update)


async def assistant_field(context, parsed, field):
    location = await selected_location(context)
    service = AssistantService(context.session, context.tenant)
    if parsed.raw_arguments:
        require_permission(context, "assistant.write")
        try:
            schema = LocationAssistantOverrideUpdate if location else AssistantUpdate
            payload = schema.model_validate({field: parsed.raw_arguments})
        except ValidationError:
            label, limit = ("name", 200) if field == "display_name" else ("greeting", 1000)
            raise CommandError("COMMAND_ARGUMENT_ERROR", f"Please use a {label} between 1 and {limit} characters.", status_code=422) from None
        if location:
            await actions(context).update_assistant_override(location.id, payload)
        else:
            await actions(context).update_assistant(payload)
    assistant = await service.resolve(context.tenant.business_id, location.id) if location else await service.get(context.tenant.business_id)
    scope = location.display_name if location else "Business defaults"
    label = "Assistant name" if field == "display_name" else "Greeting"
    return result(context, parsed, f"{scope}\n{label}: {getattr(assistant, field)}")
