"""Spec 210 acceptance tests: mode plan, the holds and the estimate (AC-210.6, AC-210.7, AC-210.8).

Contract: design.md "Plan state (`dispatch_pace.pace`)", "The gate", "`plan --json` and `status --json`". The readings, the booked-token tape
and the limit record are fixture files in the documented format under `$XDG_STATE_HOME/sdlc-foundry/usage/`; the clock is the world's.
A cycle is `cplat dispatch start --once`; the units are the fake headless of `dispatch_world`.
"""
import datetime as dt

import pytest

from dispatch_world import world  # noqa: F401  (fixture)
from support_210 import (D, H, M, TODAY, UNKNOWN_TEXT, fresh, issues, put_limit, put_readings, read_json, reading, record_message,
                         tape, ts, usage_dir, window)

HOLD_83 = "plan-window 83 % ≥ 80 %"


def _mode_plan(world, slots=2):
    world.policy(slots=slots, budget={"mode": "plan"})
    issues(world, 3)
    world.behave(mode="wait")


def _held_budget(world, text, n=3):
    doc = world.plan()
    cands = [c for c in doc["candidates"] if c["item"] in ("#1", "#2", "#3")][:n]
    assert cands and all(c["verdict"] == "held" and c["reason"] == "budget" and c["detail"] == text for c in cands), cands
    assert doc["starts"]["allowed"] is False and doc["starts"]["text"] == text
    assert f"held: {text}" in world.run("plan").out


def _nothing_started(world):
    assert world.calls() == [] and world.claude_calls() == [] and world.gh_writes() == []


# ---------------- AC-210.6: the 5-hour window ----------------

def test_a_five_hour_reading_of_83_percent_holds_every_start_and_agent_call_ac_210_6(world):  # AC-210.6
    _mode_plan(world)
    fresh(world, five=83, week=30)
    r = world.run("start", "--once")
    assert r.rc == 0 and f"no starts: {HOLD_83}" in r.out, r
    _nothing_started(world)
    _held_budget(world, HOLD_83)
    status = world.run("status", "--json").json()
    assert status["starts"] == {"allowed": False, "why_not": "plan window", "text": HOLD_83}
    assert status["plan"]["five_hour"]["used"] == 83 and HOLD_83 in world.run("status").out
    assert all(h["reason"] == "budget" and h["detail"] == HOLD_83 for h in status["held"]) and len(status["held"]) == 3


def test_running_units_continue_to_their_end_when_the_window_holds_ac_210_6(world):  # AC-210.6
    _mode_plan(world)
    fresh(world, five=10, week=30)
    world.run("start", "--once")
    pids = [c["pid"] for c in world.calls()]
    assert len(pids) == 2
    fresh(world, five=83, week=30)
    assert world.run("start", "--once").rc == 0
    assert all(world.alive(p) for p in pids) and len(world.calls()) == 2


def test_a_five_hour_reading_of_79_percent_holds_nothing_ac_210_6(world):  # AC-210.6
    _mode_plan(world)
    fresh(world, five=79, week=30)
    doc = world.plan()
    assert doc["starts"]["allowed"] is True and doc["plan"]["hold"] is None
    assert world.run("start", "--once").rc == 0
    assert len(world.calls()) == 2


@pytest.mark.parametrize("used,started", [(30, 2), (43, 1)])
def test_the_weekly_pace_bands_cap_the_running_units_ac_210_6(world, used, started):  # AC-210.6
    _mode_plan(world)
    fresh(world, five=10, week=used, week_elapsed=0.5)
    doc = world.plan()
    assert doc["plan"]["seven_day"]["pace"] == pytest.approx(46.0) and doc["plan"]["seven_day"]["target"] == pytest.approx(92.0)
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert len(world.calls()) == started, (used, r.out)
    world.run("start", "--once")
    assert len(world.calls()) == started                                       # a second cycle does not exceed the band


def test_at_50_percent_used_at_50_percent_elapsed_no_unit_starts_ahead_of_pace_ac_210_6(world):  # AC-210.6
    _mode_plan(world)
    fresh(world, five=10, week=50, week_elapsed=0.5)
    text = "ahead of weekly pace (50 % used, pace 46 %)"
    r = world.run("start", "--once")
    assert r.rc == 0 and f"no starts: {text}" in r.out, r
    _nothing_started(world)
    _held_budget(world, text)
    assert world.run("status", "--json").json()["starts"]["why_not"] == "ahead of weekly pace"


