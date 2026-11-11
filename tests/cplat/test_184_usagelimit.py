"""Spec 184 acceptance tests: the usage-limit decision (AC-184.1, AC-184.2) and the budget minutes (AC-184.3).

Seam: `usagelimit.detect` / `usagelimit.Pauser` (design.md, Contract, "Usage-limit pause") and `budget.add_pause`.
No process, no sleeping: the module only decides. The local time zone is pinned so the reset times are exact.
"""
import datetime as dt
import os
import time

import pytest

import runs
from test_runs import clock  # noqa: F401  (fixture)

NOW = dt.datetime(2026, 11, 11, 10, 0)


@pytest.fixture(autouse=True)
def new_york():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


class Lazy:
    """The module `usagelimit`, imported at the first use inside a test (a missing module fails the test, not its fixture)."""

    def __getattr__(self, name):
        import usagelimit
        return getattr(usagelimit, name)


@pytest.fixture()
def ul():
    return Lazy()


def unix(local: dt.datetime) -> int:
    return int(time.mktime(local.timetuple()))


def at(hours=0, minutes=0):
    return NOW + dt.timedelta(hours=hours, minutes=minutes)


# ---------------- detect: the message and its reset time (AC-184.1) ----------------

def test_the_unix_reset_after_the_bar_is_read_as_local_time_ac_184_1(ul):  # AC-184.1
    reset = at(hours=4)
    hit = ul.detect(f"Claude AI usage limit reached|{unix(reset)}\n", 3.0, NOW)
    assert hit is not None and hit.reset == reset


@pytest.mark.parametrize("text, expected", [
    ("5-hour limit reached ∙ resets 3pm", dt.datetime(2026, 11, 11, 15, 0)),
    ("Claude usage limit reached. Your limit will reset - resets 3:30pm", dt.datetime(2026, 11, 11, 15, 30)),
    ("limit reached, resets at 9am", dt.datetime(2026, 11, 12, 9, 0)),          # 9am is past at 10:00: the next one
    ("You've hit your limit · resets Nov 14 at 9am", dt.datetime(2026, 11, 14, 9, 0)),
    ("You've hit your session limit · resets 3:30pm (Europe/Berlin)", dt.datetime(2026, 11, 12, 9, 30)),   # 15:30 Berlin = 09:30 here, tomorrow
    ("usage limit reached, resets 3pm (Mars/Olympus)", dt.datetime(2026, 11, 11, 15, 0)),               # an unknown zone is local
])
def test_the_resets_form_is_the_first_such_moment_at_or_after_the_end_ac_184_1(ul, text, expected):  # AC-184.1
    hit = ul.detect(text + "\n", 3.0, NOW)
    assert hit is not None and hit.reset == expected


def test_only_the_last_non_empty_line_is_read_for_the_message_ac_184_1(ul):  # AC-184.1
    talk = "I will write about the usage limit now.\nThe usage limit reached|1763035200 line is quoted above.\nDone, all green.\n\n  \n"
    assert ul.detect(talk, 600.0, NOW) is None
    last = "some work\nmore work\n\nClaude AI usage limit reached|1763035200\n\n"
    assert ul.detect(last, 600.0, NOW) is not None


def test_an_ordinary_end_is_no_hit_ac_184_1(ul):  # AC-184.1
    assert ul.detect("shipped 007-price-alerts\n", 5.0, NOW) is None
    assert ul.detect("shipped 007-price-alerts\n", 900.0, NOW) is None


# ---------------- detect: silent and without a time (AC-184.2) ----------------

@pytest.mark.parametrize("output, seconds, hit", [
    ("", 0.0, True), ("  \n\n", 59.0, True), ("", 59.9, True), ("", 60.0, False), ("", 600.0, False),
    ("done\n", 3.0, False),
])
def test_a_session_with_no_output_that_ends_within_60_seconds_is_a_hit_without_a_time_ac_184_2(ul, output, seconds, hit):  # AC-184.2
    got = ul.detect(output, seconds, NOW)
    assert (got is not None) is hit
    if hit:
        assert got.reset is None


def test_the_message_without_a_reset_time_is_a_hit_without_a_time_ac_184_2(ul):  # AC-184.2
    hit = ul.detect("Claude usage limit reached\n", 900.0, NOW)
    assert hit is not None and hit.reset is None


# ---------------- Pauser: with a reset time (AC-184.1) ----------------

def test_a_reset_time_pauses_until_one_minute_after_it_ac_184_1(ul):  # AC-184.1
    p = ul.Pauser()
    pause = p.pause(ul.Hit(reset=at(hours=4)), NOW)
    assert pause.stop is None
    assert pause.seconds == 4 * 3600 + 60
    assert pause.line == "paused: usage limit, resumes at 2026-11-11 14:01"
    assert p.total_seconds == 4 * 3600 + 60


