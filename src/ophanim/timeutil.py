"""Time-zone helpers.

OPHANIM uses fixed UTC offsets (e.g. "+05:00", "+05:30", "-05:00") instead of
IANA zone names. That removes daylight-saving ambiguity and any dependency on the
operating system's tz database, which differs between Windows and Linux images.
This is a documented simplification (docs/design_note.md, limitations).

All timestamps are ISO-8601 with an explicit offset. The accounting date of a
document is its *local calendar date in the company's offset*.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def parse_offset(text: str) -> timezone:
    m = _OFFSET_RE.match(text)
    if not m:
        raise ValueError(f"invalid UTC offset: {text!r}")
    sign = 1 if m.group(1) == "+" else -1
    hours, minutes = int(m.group(2)), int(m.group(3))
    if hours > 14 or minutes >= 60:
        raise ValueError(f"invalid UTC offset: {text!r}")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def offset_minutes_to_str(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    m = abs(minutes)
    return f"{sign}{m // 60:02d}:{m % 60:02d}"


def tz_from_minutes(minutes: int) -> timezone:
    return timezone(timedelta(minutes=minutes))


def format_ts(moment: datetime, offset_minutes: int) -> str:
    """Render an aware datetime in the given offset with second precision."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime")
    return moment.astimezone(tz_from_minutes(offset_minutes)).replace(microsecond=0).isoformat()


def parse_ts(text: str) -> datetime:
    """Parse ISO-8601 that must carry an explicit offset."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"timestamp without UTC offset: {text!r}")
    return moment


def local_date(moment: datetime, offset_minutes: int) -> date:
    return moment.astimezone(tz_from_minutes(offset_minutes)).date()


def local_datetime(day: date, hour: int, minute: int, second: int, offset_minutes: int) -> datetime:
    """Aware datetime for a local wall-clock time in the given offset."""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=tz_from_minutes(offset_minutes))
