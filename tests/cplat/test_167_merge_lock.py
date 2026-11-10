"""Spec 167 acceptance tests: the repo merge lock (AC-167.7).

Contract: design.md "The merge lock" (`pr wait --merge` and `ship land` hold a machine-wide lock per repo slug; a branch behind main is
updated and its checks wait again before it merges; with `e2e` in `serialize` the lock covers the whole land phase). Seams: the fake
`gh` on PATH (it models `main` moving: a merge makes every other open PR behind by one, `update-branch` gives a new head with its own
checks, a merge takes `merge_delay` seconds with the fake's own lock released, and every call and merge is logged with a timestamp);
`pr.wait` (a unit) and `pr.main(["wait", ...])` (a manual session) in two threads; `merge_lock.sleep` when the module has one.
"""
import importlib
import threading
import time

import pytest

import core
import pr as prmod
from dispatch_world import world  # noqa: F401  (fixture)

A = "https://github.com/acme/shop-api/pull/10"
B = "https://github.com/acme/shop-api/pull/11"
PASS = [{"name": "ci", "bucket": "pass"}]
PENDING = [{"name": "ci", "bucket": "pending"}]
FAIL = [{"name": "ci", "bucket": "fail"}]


@pytest.fixture(autouse=True)
def quick_lock_polling(monkeypatch):
    try:
        lock = importlib.import_module("merge_lock")
    except ImportError:
        return
    monkeypatch.setattr(lock, "sleep", lambda s: time.sleep(min(s, 0.05)), raising=False)


class Land(threading.Thread):
    def __init__(self, fn):
        super().__init__(daemon=True)
        self.fn, self.result, self.error = fn, None, None

    def run(self):
        try:
            self.result = self.fn()
        except BaseException as e:   # noqa: BLE001
            self.error = e


def _lock(world):
    return world.state_home / "sdlc-foundry" / "locks" / "acme__shop-api.merge.lock"


def _unit(world, url=A):
    return Land(lambda: prmod.wait(world.repo, url, True, 60, 0.05, 60))


def _manual(world, url=B):
    return Land(lambda: prmod.main(["wait", url, "--merge", "--interval", "0.05", "--timeout", "60", "--repo", str(world.repo)]))


def _two(world, first, second, delay=0.6):
    """Start `first`, wait until its merge is under way, start `second`, join both."""
    world.edit_gh(lambda d: d.update(merge_delay=delay))
    first.start()
    world.wait_until(lambda: any(e["ev"] == "merge-start" and e["pr"] == 10 for e in world.events()), timeout=20)
    second.start()
    first.join(60)
    second.join(60)
    assert not first.is_alive() and not second.is_alive()


def _times(world):
    ev = world.events()
    t = {(e["ev"], e["pr"]): e["t"] for e in ev}
    calls = [(e["t"], e["argv"]) for e in world._gh()["log"]]
    return ev, t, calls


def test_two_lands_in_one_repo_merge_one_at_a_time_and_the_second_reruns_its_ci_on_top_ac_167_7(world):  # AC-167.7
    world.pr(10, "fix/a", checks=[PASS])
    world.pr(11, "fix/b", checks=[PASS], after_update=[[{"name": "ci", "bucket": "pending"}], [{"name": "ci", "bucket": "pass"}]])
    unit, manual = _unit(world), _manual(world)
    _two(world, unit, manual)
    assert unit.error is None and manual.error is None, (unit.error, manual.error)
    assert unit.result[0] is True and manual.result == 0
    ev, t, calls = _times(world)
    assert [(e["ev"], e["pr"]) for e in ev if e["ev"] != "merge-start"] == [("merged", 10), ("updated", 11), ("merged", 11)]
    assert t[("merged", 10)] < t[("updated", 11)] < t[("merge-start", 11)]                 # the second waited for the first
    second = [e for e in ev if e["ev"] == "merged" and e["pr"] == 11][0]
    assert second["behind"] == 0 and second["green"] is True and second["head"] != "sha11-0"   # merged on its updated head, green
    before_merge = [argv for ts, argv in calls if t[("updated", 11)] <= ts <= t[("merge-start", 11)]]
    assert any(a[:2] == ["pr", "checks"] and a[2].endswith("/11") for a in before_merge)        # its CI ran again before it merged
    assert _lock(world).exists()


