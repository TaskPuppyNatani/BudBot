"""Administrative working location and structured weekly-hours convenience."""

from budbot.commands.admin.common import actions, result, selected_location, structured_input
from budbot.commands.customer.hours import format_hours
from budbot.core.exceptions import CommandError
from budbot.schemas.location import LocationUpdate
from budbot.services.location_service import LocationService


async def locations(context, parsed):
    items = await LocationService(context.session, context.tenant).list_locations(include_inactive=True)
    lines = [f"{item.display_name} | {item.id} | {'active' if item.active else 'inactive'}" for item in items[:50]]
    if len(items) > 50:
        lines.append("More locations are available in the dashboard.")
    return result(context, parsed, "\n".join(lines) or "No locations are configured.")


async def location(context, parsed):
    name = parsed.raw_arguments
    if name == "--business":
        return result(context, parsed, "Business default scope selected.", selected_location_id=None)
    if not name:
        item = await selected_location(context)
        return result(context, parsed, f"Working location: {item.display_name} | {item.id}" if item else "Business default scope. Select with /location <name or UUID>.")
    items = await LocationService(context.session, context.tenant).list_locations(include_inactive=True)
    normalized = " ".join(name.casefold().split())
    matches = [item for item in items if str(item.id) == name]
    if not matches:
        matches = [item for item in items if " ".join(item.display_name.casefold().split()) == normalized]
    if not matches:
        raise CommandError("LOCATION_NOT_FOUND", "No location matches in this business.", status_code=404)
    if len(matches) != 1:
        raise CommandError("LOCATION_AMBIGUOUS", "More than one location matches. Use its UUID from /locations.", status_code=409)
    item = matches[0]
    return result(context, parsed, f"Working location: {item.display_name} | {item.id}", selected_location_id=item.id)


async def hours(context, parsed):
    return result(context, parsed, format_hours(await selected_location(context, required=True)))


async def set_hours(context, parsed):
    item = await selected_location(context, required=True)
    payload = structured_input(parsed, LocationUpdate, allowed={"hours"}, required={"hours"})
    item = await actions(context).update_location(item.id, payload)
    return result(context, parsed, format_hours(item))
