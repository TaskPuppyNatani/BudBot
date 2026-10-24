"""Assistant enabled state uses existing business defaults/location overrides."""

from budbot.commands.admin.common import actions, result, selected_location
from budbot.core.exceptions import CommandError
from budbot.schemas.assistant import AssistantUpdate, LocationAssistantOverrideUpdate


async def set_enabled(context, parsed):
    item = await selected_location(context)
    enabled = parsed.canonical_name == "enable"
    if not enabled and item is None and parsed.arguments != ("--confirm",):
        raise CommandError("COMMAND_CONFIRMATION_REQUIRED",
            "This turns off the business's default assistant. Locations with their own setting keep it.\nTo confirm, run /disable --confirm.", status_code=409)
    if parsed.arguments and (enabled or parsed.arguments != ("--confirm",)):
        raise CommandError("COMMAND_ARGUMENT_ERROR", "Use /enable or /disable [--confirm].")
    if item:
        await actions(context).update_assistant_override(item.id, LocationAssistantOverrideUpdate(enabled=enabled))
    else:
        await actions(context).update_assistant(AssistantUpdate(enabled=enabled))
    label = f"Assistant for {item.display_name}" if item else "Business default assistant"
    note = "" if item else " Locations with their own setting keep it."
    return result(context, parsed, f"{label} is now {'on' if enabled else 'off'}.{note}")
