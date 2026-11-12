"""Spec 184: tell from a finished session whether it hit the usage limit, when it resets and how long the run waits.

  detect(output, seconds, ended) -> Hit | None   the last non-empty line is the limit message, or the session was silent and short
  Pauser().pause(hit, now) -> Pause              the wait before the next session, or `stop` once the pauses would pass the cap
  Pauser().resumed()                             a session that was no pause: the backoff starts again at 5 minutes

No I/O and no sleeping here: the drivers (headless, ship) print the line and sleep.
"""
from __future__ import annotations

import datetime
import re
import zoneinfo
from dataclasses import dataclass

QUICK_SECONDS = 60
BACKOFF_MINUTES = (5, 10, 20, 40, 60)
CAP_MINUTES = 360
GRACE_SECONDS = 60
STOP_PREFIX = "environment pause: usage limit resets at "

_TIME_FORMAT = "%Y-%m-%d %H:%M"
_MESSAGE = re.compile(r"usage limit|limit reached|hit your .*limit", re.IGNORECASE)
_UNIX = re.compile(r"\|\s*(\d{9,11})\s*$")
_RESETS = re.compile(
    r"resets\s+(?:at\s+)?(?:([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s+(?:at\s+)?)?"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?",
    re.IGNORECASE,
)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


@dataclass(frozen=True)
class Hit:
    reset: datetime.datetime | None


@dataclass(frozen=True)
class Pause:
    seconds: float
    line: str
    stop: str | None


def _zone(name: str | None) -> zoneinfo.ZoneInfo | None:
    if not name:
        return None
    try:
        return zoneinfo.ZoneInfo(name.strip())
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _resets(match: re.Match[str], ended: datetime.datetime) -> datetime.datetime | None:
    month, day, hour_text, minute_text, meridiem, zone_name = match.groups()
    hour, minute = int(hour_text), int(minute_text or 0)
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    zone = _zone(zone_name)
    if zone is not None:
        base = ended.astimezone().astimezone(zone).replace(tzinfo=None)
    else:
        base = ended
    try:
        if month:
            if month.lower() not in _MONTHS:
                return None
            number = _MONTHS.index(month.lower()) + 1
            moment = datetime.datetime(base.year, number, int(day), hour, minute)
            if moment < base:
                moment = moment.replace(year=base.year + 1)
        else:
            moment = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if moment < base:
                moment += datetime.timedelta(days=1)
    except ValueError:
        return None
    if zone is not None:
        return moment.replace(tzinfo=zone).astimezone().replace(tzinfo=None)
    return moment


def detect(output: str, seconds: float, ended: datetime.datetime) -> Hit | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return Hit(reset=None) if seconds < QUICK_SECONDS else None
    last = lines[-1]
    if not _MESSAGE.search(last):
        return None
    unix = _UNIX.search(last)
    if unix:
        try:
            return Hit(reset=datetime.datetime.fromtimestamp(int(unix.group(1))))
        except (OverflowError, OSError, ValueError):
            return Hit(reset=None)
    match = _RESETS.search(last)
    return Hit(reset=_resets(match, ended) if match else None)


class Pauser:
    """One per run: the pauses so far and the backoff position."""

    def __init__(self) -> None:
        self.total_seconds: float = 0.0
        self._tries = 0

    def pause(self, hit: Hit, now: datetime.datetime) -> Pause:
        if hit.reset is not None:
            wait = max(0.0, (hit.reset - now).total_seconds() + GRACE_SECONDS)
        else:
            wait = float(BACKOFF_MINUTES[min(self._tries, len(BACKOFF_MINUTES) - 1)] * 60)
        if self.total_seconds + wait > CAP_MINUTES * 60:
            when = hit.reset.strftime(_TIME_FORMAT) if hit.reset is not None else "unknown"
            return Pause(seconds=0, line="", stop=STOP_PREFIX + when)
        self.total_seconds += wait
        resume = now + datetime.timedelta(seconds=wait)
        if hit.reset is not None:
            line = f"paused: usage limit, resumes at {(hit.reset + datetime.timedelta(seconds=GRACE_SECONDS)):{_TIME_FORMAT}}"
        else:
            self._tries += 1
            line = f"paused: usage limit, next try at {resume:{_TIME_FORMAT}}"
        return Pause(seconds=wait, line=line, stop=None)

    def resumed(self) -> None:
        self._tries = 0
