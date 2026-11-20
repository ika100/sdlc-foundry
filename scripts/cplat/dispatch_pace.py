"""Spec 210: the dispatcher's plan-mode pace (design.md "Plan state"). A pure decision from the usage files and the policy.

  pace(policy, now, readings=None, tape=None, limit=None) -> Pace   the windows, their source, the hold, the band, the filler window
  doc(pace, policy) -> dict                 the `plan` object of `plan --json` and `status --json`
  fmt_pct(x) -> str                         a percentage without a trailing `.0` (83 -> `83`, 43.5 -> `43.5`)
  fmt_when(when, now) -> str                `%H:%M` on today's date, else `<Mon> %H:%M`
  Pace, Window                              the result types; `Pace.week_pace` is the weekly pace in percent
  STALE_SECONDS, FILLER_SECONDS             a reading older than 30 minutes is estimated; the filler window is the last 24 hours

The inputs default to `usage_readings.readings()`, `usage_readings.booked_between` and `usage_readings.limit()`, so tests pass
fixtures. A window is estimated from its newest reading plus the tokens booked since, at the tokens per point of the last
7 days. Without such a calibration the window is unknown. Times are Unix seconds inside, ISO local strings in the result.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass, field
from typing import Callable

import dispatch_policy as dp
import usage_readings as ur

STALE_SECONDS = 30 * 60
FILLER_SECONDS = 24 * 3600
WEEK_SECONDS = 7 * 86400
HISTORY_SECONDS = 7 * 86400
SPAN = {"five_hour": 5 * 3600, "seven_day": WEEK_SECONDS}
PAIR_RESET_TOLERANCE = 60
NEAR_PACE_POINTS = 5.0
UNKNOWN_TEXT = "plan usage unknown (install the sensor and open an interactive session)"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Window:
    used: float | None = None
    resets_at: str | None = None
    stale: bool = False
    estimated: bool = False


@dataclass
class Pace:
    source: str = "unknown"
    read_at: str | None = None
    five_hour: Window = field(default_factory=Window)
    seven_day: Window = field(default_factory=Window)
    filler: bool = False
    hold: tuple[str, str] | None = None
    max_running: int | None = None
    limit_until: str | None = None
    week_pace: float | None = None


def fmt_pct(x: float) -> str:
    return f"{round(x, 1):g}"


def fmt_when(when: dt.datetime, now: dt.datetime) -> str:
    clock = when.strftime("%H:%M")
    return clock if when.date() == now.date() else f"{DAYS[when.weekday()]} {clock}"


def _iso(epoch: float | None) -> str | None:
    return None if epoch is None else dt.datetime.fromtimestamp(epoch).isoformat(timespec="seconds")


def _point(raw) -> dict | None:
    try:
        return {"at": float(raw["at"]), "used": float(raw["used"]), "resets_at": float(raw["resets_at"])}
    except (KeyError, TypeError, ValueError):
        return None


def _tape_sum(tape: Callable[[float, float], int], t0: float, t1: float) -> int:
    """Tokens booked with t0 < at <= t1."""
    return tape(math.nextafter(t0, math.inf), math.nextafter(t1, math.inf))


def _tokens_per_point(history: list[dict], now: float, tape: Callable[[float, float], int]) -> float | None:
    rates = []
    pts = [p for p in history if p["at"] >= now - HISTORY_SECONDS]
    for a, b in zip(pts, pts[1:]):
        if abs(a["resets_at"] - b["resets_at"]) > PAIR_RESET_TOLERANCE or b["used"] <= a["used"]:
            continue
        booked = _tape_sum(tape, a["at"], b["at"])
        if booked > 0:
            rates.append(booked / (b["used"] - a["used"]))
    return statistics.median(rates) if rates else None


def _window(name: str, raw, now: float, tape) -> tuple[Window, float | None, float | None]:
    """(window, resets_at epoch, last.at epoch); `used` None when there is no reading or no calibration."""
    raw = raw if isinstance(raw, dict) else {}
    last = _point(raw.get("last"))
    if last is None:
        return Window(), None, None
    if now - last["at"] <= STALE_SECONDS and now < last["resets_at"]:
        return Window(last["used"], _iso(last["resets_at"])), last["resets_at"], last["at"]
    resets = last["resets_at"]
    base, since = last["used"], last["at"]
    if now >= resets:
        base, since = 0.0, resets
        resets = since + SPAN[name]
        while resets <= now:
            resets += SPAN[name]
    history = [p for p in map(_point, raw.get("history") or []) if p]
    tpp = _tokens_per_point(history, now, tape)
    used = None if tpp is None else base + _tape_sum(tape, since, now) / tpp
    return Window(used, _iso(resets), stale=True, estimated=True), resets, last["at"]


def _plan(policy: dp.Policy) -> dict:
    return policy.values.get("budget", {}).get("plan") or dp.PLAN_DEFAULTS


def _week_pace(policy: dp.Policy, now: float, seven_resets: float | None) -> float | None:
    if seven_resets is None:
        return None
    elapsed = min(1.0, max(0.0, (now - (seven_resets - WEEK_SECONDS)) / WEEK_SECONDS))
    return _plan(policy)["weekly_target"] * elapsed * 100


def _hold(policy: dp.Policy, now: float, five: Window, seven: Window, week_pace: float | None,
          limit: dict | None) -> tuple[str, str] | None:
    plan = _plan(policy)
    if limit is not None and float(limit["until"]) > now:
        until = fmt_when(dt.datetime.fromtimestamp(float(limit["until"])), dt.datetime.fromtimestamp(now))
        return "usage limit", f"usage limit until {until}"
    if five.used is None or seven.used is None:
        return "plan usage unknown", UNKNOWN_TEXT
    stop = round(plan["window_stop"] * 100, 9)
    if five.used >= stop:
        return "plan window", f"plan-window {fmt_pct(five.used)} % ≥ {fmt_pct(stop)} %"
    if seven.used >= round(plan["weekly_target"] * 100, 9):
        return "weekly target reached", "weekly target reached"
    if week_pace is not None and seven.used > week_pace:
        return "ahead of weekly pace", f"ahead of weekly pace ({fmt_pct(seven.used)} % used, pace {fmt_pct(week_pace)} %)"
    return None


def pace(policy: dp.Policy, now: dt.datetime, readings: dict | None = None, tape: Callable[[float, float], int] | None = None,
         limit: dict | None = None) -> Pace:
    readings = ur.readings() if readings is None else readings
    tape = ur.booked_between if tape is None else tape
    limit = ur.limit() if limit is None else limit
    at = now.timestamp()
    five, _, five_read = _window("five_hour", readings.get("five_hour"), at, tape)
    seven, seven_resets, seven_read = _window("seven_day", readings.get("seven_day"), at, tape)
    week_pace = _week_pace(policy, at, seven_resets)
    hold = _hold(policy, at, five, seven, week_pace, limit)
    reads = [r for r in (five_read, seven_read) if r is not None]
    if hold is not None and hold[0] == "usage limit":
        source = "limit"
    elif hold is not None and hold[0] == "plan usage unknown":
        source = "unknown"
    else:
        source = "estimate" if five.estimated or seven.estimated else "reading"
    near = week_pace is not None and seven.used is not None and week_pace - seven.used <= NEAR_PACE_POINTS
    return Pace(
        source=source, read_at=_iso(min(reads)) if reads else None, five_hour=five, seven_day=seven,
        filler=hold is None and seven_resets is not None and seven_resets - at <= FILLER_SECONDS,
        hold=hold, max_running=1 if hold is None and near else None,
        limit_until=_iso(float(limit["until"])) if limit is not None and float(limit["until"]) > at else None,
        week_pace=week_pace)


def doc(p: Pace, policy: dp.Policy) -> dict:
    plan = _plan(policy)

    def used(w: Window) -> float | None:
        return None if w.used is None else round(w.used, 1)

    return {
        "source": p.source, "read_at": p.read_at,
        "five_hour": {"used": used(p.five_hour), "resets_at": p.five_hour.resets_at, "stop": round(plan["window_stop"] * 100, 9)},
        "seven_day": {"used": used(p.seven_day), "resets_at": p.seven_day.resets_at,
                      "pace": None if p.week_pace is None else round(p.week_pace, 1),
                      "target": round(plan["weekly_target"] * 100, 9)},
        "filler": p.filler, "hold": p.hold[1] if p.hold else None, "max_running": p.max_running, "limit_until": p.limit_until}
