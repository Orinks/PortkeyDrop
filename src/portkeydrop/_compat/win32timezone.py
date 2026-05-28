"""Fallback for frozen builds missing pywin32's optional win32timezone module.

PortkeyDrop does not use pywin32's Windows registry timezone helpers directly.
This module exists only so optional Windows SSH/pywin32 import paths can continue
when a frozen build does not expose pywin32's ``win32/lib`` path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo


class TimeZoneInfo(tzinfo):
    """Minimal placeholder for pywin32's TimeZoneInfo class."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        super().__init__()

    def utcoffset(self, _dt: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, _dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, _dt: datetime | None) -> str:
        return "UTC"

    @classmethod
    def local(cls) -> "TimeZoneInfo":
        return cls()


def now() -> datetime:
    """Return the current UTC time for callers that only need an aware datetime."""
    return datetime.now(UTC)
