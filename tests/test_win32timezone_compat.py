from __future__ import annotations

from datetime import datetime, timedelta

from portkeydrop._compat import win32timezone


def test_win32timezone_compat_provides_utc_tzinfo() -> None:
    timezone = win32timezone.TimeZoneInfo.local()
    value = datetime(2026, 5, 27, tzinfo=timezone)

    assert value.utcoffset() == timedelta(0)
    assert value.tzname() == "UTC"
