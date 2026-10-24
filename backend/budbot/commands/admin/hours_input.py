"""Owner-friendly hours input translated into the existing strict hours model."""

from datetime import time
import re

from budbot.core.exceptions import CommandError
from budbot.schemas.location import LocationHoursInput

_DAYS = (
    ("monday", "mon"), ("tuesday", "tue", "tues"),
    ("wednesday", "wed", "weds"), ("thursday", "thu", "thur", "thurs"),
    ("friday", "fri"), ("saturday", "sat"), ("sunday", "sun"),
)
_DAY_INDEX = {name: day for day, names in enumerate(_DAYS) for name in names}
_TIME = r"(?:noon|midnight|\d{1,2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?)"
_RANGE = re.compile(rf"(?P<open>{_TIME})(?:\s+to\s+|\s*[-–]\s*|\s+)(?P<close>{_TIME})", re.IGNORECASE)
HOURS_GUIDANCE = (
    "I couldn't understand those hours. Try:\n/set-hours monday 9am 10pm\n"
    "Or: /set-hours monday closed\nThe closing time must be later than the opening time on the same day."
)


def _time(value: str) -> time:
    value = re.sub(r"[\s.]", "", value.casefold())
    if value in {"noon", "midnight"}:
        return time(12 if value == "noon" else 0)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", value)
    if match is None:
        raise ValueError()
    hour, minute = int(match[1]), int(match[2] or 0)
    if match[3]:
        if not 1 <= hour <= 12:
            raise ValueError()
        hour = hour % 12 + (12 if match[3] == "pm" else 0)
    return time(hour, minute)


def parse_hours(value: str) -> LocationHoursInput:
    try:
        day, hours = value.strip().split(maxsplit=1)
        day_index = _DAY_INDEX[day.casefold().rstrip(".")]
        if hours.casefold() == "closed":
            return LocationHoursInput(day_of_week=day_index, is_closed=True)
        match = _RANGE.fullmatch(hours)
        if match is None:
            raise ValueError()
        return LocationHoursInput(day_of_week=day_index,
            open_time=_time(match["open"]), close_time=_time(match["close"]))
    except (ValueError, KeyError):
        # Includes the existing model's range validation; never echo input.
        raise CommandError("COMMAND_ARGUMENT_ERROR", HOURS_GUIDANCE, status_code=422) from None
