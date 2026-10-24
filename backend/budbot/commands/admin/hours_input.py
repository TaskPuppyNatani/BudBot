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
_DAY_GROUPS = {
    "weekdays": tuple(range(5)), "weekends": (5, 6),
    "everyday": tuple(range(7)), "daily": tuple(range(7)),
}
_GROUP = re.compile(r"(?P<first>[a-z]+\.?)(?:\s*[-–]\s*(?P<last>[a-z]+\.?))?\s+(?P<hours>.+)", re.IGNORECASE)
_TIME = r"(?:noon|midnight|\d{1,2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?)"
_RANGE = re.compile(rf"(?P<open>{_TIME})(?:\s+to\s+|\s*[-–]\s*|\s+)(?P<close>{_TIME})", re.IGNORECASE)
HOURS_EXAMPLE = "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed"
HOURS_GUIDANCE = (
    "I couldn't understand those hours. Try:\n" + HOURS_EXAMPLE +
    "\nThe closing time must be later than the opening time on the same day."
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


def _days(first: str, last: str | None) -> tuple[int, ...]:
    first = first.casefold().rstrip(".")
    if last is not None:
        start, end = _DAY_INDEX[first], _DAY_INDEX[last.casefold().rstrip(".")]
        # Inclusive ranges can cross Sunday, e.g. fri-mon.
        return tuple((start + offset) % 7 for offset in range((end - start) % 7 + 1))
    return _DAY_GROUPS[first] if first in _DAY_GROUPS else (_DAY_INDEX[first],)


def parse_hours(value: str) -> tuple[LocationHoursInput, ...]:
    """Validate the entire schedule before returning any rows to the writer."""
    try:
        rows = []
        seen = set()
        for group in value.split(";"):
            match = _GROUP.fullmatch(group.strip())
            if match is None:
                raise ValueError()
            days = _days(match["first"], match["last"])
            hours = match["hours"].strip()
            closed = hours.casefold() == "closed"
            times = None if closed else _RANGE.fullmatch(hours)
            if not closed and times is None:
                raise ValueError()
            for day in days:
                if day in seen:
                    raise CommandError("COMMAND_ARGUMENT_ERROR",
                        f"{_DAYS[day][0].capitalize()} appears more than once. Include each day only once.\nTry:\n{HOURS_EXAMPLE}",
                        status_code=422)
                seen.add(day)
                rows.append(LocationHoursInput(day_of_week=day, is_closed=closed,
                    open_time=None if closed else _time(times["open"]),
                    close_time=None if closed else _time(times["close"])))
        return tuple(sorted(rows, key=lambda row: row.day_of_week))
    except (ValueError, KeyError):
        # Includes the existing model's range validation; never echo input.
        raise CommandError("COMMAND_ARGUMENT_ERROR", HOURS_GUIDANCE, status_code=422) from None
