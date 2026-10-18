"""Time source and timestamp formats.

* New agent/audit tables: UTC 'YYYY-MM-DDTHH:MM:SS.mmmZ' (24 chars, sortable).
* Existing tables: their established '+05:30' format 'YYYY-MM-DDTHH:MM:SS+05:30'.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def format_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    u = dt.astimezone(timezone.utc)
    return f"{u:%Y-%m-%dT%H:%M:%S}.{u.microsecond // 1000:03d}Z"


def format_existing(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def now_iso() -> str:
    return format_existing(datetime.now(IST))


def parse_utc(text: str) -> datetime:
    if len(text) != 24 or not text.endswith("Z"):
        raise ValueError(f"not a UTC timestamp: {text!r}")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


class Clock:
    def now(self) -> datetime:
        raise NotImplementedError

    def utc(self) -> str:
        return format_utc(self.now())

    def existing(self) -> str:
        return format_existing(self.now())


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock(Clock):
    """Deterministic clock for tests."""

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
