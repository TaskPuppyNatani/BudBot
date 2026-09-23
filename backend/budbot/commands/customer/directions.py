"""Address-based directions command with a fixed, safely encoded maps link."""

from urllib.parse import quote

from budbot.commands.customer.common import command_result, get_selected_location
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand
from budbot.core.exceptions import CommandError
from budbot.services.customer_information_service import CustomerInformationService


async def directions(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    location = await get_selected_location(context)
    assert location is not None
    contact = await CustomerInformationService(
        context.session, context.tenant
    ).resolve_contact(location)
    if not contact.address:
        raise CommandError(
            "INFORMATION_NOT_CONFIGURED",
            "Directions are unavailable because this location has no configured address.",
            status_code=409,
        )
    maps_url = "https://www.google.com/maps/dir/?api=1&destination=" + quote(
        contact.address, safe=""
    )
    return command_result(
        parsed, f"Directions to {location.display_name}: {contact.address}\n{maps_url}"
    )