# ---------------- Pauser: the backoff (AC-184.2) ----------------

def test_without_a_time_the_waits_are_5_10_20_40_then_60_minutes_ac_184_2(ul):  # AC-184.2
    p = ul.Pauser()
    now = NOW
    waits = []
    for _ in range(8):
        pause = p.pause(ul.Hit(reset=None), now)
        assert pause.stop is None
        waits.append(pause.seconds / 60)
        assert pause.line == f"paused: usage limit, next try at {now + dt.timedelta(seconds=pause.seconds):%Y-%m-%d %H:%M}"
        now += dt.timedelta(seconds=pause.seconds)
    assert waits == [5, 10, 20, 40, 60, 60, 60, 60]


def test_a_session_that_was_no_pause_starts_the_backoff_again_but_keeps_the_total_ac_184_2(ul):  # AC-184.2
    p = ul.Pauser()
    assert p.pause(ul.Hit(reset=None), NOW).seconds == 300
    assert p.pause(ul.Hit(reset=None), NOW).seconds == 600
    p.resumed()
    assert p.pause(ul.Hit(reset=None), NOW).seconds == 300
    assert p.total_seconds == (5 + 10 + 5) * 60


def test_the_pauses_of_one_run_stop_at_360_minutes_in_total_ac_184_2(ul):  # AC-184.2
    p = ul.Pauser()
    for _ in range(8):                                  # 5+10+20+40+60+60+60+60 = 315 minutes
        assert p.pause(ul.Hit(reset=None), NOW).stop is None
    stop = p.pause(ul.Hit(reset=None), NOW)             # 315 + 60 > 360
    assert stop.stop == "environment pause: usage limit resets at unknown" and stop.stop.startswith(ul.STOP_PREFIX)
    assert stop.seconds == 0
    assert p.total_seconds == 315 * 60


def test_a_reset_time_beyond_the_cap_stops_at_once_and_names_the_reset_itself_ac_184_2(ul):  # AC-184.2
    p = ul.Pauser()
    stop = p.pause(ul.Hit(reset=at(hours=7)), NOW)
    assert stop.stop == "environment pause: usage limit resets at 2026-11-11 17:00" and stop.seconds == 0
    assert p.pause(ul.Hit(reset=at(hours=5)), NOW).stop is None          # within the cap


def test_reset_pauses_and_backoff_pauses_share_the_one_total_ac_184_2(ul):  # AC-184.2
    p = ul.Pauser()
    assert p.pause(ul.Hit(reset=at(hours=5)), NOW).stop is None          # 301 minutes
    assert p.pause(ul.Hit(reset=None), NOW).stop is None                  # + 5 = 306
    assert p.pause(ul.Hit(reset=None), NOW).stop is None                  # + 10 = 316
    assert p.pause(ul.Hit(reset=None), NOW).stop is None                  # + 20 = 336
    assert p.pause(ul.Hit(reset=None), NOW).stop is not None              # + 40 > 360


# ---------------- budget: pause minutes (AC-184.3) ----------------

def test_pause_minutes_do_not_count_against_the_minutes_of_the_budget_ac_184_3(clock):  # AC-184.3
    import budget
    rid = runs.start("headless", repo="acme/shop-api", mode="headless")
    budget.open_root(rid, "pause-key")
    clock.tick(90 * 60)
    path, data = budget.find(rid)
    assert budget.used_of(data, cost=False)["minutes"] == 90
    budget.add_pause(rid, 60)
    path, data = budget.find(rid)
    assert data["current"]["paused_minutes"] == 60
    assert budget.used_of(data, cost=False)["minutes"] == 30
    budget.add_pause(rid, 25)
    assert budget.used_of(budget.find(rid)[1], cost=False)["minutes"] == 5
    budget.add_pause(rid, 600)                                    # never below what was carried
    assert budget.used_of(budget.find(rid)[1], cost=False)["minutes"] == 0


def test_a_continued_ledger_carries_the_minutes_without_the_pause_ac_184_3(clock):  # AC-184.3
    import budget
    first = runs.start("headless", repo="acme/shop-api", mode="headless")
    budget.open_root(first, "pause-key-2")
    clock.tick(120 * 60)
    budget.add_pause(first, 60)                                   # the run died during its pause: its root never closed
    second = runs.start("headless", repo="acme/shop-api", mode="headless")
    budget.open_root(second, "pause-key-2")
    assert budget.find(second)[1]["carried"]["minutes"] == 60


def test_adding_a_pause_to_a_run_without_a_ledger_never_raises_ac_184_3(clock):  # AC-184.3
    import budget
    budget.add_pause(None, 5)
    budget.add_pause("no-such-run", 5)
