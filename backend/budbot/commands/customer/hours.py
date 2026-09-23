"""Customer-facing weekly-hours command."""

from datetime import time

from budbot.commands.customer.common import command_result, get_selected_location
from budbot.commands.types import CommandExecutionContext, ParsedCommand

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _format_time(value: time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


async def hours(
    context: CommandExecutionContext, parsed: ParsedCommand
):
    location = await get_selected_location(context)
    assert location is not None
    if not location.hours:
        return command_result(
            parsed, f"Weekly hours are not configured for {location.display_name}."
        )

    by_day = {entry.day_of_week: entry for entry in location.hours}
    lines = [f"Weekly hours for {location.display_name}:"]
    for day, weekday in enumerate(_WEEKDAYS):
        entry = by_day.get(day)
        if entry is None:
            details = "Hours not configured"
        elif entry.is_closed:
            details = "Closed"
        elif entry.open_time is None or entry.close_time is None:
            details = "Hours not configured"
        else:
            details = f"{_format_time(entry.open_time)}–{_format_time(entry.close_time)}"
        lines.append(f"{weekday}: {details}")
    return command_result(parsed, "\n".join(lines))