def test_at_or_above_the_weekly_target_no_unit_starts_ac_210_6(world):  # AC-210.6
    _mode_plan(world)
    fresh(world, five=10, week=92, week_elapsed=0.5)
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: weekly target reached" in r.out, r
    _nothing_started(world)
    _held_budget(world, "weekly target reached")
    assert world.run("status", "--json").json()["starts"]["why_not"] == "weekly target reached"


def test_the_window_stop_and_weekly_target_of_the_policy_are_used_ac_210_6(world):  # AC-210.6
    world.policy(slots=2, budget={"mode": "plan", "plan": {"window_stop": 0.6, "weekly_target": 0.5}})
    issues(world, 2)
    fresh(world, five=61, week=10, week_elapsed=0.5)                           # pace is 25 % now
    assert world.run("start", "--once").out.count("no starts: plan-window 61 % ≥ 60 %") == 1
    fresh(world, five=10, week=50, week_elapsed=0.5)
    assert "no starts: weekly target reached" in world.run("start", "--once").out
    assert world.calls() == []


def test_the_plan_json_carries_the_plan_object_and_the_text_the_plan_line_ac_210_2(world):  # AC-210.2
    world.policy(slots=1, budget={"mode": "plan"})
    at = world.now - 4 * M
    five_resets = world.now.replace(hour=15, minute=45)
    seven_resets = world.now + 7 * D / 2                                      # a Saturday, 00:00: half of the week is over
    put_readings(world, five=window(reading(at, 83, five_resets)), seven=window(reading(at, 41, seven_resets)))
    doc = world.plan()
    p = doc["plan"]
    assert {"source", "read_at", "five_hour", "seven_day", "filler"} <= set(p)
    assert p["source"] == "reading" and p["filler"] is False and p["read_at"]
    assert set(p["five_hour"]) >= {"used", "resets_at", "stop"} and p["five_hour"]["used"] == 83 and p["five_hour"]["stop"] == 80
    assert set(p["seven_day"]) >= {"used", "resets_at", "pace", "target"} and p["seven_day"]["used"] == 41
    assert p["seven_day"]["pace"] == pytest.approx(46.0) and p["seven_day"]["target"] == pytest.approx(92.0)
    assert doc["cost"]["day"] == TODAY and doc["policy"]["values"]["budget"]["mode"] == "plan"
    line = "plan usage: 5h 83 % (stop 80 %, resets 15:45) · week 41 % (pace 46 %, target 92 %, resets Sat 00:00) · reading 4 min old"
    assert line in world.run("plan").out.splitlines()
    assert line in world.run("status").out.splitlines()
    assert world.run("status", "--json").json()["plan"] == p


def test_plan_in_mode_plan_changes_nothing_ac_210_2(world):  # AC-210.2
    _mode_plan(world)
    fresh(world, five=10, week=30)
    before = world.fingerprint()
    for args in (("plan",), ("plan", "--json"), ("status",), ("status", "--json")):
        assert world.run(*args).rc == 0
    assert world.fingerprint() == before and world.calls() == [] and world.gh_writes() == []
    assert not list((world.dispatch_dir() / "worktrees").glob("*"))


# ---------------- AC-210.7: a stale reading is estimated ----------------

def _calibrated(world, tape_after=15_000_000, five_resets=None):
    """40 % at 10:00 and 42 % at 11:00 with 20 M tokens between: 10 M per point. Now is 12:00, so the newest reading is stale."""
    t10, t11 = world.now - 2 * H, world.now - 1 * H
    seven_resets = world.now + D * 3 + 12 * H
    five_resets = five_resets or world.now + 2 * H
    put_readings(
        world,
        five=window(reading(t11, 12, five_resets), [reading(t10, 10, five_resets), reading(t11, 12, five_resets)]),
        seven=window(reading(t11, 42, seven_resets), [reading(t10, 40, seven_resets), reading(t11, 42, seven_resets)]))
    tape(world, (t10 + 30 * M, 20_000_000), (t11 + 30 * M, tape_after))


def test_a_stale_reading_plus_the_booked_tokens_gives_the_estimate_ac_210_7(world):  # AC-210.7
    world.policy(slots=2, budget={"mode": "plan"})
    _calibrated(world)
    p = world.plan()["plan"]
    assert p["source"] == "estimate"
    assert p["seven_day"]["used"] == pytest.approx(43.5) and p["five_hour"]["used"] == pytest.approx(13.5)
    assert "estimate from a reading 60 min old" in world.run("plan").out


