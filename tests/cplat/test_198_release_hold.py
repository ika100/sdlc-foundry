"""Spec 198 acceptance tests: the release hold file and its rules (AC-198.1, 198.3, 198.5 to 198.9).

Contract: design.md, "The hold file" and "`release_hold.py`". Seams: `release_hold.now`, `release_hold.sleep`, `release_hold.alive`
(a fake clock, see hold_world_198); the hold file is read and written by its documented JSON shape.
"""
import json
import os

import pytest

import core
from hold_world_198 import OTHER_PID, SLUG, clock, drop_hold, hold_path, read_hold, said, stopped_hold, write_hold  # noqa: F401

WAITING = f"waiting for the release hold of {SLUG}: release 5.24.0 since 2026-11-16 10:20"


@pytest.fixture()
def rh(clock):
    import release_hold
    return release_hold


# ---------------- AC-198.1: what a hold records ----------------

def test_claim_records_version_start_time_and_own_process_ac_198_1(rh, clock):  # AC-198.1
    hold, taken = rh.claim(SLUG, "5.24.0")
    assert taken is False and hold.pid == os.getpid()
    assert read_hold() == {"slug": SLUG, "version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": os.getpid(),
                           "state": "running", "confirm": None, "expires": None}


def test_an_unreadable_hold_file_counts_as_no_hold_and_is_replaced_ac_198_1(rh):  # AC-198.1
    hold_path().parent.mkdir(parents=True, exist_ok=True)
    hold_path().write_text("[not an object")
    assert rh.read(SLUG) is None and rh.view(SLUG) is None
    rh.claim(SLUG, "5.24.0")
    assert read_hold()["version"] == "5.24.0"


# ---------------- AC-198.7: a hold whose process is gone, a second release ----------------

def test_a_running_hold_of_a_dead_process_is_dropped_by_whoever_checks_ac_198_7(rh, clock, said):  # AC-198.7
    write_hold(pid=OTHER_PID)
    assert rh.resolve(SLUG) is None
    assert read_hold() is None
    assert said == [f"release hold of {SLUG} dropped: process {OTHER_PID} is gone"]


def test_a_running_hold_of_a_live_process_is_kept_ac_198_7(rh, clock, said):  # AC-198.7
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    h = rh.resolve(SLUG)
    assert h.pid == OTHER_PID and h.version == "5.24.0" and read_hold() is not None and said == []


def test_a_second_release_is_refused_and_nothing_changes_ac_198_7(rh, clock):  # AC-198.7
    before = write_hold(pid=OTHER_PID, version="5.23.9")
    clock.live.add(OTHER_PID)
    with pytest.raises(rh.HoldTaken) as e:
        rh.claim(SLUG, "5.24.0")
    assert isinstance(e.value, core.PlatformError)
    assert "5.23.9" in str(e.value) and str(OTHER_PID) in str(e.value) and "one release at a time" in str(e.value)
    assert read_hold() == before


def test_claim_over_a_dead_hold_starts_a_new_one_ac_198_7(rh, clock, said):  # AC-198.7
    write_hold(pid=OTHER_PID)
    hold, taken = rh.claim(SLUG, "5.25.0")
    assert not taken and read_hold()["version"] == "5.25.0" and read_hold()["pid"] == os.getpid()
    assert said == [f"release hold of {SLUG} dropped: process {OTHER_PID} is gone"]


# ---------------- AC-198.6: a stop keeps the hold, a later run takes it over ----------------

def test_a_stop_keeps_the_hold_for_two_hours_ac_198_6(rh, clock):  # AC-198.6
    rh.claim(SLUG, "5.24.0")
    clock.t = 600
    h = rh.stop(SLUG, "merge")
    assert h.state == "stopped" and h.confirm == "merge"
    doc = read_hold()
    assert (doc["state"], doc["confirm"], doc["expires"], doc["pid"]) == ("stopped", "merge", "2026-11-16T12:30:00", os.getpid())
    assert rh.release(SLUG) is False and read_hold() is not None        # the exit of a stopped release removes nothing


def test_stop_without_an_own_running_hold_does_nothing_ac_198_6(rh, clock):  # AC-198.6
    assert rh.stop(SLUG, "tag") is None and read_hold() is None
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    assert rh.stop(SLUG, "tag") is None and read_hold()["state"] == "running"


def test_a_later_run_takes_over_a_stopped_hold_and_lifts_the_expiry_ac_198_6(rh, clock):  # AC-198.6
    stopped_hold(confirm="tag", version="5.24.0", since="2026-11-16T09:00:00")
    hold, taken = rh.claim(SLUG, "5.24.1")
    assert taken is True
    assert read_hold() == {"slug": SLUG, "version": "5.24.1", "since": "2026-11-16T09:00:00", "pid": os.getpid(),
                           "state": "running", "confirm": None, "expires": None}


def test_an_expired_stopped_hold_is_removed_with_the_expired_line_ac_198_6(rh, clock, said):  # AC-198.6
    stopped_hold(expires="2026-11-16T10:00:00")
    assert rh.resolve(SLUG) is None and read_hold() is None
    assert said == [f"release hold of {SLUG} expired"]


