"""Small UTC clock helpers used by expiring domain state."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current timezone-aware UTC instant."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize database values that may lose timezone information in SQLite."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