def test_an_estimate_is_used_for_the_holds_like_a_reading_ac_210_7(world):  # AC-210.7
    world.policy(slots=2, budget={"mode": "plan"})
    issues(world, 2)
    _calibrated(world, tape_after=200_000_000)                                 # 42 % + 20 points = 62 %: far ahead of the pace
    r = world.run("start", "--once")
    assert r.rc == 0 and "no starts: ahead of weekly pace (62 % used, pace" in r.out, r
    _nothing_started(world)


def test_a_window_whose_reset_has_passed_counts_from_zero_ac_210_7(world):  # AC-210.7
    world.policy(slots=2, budget={"mode": "plan"})
    _calibrated(world, tape_after=15_000_000, five_resets=world.now - 1 * H)    # the 5-hour window reset at 11:00
    p = world.plan()["plan"]
    assert p["source"] == "estimate"
    assert p["five_hour"]["used"] == pytest.approx(1.5)                         # 0 % + the 15 M booked since the reset at 11:00, at 10 M per point
    assert p["five_hour"]["used"] < 12                                          # not the old 12 %


def test_no_reading_at_all_holds_starts_and_lists_one_need_per_day_ac_210_7(world):  # AC-210.7
    _mode_plan(world)
    r = world.run("start", "--once")
    assert r.rc == 0 and f"no starts: {UNKNOWN_TEXT}" in r.out, r
    _nothing_started(world)
    p = world.plan()
    assert p["plan"]["source"] == "unknown" and p["starts"]["text"] == UNKNOWN_TEXT
    _held_budget(world, UNKNOWN_TEXT)
    assert f"plan usage: unknown ({UNKNOWN_TEXT[len('plan usage unknown ('):]}" in world.run("plan").out
    assert world.run("status", "--json").json()["starts"] == {"allowed": False, "why_not": "plan usage unknown", "text": UNKNOWN_TEXT}
    world.run("start", "--once")
    [need] = [i for i in world.needs("--json").json()["items"] if i["kind"] == "budget"]
    assert need["id"] == f"budget:acme/shop-api:{TODAY}" and need["reason"].startswith("plan usage unknown")
    assert "cplat dispatch sensor install" in need["command"]


def test_a_stale_reading_without_a_calibration_holds_starts_ac_210_7(world):  # AC-210.7
    _mode_plan(world)
    at = world.now - 3 * H
    put_readings(world, five=window(reading(at, 20, world.now + 2 * H)), seven=window(reading(at, 20, world.now + 3 * D)))
    tape(world, (world.now - 2 * H, 10_000_000))
    r = world.run("start", "--once")
    assert r.rc == 0 and f"no starts: {UNKNOWN_TEXT}" in r.out, r
    _nothing_started(world)
    assert world.plan()["plan"]["source"] == "unknown"


def test_two_readings_without_booked_tokens_between_them_are_no_calibration_ac_210_7(world):  # AC-210.7
    _mode_plan(world)
    a, b = world.now - 3 * H, world.now - 2 * H
    five_resets, seven_resets = world.now + 2 * H, world.now + 3 * D
    put_readings(world, five=window(reading(b, 22, five_resets), [reading(a, 20, five_resets), reading(b, 22, five_resets)]),
                 seven=window(reading(b, 22, seven_resets), [reading(a, 20, seven_resets), reading(b, 22, seven_resets)]))
    tape(world, (world.now - 30 * M, 10_000_000))                               # tokens only after the second reading
    assert world.plan()["plan"]["source"] == "unknown"


# ---------------- AC-210.8: a usage-limit message ----------------

def test_a_limit_until_a_reset_holds_every_start_even_with_a_low_reading_ac_210_8(world):  # AC-210.8
    _mode_plan(world)
    fresh(world, five=5, week=5)
    put_limit(world, until=world.now.replace(hour=15, minute=45))
    r = world.run("start", "--once")
    text = "usage limit until 15:45"
    assert r.rc == 0 and f"no starts: {text}" in r.out, r
    _nothing_started(world)
    doc = world.plan()
    assert doc["plan"]["source"] == "limit" and doc["plan"]["hold"] == text and doc["plan"]["limit_until"]
    _held_budget(world, text)
    assert "usage limit until 15:45" in world.run("plan").out and doc["plan"]["five_hour"]["used"] == 5


