"""Trip-date and flight-time rules shared by search, sessions and offer validation.

* Trip dates travel as ISO date-only strings (YYYY-MM-DD) and are parsed with
  `date.fromisoformat` -- never through a datetime/UTC conversion -- so the calendar day the
  traveller picked is the day that is checked and stored.
* "Today" is the local date in IST, the timezone every timestamp in the dataset uses.
* Flights are compared as instants (their stored `+05:30` timestamps), and shown in each
  airport's own timezone. A flight that lands after local midnight is valid: only an arrival
  instant at or before the departure instant is not.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.clock import IST, Clock

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def local_today(clock: Clock) -> date:
    return clock.now().astimezone(IST).date()


def parse_date_only(value: object) -> date:
    """A strict YYYY-MM-DD calendar date; anything with a time or offset is refused."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not _DATE_ONLY.match(value):
        raise ValueError(f"{value!r} is not a YYYY-MM-DD date")
    return date.fromisoformat(value)


def date_order_error(start: Optional[date], end: Optional[date], *,
                     start_label: str, end_label: str) -> Optional[str]:
    """The trip's end must be at least one day after its start (one night for a stay)."""
    if start is not None and end is not None and end <= start:
        return f"{end_label} {end.isoformat()} must be after {start_label} {start.isoformat()}"
    return None


def past_date_error(start: Optional[date], today: date, *, label: str) -> Optional[str]:
    if start is not None and start < today:
        return f"{label} {start.isoformat()} is in the past (today is {today.isoformat()})"
    return None


def parse_instant(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError(f"timestamp without an offset: {value!r}")
    return moment


def _in_zone(moment: datetime, tz_name: Optional[str]) -> datetime:
    try:
        return moment.astimezone(ZoneInfo(tz_name)) if tz_name else moment
    except (KeyError, ValueError):  # unknown zone name: keep the stored offset
        return moment


def flight_times(departs_at: str, arrives_at: str, origin_tz: Optional[str],
                 dest_tz: Optional[str]) -> dict:
    """Local departure/arrival at each airport, how many local calendar days later the flight
    lands (0 = same day, 1 = after midnight), and whether arrival is after departure."""
    dep, arr = parse_instant(departs_at), parse_instant(arrives_at)
    dep_local, arr_local = _in_zone(dep, origin_tz), _in_zone(arr, dest_tz)
    return {
        "departsAtLocal": dep_local.isoformat(timespec="seconds"),
        "arrivesAtLocal": arr_local.isoformat(timespec="seconds"),
        "arrivalDayOffset": (arr_local.date() - dep_local.date()).days,
        "arrivesAfterDeparture": arr > dep,
    }


def has_departed(departs_at: str, now: datetime) -> bool:
    return parse_instant(departs_at) <= now
