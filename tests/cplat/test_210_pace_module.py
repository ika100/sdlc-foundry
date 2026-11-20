"""Module-level tests of dispatch_pace (spec 210, task t5): windows, estimate, calibration, limit hold, bands, filler window."""
import datetime as dt

import pytest

import dispatch_pace as dpace
from dispatch_policy import PLAN_DEFAULTS, Policy

NOW = dt.datetime(2026, 11, 18, 12, 0, 0)       # a Wednesday
H, D = 3600, 86400


def _policy(**plan):
    return Policy(values={"budget": {"mode": "plan", "plan": {**PLAN_DEFAULTS, **plan}}})


def _t(offset_seconds):
    return NOW.timestamp() + offset_seconds


def _pt(at, used, resets):
    return {"at": at, "used": used, "resets_at": resets}


def _win(last, history=None):
    return {"last": last, "history": history if history is not None else [last]}


def _fresh(five, week, elapsed=0.5):
    at = _t(-240)
    return {"five_hour": _win(_pt(at, five, _t(3 * H))), "seven_day": _win(_pt(at, week, _t(7 * D * (1 - elapsed))))}


def _pace(readings, tape=None, limit=None, policy=None):
    return dpace.pace(policy or _policy(), NOW, readings=readings, tape=tape or (lambda a, b: 0), limit=limit or {"until": 0})


def test_window_stop_holds_at_the_stop_and_not_below():
    held = _pace(_fresh(83, 30))
    assert held.hold == ("plan window", "plan-window 83 % ≥ 80 %") and held.source == "reading" and held.max_running is None
    assert _pace(_fresh(79, 30)).hold is None


def test_weekly_bands_at_half_the_week():
    assert _pace(_fresh(10, 30)).max_running is None
    near = _pace(_fresh(10, 43))
    assert near.hold is None and near.max_running == 1 and near.week_pace == pytest.approx(46.0)
    assert _pace(_fresh(10, 50)).hold == ("ahead of weekly pace", "ahead of weekly pace (50 % used, pace 46 %)")
    assert _pace(_fresh(10, 92)).hold == ("weekly target reached", "weekly target reached")


def test_policy_values_move_the_thresholds():
    p = _policy(window_stop=0.6, weekly_target=0.5)
    assert _pace(_fresh(61, 10), policy=p).hold[1] == "plan-window 61 % ≥ 60 %"
    assert _pace(_fresh(10, 50), policy=p).hold[1] == "weekly target reached"


def test_estimate_from_a_calibrated_stale_reading():
    t10, t11 = _t(-2 * H), _t(-1 * H)
    resets5, resets7 = _t(2 * H), _t(3.5 * D)
    rows = [(t10 + 1800, 20_000_000), (t11 + 1800, 15_000_000)]
    readings = {"five_hour": _win(_pt(t11, 12, resets5), [_pt(t10, 10, resets5), _pt(t11, 12, resets5)]),
                "seven_day": _win(_pt(t11, 42, resets7), [_pt(t10, 40, resets7), _pt(t11, 42, resets7)])}
    p = _pace(readings, tape=lambda a, b: sum(n for at, n in rows if a <= at < b))
    assert p.source == "estimate" and p.seven_day.used == pytest.approx(43.5) and p.five_hour.used == pytest.approx(13.5)
    assert p.five_hour.stale and p.five_hour.estimated and p.read_at


def test_a_passed_reset_counts_from_zero_and_steps_the_window_forward():
    t10, t11 = _t(-2 * H), _t(-1 * H)
    rows = [(t10 + 1800, 20_000_000), (t11 + 1800, 15_000_000)]
    resets5 = _t(-1 * H)
    readings = {"five_hour": _win(_pt(t11, 12, resets5), [_pt(t10, 10, resets5), _pt(t11, 12, resets5)]),
                "seven_day": _win(_pt(t11, 42, _t(3 * D)), [_pt(t10, 40, _t(3 * D)), _pt(t11, 42, _t(3 * D))])}
    p = _pace(readings, tape=lambda a, b: sum(n for at, n in rows if a <= at < b))
    assert p.five_hour.used == pytest.approx(1.5) and p.five_hour.resets_at == dt.datetime.fromtimestamp(resets5 + 5 * H).isoformat(timespec="seconds")


def test_no_calibration_or_no_reading_is_unknown():
    stale = _t(-3 * H)
    one = {"five_hour": _win(_pt(stale, 20, _t(2 * H))), "seven_day": _win(_pt(stale, 20, _t(3 * D)))}
    p = _pace(one, tape=lambda a, b: 10_000_000)
    assert p.source == "unknown" and p.hold == ("plan usage unknown", dpace.UNKNOWN_TEXT) and p.five_hour.used is None
    assert _pace({}).source == "unknown" and _pace({}).read_at is None


def test_a_limit_holds_even_with_a_low_reading_and_ends_with_its_until():
    p = _pace(_fresh(5, 5), limit={"until": _t(3 * H + 45 * 60)})
    assert p.source == "limit" and p.hold == ("usage limit", "usage limit until 15:45") and p.five_hour.used == 5
    assert p.limit_until == "2026-11-18T15:45:00"
    assert _pace(_fresh(5, 5), limit={"until": _t(-1)}).hold is None


def test_a_limit_on_another_day_names_the_weekday():
    p = _pace(_fresh(5, 5), limit={"until": _t(2 * D)})
    assert p.hold[1] == "usage limit until Fri 12:00"


def test_the_filler_window_opens_in_the_last_24_hours_unless_held():
    assert _pace(_fresh(10, 30, elapsed=0.8)).filler is False
    assert _pace(_fresh(10, 30, elapsed=1 - 20 * H / (7 * D))).filler is True
    assert _pace(_fresh(83, 30, elapsed=1 - 20 * H / (7 * D))).filler is False


def test_formats_and_doc():
    assert (dpace.fmt_pct(83.0), dpace.fmt_pct(43.54)) == ("83", "43.5")
    assert dpace.fmt_when(dt.datetime(2026, 11, 18, 15, 45), NOW) == "15:45"
    assert dpace.fmt_when(dt.datetime(2026, 11, 23, 0, 0), NOW) == "Mon 00:00"
    d = dpace.doc(_pace(_fresh(83, 41)), _policy())
    assert d["source"] == "reading" and d["five_hour"]["used"] == 83 and d["five_hour"]["stop"] == 80
    assert d["seven_day"]["pace"] == pytest.approx(46.0) and d["seven_day"]["target"] == pytest.approx(92.0)
    assert d["hold"] == "plan-window 83 % ≥ 80 %" and d["max_running"] is None and d["limit_until"] is None
