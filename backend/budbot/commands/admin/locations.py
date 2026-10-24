"""Location names and friendly one-day edits through strict weekly-hours models."""

from collections import Counter

from pydantic import ValidationError

from budbot.commands.admin.common import actions, result, runtime, selected_location
from budbot.commands.admin.hours_input import parse_hours
from budbot.commands.customer.hours import format_hours
from budbot.core.exceptions import CommandError
from budbot.schemas.location import LocationHoursInput, LocationUpdate
from budbot.services.location_service import LocationService


async def locations(context, parsed):
    items = await LocationService(context.session, context.tenant).list_locations(include_inactive=True)
    counts = Counter(" ".join(item.display_name.casefold().split()) for item in items)
    lines = []
    for item in items[:50]:
        label = f"{item.display_name} — {'Active' if item.active else 'Inactive'}"
        if item.id == runtime(context).location_id:
            label += " (selected)"
        if counts[" ".join(item.display_name.casefold().split())] > 1:
            label += f" — {item.address_line_1}, {item.city}\n  Selection ID for duplicate names: /location {item.id}"
        lines.append(label)
    if len(items) > 50:
        lines.append("More locations are available in the dashboard.")
    return result(context, parsed, "\n".join(lines) or "No locations are configured.")


async def location(context, parsed):
    name = parsed.raw_arguments
    if name == "--business":
        return result(context, parsed, "Business defaults selected.", selected_location_id=None)
    if not name:
        item = await selected_location(context)
        return result(context, parsed, f"Selected location: {item.display_name} — {'Active' if item.active else 'Inactive'}" if item else "Business defaults selected. Choose a location from the menu, or use /location Main.")
    items = await LocationService(context.session, context.tenant).list_locations(include_inactive=True)
    normalized = " ".join(name.casefold().split())
    matches = [item for item in items if str(item.id) == name]
    if not matches:
        matches = [item for item in items if " ".join(item.display_name.casefold().split()) == normalized]
    if not matches:
        raise CommandError("LOCATION_NOT_FOUND", "I couldn't find that location. Run /locations and use one of the listed names.", status_code=404)
    if len(matches) != 1:
        raise CommandError("LOCATION_AMBIGUOUS", "More than one location has that name. Choose it from the Command location menu, or run /locations for their addresses and selection IDs.", status_code=409)
    item = matches[0]
    return result(context, parsed, f"Selected location: {item.display_name} — {'Active' if item.active else 'Inactive'}", selected_location_id=item.id)


async def hours(context, parsed):
    return result(context, parsed, format_hours(await selected_location(context, required=True)))


async def set_hours(context, parsed):
    row = parse_hours(parsed.raw_arguments)
    # The existing row lock/populate_existing read keeps other days current
    # before merging. The audited action still uses LocationService.update.
    item = await selected_location(context, required=True, for_update=True)
    try:
        hours = [LocationHoursInput.model_validate(entry) for entry in item.hours if entry.day_of_week != row.day_of_week]
        payload = LocationUpdate(hours=sorted([*hours, row], key=lambda entry: entry.day_of_week))
    except ValidationError:
        raise CommandError("COMMAND_ARGUMENT_ERROR", "Some saved hours need attention. Open Locations to review the weekly schedule before trying again.", status_code=422) from None
    item = await actions(context).update_location(item.id, payload)
    return result(context, parsed, format_hours(item))
