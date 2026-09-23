"""Shared helpers for deterministic M5 customer commands."""

from budbot.commands.types import (
    CommandExecutionContext,
    CommandResult,
    ParsedCommand,
)
from budbot.core.exceptions import CommandError
from budbot.models.location import Location
from budbot.services.location_service import LocationService


async def get_selected_location(
    context: CommandExecutionContext, *, required: bool = True
) -> Location | None:
    customer_session = context.customer_session
    if customer_session is None:
        raise CommandError("COMMAND_INVALID", "a live customer session is required")
    location_id = customer_session.selected_location_id
    if location_id is None:
        if not required:
            return None
        raise CommandError(
            "LOCATION_REQUIRED",
            "Select a location with /location <name>. Use /locations to see active locations.",
            status_code=409,
        )
    location = await LocationService(context.session, context.tenant).get(location_id)
    if not location.active:
        if not required:
            return None
        raise CommandError(
            "LOCATION_INACTIVE",
            "Your selected location is no longer active. Select another with /location <name>.",
            status_code=409,
        )
    return location


def command_result(parsed: ParsedCommand, output: str) -> CommandResult:
    return CommandResult(parsed.canonical_name, parsed.requested_name, output)