def test_a_branch_that_is_not_behind_main_is_merged_without_an_update_ac_167_7(world):  # AC-167.7
    world.pr(10, "fix/a", checks=[PASS])
    ok, lines = prmod.wait(world.repo, A, True, 60, 0.05, 60)
    assert ok and lines[-1].startswith("merged")
    assert not any(a[:2] == ["pr", "update-branch"] for a in world.gh_calls())
    assert [e["green"] for e in world.events() if e["ev"] == "merged"] == [True]
    assert _lock(world).exists()                                       # even a lone merge goes through the repo lock


def test_a_merge_is_never_made_while_a_check_is_red_ac_167_7(world):  # AC-167.7
    world.policy(serialize=["merge", "e2e"])                           # the land phase, red CI included, holds the lock
    world.pr(10, "fix/a", checks=[[{"name": "ci", "bucket": "pass"}, {"name": "e2e", "bucket": "fail"}]])
    ok, lines = prmod.wait(world.repo, A, True, 60, 0.05, 60)
    assert not ok and lines[0].startswith("RED")
    assert not any(a[:2] == ["pr", "merge"] for a in world.gh_calls())
    assert _lock(world).exists()


def test_a_branch_whose_new_head_turns_red_after_the_update_is_not_merged_ac_167_7(world):  # AC-167.7
    world.pr(10, "fix/a", checks=[PASS])
    world.pr(11, "fix/b", checks=[PASS], after_update=[[{"name": "ci", "bucket": "pending"}], FAIL])
    unit, manual = _unit(world), _manual(world)
    _two(world, unit, manual)
    assert unit.error is None and unit.result[0] is True
    assert manual.error is None and manual.result == 1
    ev = world.events()
    assert [e["pr"] for e in ev if e["ev"] == "merged"] == [10] and any(e["ev"] == "updated" and e["pr"] == 11 for e in ev)


def test_a_conflict_on_the_update_is_a_human_decision_and_nothing_merges_ac_167_7(world):  # AC-167.7
    world.pr(10, "fix/a", checks=[PASS])
    world.pr(11, "fix/b", checks=[PASS])
    unit, manual = _unit(world), _manual(world)
    world.edit_gh(lambda d: d.update(update_conflict=True))
    _two(world, unit, manual)
    assert [e["pr"] for e in world.events() if e["ev"] == "merged"] == [10]
    assert isinstance(manual.error, core.PlatformError) or manual.result == 1


def test_with_e2e_in_serialize_the_lock_covers_the_whole_land_phase_ac_167_7(world):  # AC-167.7
    world.policy(serialize=["merge", "e2e"])
    world.pr(10, "fix/a", checks=[PENDING, PENDING, PASS])
    world.pr(11, "fix/b", checks=[PENDING, PASS], after_update=[PASS])
    unit, manual = _unit(world), _manual(world)
    _two(world, unit, manual, delay=0.5)
    assert unit.error is None and manual.error is None, (unit.error, manual.error)
    ev, t, calls = _times(world)
    first_checks_b = min(ts for ts, argv in calls if argv[:2] == ["pr", "checks"] and argv[2].endswith("/11"))
    assert first_checks_b > t[("merged", 10)]                         # no CI wait of the second while the first lands
    assert t[("merged", 10)] < t[("merge-start", 11)]


def test_without_e2e_only_the_merge_is_serialized_ac_167_7(world):  # AC-167.7
    world.pr(10, "fix/a", checks=[PASS])
    world.pr(11, "fix/b", checks=[PASS], after_update=[PASS])
    unit, manual = _unit(world), _manual(world)
    _two(world, unit, manual, delay=0.8)
    ev, t, calls = _times(world)
    first_checks_b = min(ts for ts, argv in calls if argv[:2] == ["pr", "checks"] and argv[2].endswith("/11"))
    assert first_checks_b < t[("merged", 10)]                         # the second watched its CI while the first merged
    assert t[("merged", 10)] < t[("merge-start", 11)]                 # but its merge waited
