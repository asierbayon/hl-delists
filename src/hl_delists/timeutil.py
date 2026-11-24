"""Parse the clock times Hyperliquid writes in announcements."""

from __future__ import annotations

import re
from datetime import datetime, timezone

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sept": 9,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_MONTH = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
)

DATE_RE = re.compile(
    rf"(?<![A-Za-z])(?:"
    rf"(?P<d1>\d{{1,2}})\s+(?P<m1>{_MONTH})(?:\s+(?P<y1>20\d{{2}}))?|"
    rf"(?P<m2>{_MONTH})\s+(?P<d2>\d{{1,2}})(?:,?\s+(?P<y2>20\d{{2}}))?"
    rf")(?![A-Za-z])",
    re.IGNORECASE,
)

TIME_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<min>\d{2})\s*UTC\b",
    re.IGNORECASE,
)

APPROX_RE = re.compile(r"\b(around|approximately|approx\.?)\b", re.IGNORECASE)


def parse_instant(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_instant(value: datetime) -> str:
    utc = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stated_datetime(
    phrase: str, default_year: int
) -> tuple[datetime, bool, bool] | None:
    """Return UTC time, whether the wording is approximate, and whether a year was written."""
    date_match = DATE_RE.search(phrase)
    time_match = TIME_RE.search(phrase)
    if date_match is None or time_match is None:
        return None
    if date_match.group("m1"):
        month = MONTHS[date_match.group("m1").lower()]
        day = int(date_match.group("d1"))
        year_text = date_match.group("y1")
    else:
        month = MONTHS[date_match.group("m2").lower()]
        day = int(date_match.group("d2"))
        year_text = date_match.group("y2")
    year = int(year_text) if year_text else default_year
    hour = int(time_match.group("h"))
    minute = int(time_match.group("min"))
    if hour > 23 or minute > 59 or day < 1 or day > 31:
        return None
    try:
        stated = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None
    approximate = APPROX_RE.search(phrase) is not None
    return stated, approximate, year_text is not None


def shift_if_before_announcement(stated: datetime, announced_at: datetime) -> datetime:
    """Announcements are published before the event. A missing year can land in the past."""
    if stated >= announced_at:
        return stated
    # A few hours of same-day posts (a correction the morning of the delist) stay put.
    if (announced_at - stated).total_seconds() <= 36 * 3600:
        return stated
    try:
        return stated.replace(year=stated.year + 1)
    except ValueError:
        return stated
