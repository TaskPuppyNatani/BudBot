"""Common owner input forms, strict time boundaries, and safe display coverage."""

from datetime import time

import pytest

from budbot.commands.admin.display import DIAGNOSTIC_GUIDANCE, DIAGNOSTIC_LABELS, diagnostic_message
from budbot.commands.admin.hours_input import parse_hours
from budbot.core.exceptions import CommandError
from budbot.schemas.provider import ProviderDiagnosticCode as Code


@pytest.mark.parametrize("value,day,opens,closes", [
    ("monday 9am 10pm", 0, time(9), time(22)),
    ("MON 09:00 22:00", 0, time(9), time(22)),
    ("tues 9:30 AM 10:15 PM", 1, time(9, 30), time(22, 15)),
    ("Wed. 09:30-17:45", 2, time(9, 30), time(17, 45)),
    ("thurs noon to 10pm", 3, time(12), time(22)),
    ("Fri 12am 12pm", 4, time(0), time(12)),
    ("sat midnight noon", 5, time(0), time(12)),
    ("Sunday 9 a.m. 5 p.m.", 6, time(9), time(17)),
    ("thu 9 17", 3, time(9), time(17)),
    ("tue 12pm 11:59pm", 1, time(12), time(23, 59)),
])
def test_common_day_and_time_forms(value, day, opens, closes):
    row, = parse_hours(value)
    assert (row.day_of_week, row.open_time, row.close_time, row.is_closed) == (day, opens, closes, False)


@pytest.mark.parametrize("day,index", [("Mon", 0), ("Tuesday", 1), ("Weds", 2), ("Thur.", 3), ("Friday", 4), ("Saturday", 5), ("Sun", 6)])
def test_closed_days_have_no_times(day, index):
    row, = parse_hours(day + " CLOSED")
    assert row.day_of_week == index and row.is_closed
    assert row.open_time is None and row.close_time is None


@pytest.mark.parametrize("value", ["", "monday", "0 09:00 17:00", "monday 9am", "monday 13pm 15pm",
    "monday 00am 9am", "monday 9:60am 5pm", "monday 9:5am 5pm", "monday 24:00 25:00",
    "monday 10pm 2am", "monday 9am 9am", "monday closed extra", 'monday {"hours":[]}',
    "private-input-marker 9am 5pm"])
def test_invalid_hours_keep_existing_policy_and_give_examples(value):
    with pytest.raises(CommandError) as failure:
        parse_hours(value)
    assert failure.value.status_code == 422
    assert "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed" in failure.value.detail
    assert "private-input-marker" not in failure.value.detail


@pytest.mark.parametrize("days,expected", [
    ("mon-fri", range(5)), ("monday-friday", range(5)), ("weekdays", range(5)),
    ("weekends", (5, 6)), ("everyday", range(7)), ("daily", range(7)),
    ("Tues - Thurs", (1, 2, 3)), ("fri-mon", (0, 4, 5, 6)),
])
@pytest.mark.parametrize("hours,closed", [("9 am-9 pm", False), ("closed", True)])
def test_grouped_days_and_ranges(days, expected, hours, closed):
    rows = parse_hours(days + " " + hours)
    assert [row.day_of_week for row in rows] == list(expected)
    assert all(row.is_closed == closed for row in rows)
    assert all((row.open_time, row.close_time) == ((None, None) if closed else (time(9), time(21))) for row in rows)


def test_mixed_full_week_is_validated_into_strict_rows():
    rows = parse_hours("mon-fri 9am-9pm; sat 10am-8pm; sun closed")
    assert [row.day_of_week for row in rows] == list(range(7))
    assert all((row.open_time, row.close_time) == (time(9), time(21)) for row in rows[:5])
    assert (rows[5].open_time, rows[5].close_time) == (time(10), time(20))
    assert rows[6].is_closed


@pytest.mark.parametrize("value,day", [
    ("mon-fri 9am-9pm; fri closed", "Friday"),
    ("weekdays closed; monday 9am-5pm", "Monday"),
    ("daily closed; weekends closed", "Saturday"),
    ("sun closed; sunday closed", "Sunday"),
])
def test_overlapping_groups_explain_which_day_is_duplicated(value, day):
    with pytest.raises(CommandError) as failure:
        parse_hours(value)
    assert failure.value.status_code == 422
    assert day + " appears more than once. Include each day only once." in failure.value.detail
    assert "day_of_week" not in failure.value.detail


@pytest.mark.parametrize("value", [
    "mon-fri 9am-9pm; sat 10am-25:00", "weekdays 9am-9pm; sun private-input-marker",
    "weekdays-friday closed", "mon-fri closed;", "mon closed;;sun closed",
])
def test_invalid_group_rejects_the_whole_schedule_with_safe_guidance(value):
    with pytest.raises(CommandError) as failure:
        parse_hours(value)
    assert failure.value.status_code == 422
    assert "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed" in failure.value.detail
    assert not any(marker in failure.value.detail for marker in ("private-input-marker", "LocationUpdate", "day_of_week", "Traceback"))


def test_every_diagnostic_has_owner_facing_text_and_no_code_fallback():
    assert set(DIAGNOSTIC_LABELS) == set(DIAGNOSTIC_GUIDANCE) == set(Code)
    for code in Code:
        assert code.value not in diagnostic_message(code)
        assert "AI_" not in diagnostic_message(code)
    assert "private-code-marker" not in diagnostic_message("private-code-marker")
