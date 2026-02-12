import datetime as dt
from zoneinfo import ZoneInfo

from loguru import logger


def date_to_us_long(date: dt.date) -> str:
    """Convert ``date(2026, 3, 22)`` → ``March 22, 2026`` for Healthie's date input."""
    return f"{date.strftime('%B')} {date.day}, {date.year}"


def time_to_12h(time: dt.time) -> str:
    """Convert ``time(14, 30)`` → ``2:30 PM`` for Healthie's time picker.

    Healthie's dropdown uses no leading zero on the hour (``3:30 PM``
    not ``03:30 PM``).
    """
    hour = time.hour % 12 or 12
    period = "AM" if time.hour < 12 else "PM"
    return f"{hour}:{time.strftime('%M')} {period}"


def resolve_timezone(name: str) -> dt.tzinfo:
    """Resolve a timezone name, falling back to UTC if invalid."""
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning("Invalid clinic timezone '{}'; defaulting to UTC", name)
        return dt.timezone.utc