def test_running_units_continue_while_a_limit_holds_ac_210_8(world):  # AC-210.8
    _mode_plan(world)
    fresh(world, five=5, week=5)
    world.run("start", "--once")
    pids = [c["pid"] for c in world.calls()]
    assert len(pids) == 2
    put_limit(world, until=world.now + 2 * H)
    assert world.run("start", "--once").rc == 0
    assert all(world.alive(p) for p in pids) and len(world.calls()) == 2


def test_starts_continue_once_the_limits_reset_has_passed_ac_210_8(world):  # AC-210.8
    _mode_plan(world)
    fresh(world, five=5, week=5)
    put_limit(world, until=world.now + 2 * H)
    assert world.run("start", "--once").rc == 0 and world.calls() == []
    world.set_now(world.now + 2 * H + 1 * M)
    fresh(world, five=5, week=5)
    assert world.run("start", "--once").rc == 0
    assert len(world.calls()) == 2


def test_the_limit_holds_each_cycle_and_nothing_spends_credits_ac_210_8(world):  # AC-210.8
    _mode_plan(world)
    fresh(world, five=5, week=5)
    put_limit(world, until=world.now + 2 * H, message="You've hit your weekly limit · resets Mon 12:00am")
    for _ in range(2):
        assert "no starts: usage limit until" in world.run("start", "--once").out
    _nothing_started(world)


def test_a_limit_message_with_a_reset_time_is_recorded_with_that_time_ac_210_8(world):  # AC-210.8
    record_message(world, "You've hit your session limit · resets 3:45pm", ended=dt.datetime(2026, 11, 10, 12, 0))
    doc = read_json(usage_dir(world) / "limit.json")
    assert dt.datetime.fromtimestamp(doc["until"]) == dt.datetime(2026, 11, 10, 15, 45)
    assert doc["reset_known"] is True and "session limit" in doc["message"]


def test_a_limit_message_without_a_reset_time_holds_for_60_minutes_ac_210_8(world):  # AC-210.8
    ended = dt.datetime(2026, 11, 10, 12, 0)
    record_message(world, "You've hit your limit", ended=ended)
    doc = read_json(usage_dir(world) / "limit.json")
    assert doc["until"] == ts(ended + 1 * H) and doc["reset_known"] is False
    _mode_plan(world)
    fresh(world, five=5, week=5)
    world.set_now(ended + 30 * M)
    fresh(world, five=5, week=5)
    assert "no starts: usage limit until 13:00" in world.run("start", "--once").out
    world.set_now(ended + 61 * M)
    fresh(world, five=5, week=5)
    assert world.run("start", "--once").rc == 0 and len(world.calls()) == 2


def test_a_weekly_limit_message_is_recorded_ac_210_8(world):  # AC-210.8
    ended = dt.datetime(2026, 11, 10, 12, 0)
    record_message(world, "You've hit your weekly limit · resets Mon 12:00am", ended=ended)
    doc = read_json(usage_dir(world) / "limit.json")
    assert "weekly limit" in doc["message"] and doc["until"] > ts(ended)


def test_a_silent_short_session_records_no_limit_ac_210_8(world):  # AC-210.8
    import usagelimit
    ended = dt.datetime(2026, 11, 10, 12, 0)
    assert usagelimit.detect("", 3.0, ended).message is None                    # a hit, but it carries no limit line
    assert usagelimit.detect("You've hit your limit", 120.0, ended).message == "You've hit your limit"
    record_message(world, "", ended=ended, seconds=3.0)
    assert not (usage_dir(world) / "limit.json").exists()
    record_message(world, "You've hit your limit", ended=ended)
    before = (usage_dir(world) / "limit.json").read_text()
    record_message(world, "", ended=ended + 4 * H, seconds=3.0)
    assert (usage_dir(world) / "limit.json").read_text() == before


def test_a_later_limit_replaces_the_file_only_when_it_ends_later_ac_210_8(world):  # AC-210.8
    ended = dt.datetime(2026, 11, 10, 12, 0)
    record_message(world, "You've hit your session limit · resets 3:45pm", ended=ended)
    record_message(world, "You've hit your session limit · resets 1:00pm", ended=ended)
    assert dt.datetime.fromtimestamp(read_json(usage_dir(world) / "limit.json")["until"]) == dt.datetime(2026, 11, 10, 15, 45)
