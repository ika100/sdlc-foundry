"""Spec 198 acceptance tests: merges wait for a release hold inside `merge_lock.held`, and the release sets its hold through
`merge_lock.set_release_hold` (AC-198.1 to AC-198.4, AC-198.7).

Contract: design.md, "`merge_lock.py`" and the table of lines. Seams: the fake clock behind `release_hold.sleep/now/alive` and
`merge_lock.sleep/time` (hold_world_198); `pr.wait` and `ship.land` run against the existing fakes (dispatch_world, test_ship).
"""
import os

import pytest

import core
import merge_lock
import pr as prmod
import ship
from dispatch_world import world  # noqa: F401  (fixture)
from hold_world_198 import (OTHER_PID, SLUG, busy_lock, clock, drop_hold, lock_is_free, read_hold, said,  # noqa: F401
                            stopped_hold, write_hold)
from test_ship import check, gh, repo, to_land  # noqa: F401  (fixtures)

WAITING = f"waiting for the release hold of {SLUG}: release 5.24.0 since 2026-11-16 10:20"
CLEARED = f"release hold of {SLUG} cleared"


def foreign_hold(clock, **fields):
    doc = write_hold(**fields)
    clock.live.add(doc["pid"])
    return doc


def lines_of(said, start):
    return [ln for ln in said if ln.startswith(start)]


# ---------------- AC-198.2: a merge meets a foreign hold ----------------

def test_a_merge_does_not_merge_while_another_process_holds_the_repo_ac_198_2(clock, said):  # AC-198.2
    foreign_hold(clock)
    clock.at(125, drop_hold)
    entered = []
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        entered.append(clock.t)
    assert entered[0] >= 125
    assert lines_of(said, "waiting for the release hold") == [WAITING] * 3          # at once, then every 60 seconds
    assert said.index(CLEARED) > said.index(WAITING)


def test_the_wait_for_a_hold_does_not_count_against_the_timeout_ac_198_2(clock, said):  # AC-198.2
    foreign_hold(clock)
    clock.at(3600, drop_hold)                                    # an hour, with a 30 second timeout
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        pass
    assert clock.t >= 3600 and not any("merge lock" in ln for ln in said)


def test_a_merge_waits_outside_the_merge_lock_so_the_release_can_merge_ac_198_2(clock, said):  # AC-198.2
    foreign_hold(clock)
    free = []
    clock.every(lambda: free.append(lock_is_free()))
    clock.at(20, drop_hold)
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        pass
    assert free and all(free)


def test_only_the_time_waiting_for_another_merge_still_counts_against_the_timeout_ac_198_2(clock, said):  # AC-198.2
    foreign_hold(clock)
    holder = {}

    def hold_ends_and_a_merge_takes_the_lock():
        drop_hold()
        holder["let_go"] = busy_lock(SLUG, "pr 11")
    clock.at(100, hold_ends_and_a_merge_takes_the_lock)
    clock.at(120, lambda: holder["let_go"]())                    # 20 seconds of lock wait, 30 allowed
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        assert clock.t >= 120


def test_a_busy_lock_after_the_hold_still_ends_as_busy_ac_198_2(clock, said):  # AC-198.2
    foreign_hold(clock)
    holder = {}

    def hold_ends_and_a_merge_takes_the_lock():
        drop_hold()
        holder["let_go"] = busy_lock(SLUG, "pr 11")
    clock.at(100, hold_ends_and_a_merge_takes_the_lock)
    clock.live.discard(os.getpid())                              # the holder's process is gone: the lock is stuck, not a queue
    try:
        with pytest.raises(merge_lock.Busy):
            with merge_lock.held(SLUG, "pr 10", 30, 5):
                pass
    finally:
        holder["let_go"]()


def test_a_stopped_hold_keeps_merges_waiting_until_it_expires_ac_198_6(clock, said):  # AC-198.6
    stopped_hold(expires="2026-11-16T11:20:00")                  # an hour after the start
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        assert clock.t >= 3600
    assert f"release hold of {SLUG} expired" in said
    assert read_hold() is None


# ---------------- AC-198.3: it continues by itself ----------------

def test_a_cleared_hold_lets_the_merge_continue_within_30_seconds_ac_198_3(clock, said):  # AC-198.3
    foreign_hold(clock)
    clock.at(7, drop_hold)
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        assert clock.t - 7 <= 30
    assert CLEARED in said


def test_the_merge_lock_is_free_again_after_the_merge_and_the_info_is_gone_ac_198_3(clock, said):  # AC-198.3
    foreign_hold(clock)
    clock.at(7, drop_hold)
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        pass
    assert lock_is_free()


def test_a_land_waits_for_the_hold_then_merges_as_without_it_ac_198_3(repo, gh, clock, said):  # AC-198.3
    to_land(repo, gh)
    gh.checks = [[check("test", "pass")]]
    foreign_hold(clock, slug="acme/shop-api")
    clock.at(40, lambda: drop_hold("acme/shop-api"))
    at_hold = []
    clock.every(lambda: at_hold.append(len(gh.merges)))
    ok, _ = ship.land(repo, timeout=30, interval=10)
    assert ok and len(gh.merges) == 1 and set(at_hold) == {0}        # nothing merged during the hold, one merge after it
    assert any(ln.startswith("waiting for the release hold of acme/shop-api") for ln in said)
    assert "release hold of acme/shop-api cleared" in said


