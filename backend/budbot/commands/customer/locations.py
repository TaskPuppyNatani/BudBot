"""Customer-facing location listing and session selection commands."""

from budbot.commands.customer.common import command_result
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand
from budbot.core.exceptions import CommandError
from budbot.schemas.session import SessionLocationUpdate
from budbot.services.location_service import LocationService
from budbot.services.session_service import SessionService


def _normalized_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _label(location) -> str:
    return f"{location.display_name} — {location.city}, {location.region}"


async def locations(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    service = LocationService(context.session, context.tenant)
    items = await service.list_locations()
    items.sort(key=lambda item: (item.display_name.casefold(), item.display_name, str(item.id)))
    customer_session = context.customer_session
    selected_id = customer_session.selected_location_id if customer_session else None
    if not items:
        return command_result(parsed, "No active locations are configured.")

    lines = ["Active locations:"]
    for item in items:
        marker = " (selected)" if item.id == selected_id else ""
        lines.append(f"- {_label(item)}{marker}")
    lines.append("Select or switch with /location <name>.")
    return command_result(parsed, "\n".join(lines))


async def location(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    customer_session = context.customer_session
    if customer_session is None:
        raise CommandError("COMMAND_INVALID", "a live customer session is required")
    service = LocationService(context.session, context.tenant)
    requested_name = " ".join(parsed.arguments).strip()
    if not requested_name:
        selected_id = customer_session.selected_location_id
        if selected_id is None:
            return command_result(
                parsed, "No location is selected. Use /locations, then /location <name>."
            )
        selected = await service.get(selected_id)
        if not selected.active:
            raise CommandError(
                "LOCATION_INACTIVE",
                "Your selected location is no longer active. Select another with /location <name>.",
                status_code=409,
            )
        return command_result(parsed, f"Selected location: {_label(selected)}.")

    active = await service.list_locations()
    normalized = _normalized_name(requested_name)
    matches = [
        item
        for item in active
        if _normalized_name(item.display_name) == normalized
    ]
    if not matches:
        raise CommandError(
            "LOCATION_NOT_FOUND",
            "No active location matches that name.",
            status_code=404,
        )
    if len(matches) > 1:
        raise CommandError(
            "LOCATION_AMBIGUOUS",
            "More than one active location has that name; ask the business to distinguish them.",
            status_code=409,
        )

    selected = matches[0]
    await SessionService(context.session, context.tenant).set_location(
        customer_session.id, SessionLocationUpdate(selected_location_id=selected.id)
    )
    return command_result(parsed, f"Selected location: {_label(selected)}.")