def test_a_stopped_hold_does_not_need_a_running_process_until_it_expires_ac_198_6(rh, clock, said):  # AC-198.6
    stopped_hold(pid=OTHER_PID)                     # the process ended at the stop: that is no "gone"
    h = rh.resolve(SLUG)
    assert h is not None and h.state == "stopped" and said == []


# ---------------- AC-198.5: the release clears its own hold ----------------

def test_release_removes_an_own_running_hold_only_ac_198_5(rh, clock):  # AC-198.5
    rh.claim(SLUG, "5.24.0")
    assert rh.release(SLUG) is True and read_hold() is None
    assert rh.release(SLUG) is False
    write_hold(pid=OTHER_PID)
    assert rh.release(SLUG) is False and read_hold() is not None        # never another process's hold


# ---------------- AC-198.4: a merge of the holder's own process passes ----------------

def test_foreign_is_none_for_the_own_hold_and_the_hold_of_another_process_ac_198_4(rh, clock):  # AC-198.4
    assert rh.foreign(SLUG) is None
    write_hold(pid=os.getpid())
    assert rh.foreign(SLUG) is None
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    assert rh.foreign(SLUG).pid == OTHER_PID


# ---------------- AC-198.8: show and clear by hand ----------------

def test_clear_removes_any_hold_and_returns_it_ac_198_8(rh, clock):  # AC-198.8
    assert rh.clear(SLUG) is None
    write_hold(pid=OTHER_PID)                       # a dead one too
    h = rh.clear(SLUG)
    assert h.version == "5.24.0" and read_hold() is None


def test_view_is_the_effective_hold_and_text_is_its_line_ac_198_8(rh, clock):  # AC-198.8
    assert rh.view(SLUG) is None and rh.text(SLUG, None) == f"no release hold on {SLUG}"
    write_hold(pid=OTHER_PID)
    assert rh.view(SLUG) is None and read_hold() is not None            # stale: absent for a reader, and not removed
    clock.live.add(OTHER_PID)
    v = rh.view(SLUG)
    assert v == {"version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": OTHER_PID, "state": "running", "expires": None}
    assert rh.text(SLUG, v) == f"release hold on {SLUG}: release 5.24.0 since 2026-11-16 10:20, process {OTHER_PID}, running"
    stopped_hold(confirm="tag")
    v = rh.view(SLUG)
    assert v == {"version": "5.24.0", "since": "2026-11-16T10:20:00", "pid": OTHER_PID, "state": "stopped at confirm tag",
                 "expires": "2026-11-16T12:20:00"}
    assert rh.text(SLUG, v) == (f"release hold on {SLUG}: release 5.24.0 since 2026-11-16 10:20, process {OTHER_PID}, "
                                "stopped at confirm tag, expires 2026-11-16 12:20")
    assert rh.describe(rh.read(SLUG)) == "release 5.24.0 since 2026-11-16 10:20"
    json.dumps(v)


# ---------------- AC-198.2 / AC-198.3: the wait loop of a merge ----------------

def _waiting(rh, said):
    return [ln for ln in said if ln.startswith("waiting for the release hold")]


def test_the_wait_says_what_it_waits_for_at_once_and_every_60_seconds_ac_198_2(rh, clock, said):  # AC-198.2
    h = write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    clock.at(125, drop_hold)
    waited = rh.wait_clear(SLUG, rh.read(SLUG))
    assert _waiting(rh, said) == [WAITING] * 3                  # at 0, 60 and 120 seconds
    assert said[0] == WAITING and said[-1] == f"release hold of {SLUG} cleared"
    assert 125 <= waited <= 130 and h["version"] == "5.24.0"


def test_a_cleared_hold_lets_the_wait_end_within_30_seconds_ac_198_3(rh, clock, said):  # AC-198.3
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    clock.at(7, drop_hold)
    rh.wait_clear(SLUG, rh.read(SLUG))
    assert clock.t - 7 <= 30 and said[-1] == f"release hold of {SLUG} cleared"


def test_a_hold_that_expires_ends_the_wait_with_the_expired_line_ac_198_3(rh, clock, said):  # AC-198.3
    stopped_hold(expires="2026-11-16T10:21:00")                  # 60 seconds from the start of the wait
    rh.wait_clear(SLUG, rh.read(SLUG))
    assert said[-1] == f"release hold of {SLUG} expired" and read_hold() is None
    assert 60 <= clock.t <= 90


def test_a_hold_whose_process_dies_ends_the_wait_with_the_dropped_line_ac_198_7(rh, clock, said):  # AC-198.7
    write_hold(pid=OTHER_PID)
    clock.live.add(OTHER_PID)
    clock.at(20, lambda: clock.live.discard(OTHER_PID))
    rh.wait_clear(SLUG, rh.read(SLUG))
    assert said[-1] == f"release hold of {SLUG} dropped: process {OTHER_PID} is gone" and read_hold() is None
    assert clock.t <= 20 + 30