def test_a_pr_wait_merge_waits_then_brings_a_branch_that_fell_behind_up_to_date_ac_198_3(world, clock, said):  # AC-198.3
    slug = "acme/shop-api"
    url = world.pr(10, "fix/a", checks=[[{"name": "ci", "bucket": "pass"}]],
                   after_update=[[{"name": "ci", "bucket": "pending"}], [{"name": "ci", "bucket": "pass"}]])
    foreign_hold(clock, slug=slug)
    merged_early = []

    def main_moves():
        merged_early.extend(e for e in world.events() if e["ev"] == "merged")
        world.edit_gh(lambda d: d["prs"]["10"].update(behind=1))      # main moved while the merge waited

    clock.at(10, main_moves)
    clock.at(20, lambda: drop_hold(slug))
    ok, lines = prmod.wait(world.repo, url, True, 60, 0.05, 60)
    assert ok and merged_early == []
    ev = [e["ev"] for e in world.events()]
    assert ev.index("updated") < ev.index("merged")                 # caught up, its checks waited for again, then merged
    assert any(a[:2] == ["pr", "update-branch"] for a in world.gh_calls())
    assert f"release hold of {slug} cleared" in said


# ---------------- AC-198.4: the release's own merge ----------------

def test_the_merge_of_the_holding_process_is_not_held_ac_198_4(clock, said):  # AC-198.4
    write_hold(pid=os.getpid())
    with merge_lock.held(SLUG, "pr 7", 30, 5):
        pass
    assert clock.t == 0 and lines_of(said, "waiting for the release hold") == []


def test_a_repo_without_a_hold_merges_at_once_ac_198_2(clock, said):  # AC-198.2
    with merge_lock.held(SLUG, "pr 7", 30, 5):
        pass
    assert clock.t == 0 and said == []


# ---------------- AC-198.7: a dead hold is dropped by the merge ----------------

def test_a_merge_drops_a_hold_whose_process_is_gone_and_goes_on_ac_198_7(clock, said):  # AC-198.7
    write_hold(pid=OTHER_PID)
    with merge_lock.held(SLUG, "pr 10", 30, 5):
        pass
    assert said == [f"release hold of {SLUG} dropped: process {OTHER_PID} is gone"]
    assert read_hold() is None and clock.t == 0


# ---------------- AC-198.1: set_release_hold ----------------

def test_the_release_sets_its_hold_and_says_so_ac_198_1(clock, said):  # AC-198.1
    hold = merge_lock.set_release_hold(SLUG, "5.24.0", 600)
    assert said == [f"release hold set on {SLUG} for 5.24.0"]
    assert read_hold()["version"] == "5.24.0" and read_hold()["pid"] == os.getpid() and hold.version == "5.24.0"
    assert lock_is_free()                                        # the release does not keep the merge lock


def test_the_release_waits_for_a_merge_inside_the_lock_to_end_first_ac_198_1(clock, said):  # AC-198.1
    let_go = busy_lock(SLUG, "pr 10 (issue-9)")
    seen = []
    clock.every(lambda: seen.append(read_hold() is not None))
    clock.at(125, let_go)
    try:
        merge_lock.set_release_hold(SLUG, "5.24.0", 600)
    finally:
        let_go()
    waiting = "waiting for the merge of pr 10 (issue-9) to end before the release"
    assert lines_of(said, "waiting for the merge of") == [waiting] * 3         # at once, then every 60 seconds
    assert said[-1] == f"release hold set on {SLUG} for 5.24.0"
    assert seen and all(seen)                                    # the hold was written before the wait, so no new merge gets in
    assert clock.t >= 125


def test_a_merge_that_does_not_end_in_time_stops_the_release_before_it_starts_ac_198_1(clock, said):  # AC-198.1
    let_go = busy_lock(SLUG, "pr 10")
    try:
        with pytest.raises(core.PlatformError) as e:
            merge_lock.set_release_hold(SLUG, "5.24.0", 30)
    finally:
        let_go()
    assert str(e.value) == f"the merge of pr 10 in {SLUG} did not end within 30s; the release did not start"
    assert read_hold() is None


def test_a_take_over_says_where_the_hold_came_from_ac_198_6(clock, said):  # AC-198.6
    stopped_hold(confirm="tag")
    merge_lock.set_release_hold(SLUG, "5.24.1", 600)
    assert said == [f"release hold set on {SLUG} for 5.24.1 (taken over from the stop at confirm tag)"]
    assert read_hold()["state"] == "running" and read_hold()["expires"] is None and read_hold()["pid"] == os.getpid()


def test_a_second_release_is_refused_before_anything_else_ac_198_7(clock, said):  # AC-198.7
    import release_hold
    before = foreign_hold(clock, version="5.23.9")
    with pytest.raises(release_hold.HoldTaken):
        merge_lock.set_release_hold(SLUG, "5.24.0", 600)
    assert read_hold() == before and said == []


def test_a_dead_hold_is_dropped_when_a_release_sets_its_own_ac_198_7(clock, said):  # AC-198.7
    write_hold(pid=OTHER_PID)
    merge_lock.set_release_hold(SLUG, "5.24.0", 600)
    assert said == [f"release hold of {SLUG} dropped: process {OTHER_PID} is gone", f"release hold set on {SLUG} for 5.24.0"]


def test_a_live_holder_is_a_queue_and_the_merge_waits_past_its_timeout(clock, said):
    let_go = busy_lock(SLUG, "pr 11")
    clock.at(7200, let_go)                          # twice the 3600 s timeout
    with merge_lock.held(SLUG, "pr 10", 3600, 5):
        pass
    assert lines_of(said, "waiting for the merge lock")


def test_a_live_holder_ends_the_wait_at_the_queue_limit(clock, said):
    let_go = busy_lock(SLUG, "pr 11")
    try:
        with pytest.raises(merge_lock.Busy):
            with merge_lock.held(SLUG, "pr 10", 3600, 5):
                pass
    finally:
        let_go()
    assert clock.t > merge_lock.QUEUE_LIMIT
