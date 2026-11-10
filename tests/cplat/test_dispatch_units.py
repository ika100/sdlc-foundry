"""Unit tests of `dispatch_units`: one unit's lifecycle against the fake `gh` and the fake headless of `dispatch_world`.

The cycle and the CLI call these functions; here the tests call them directly (the land process runs in this process).
"""
import os
import re
import signal
import time

import pytest

import claim
import dispatch_backlog
import dispatch_policy
import dispatch_state as ds
import dispatch_units as du
from dispatch_world import git, world  # noqa: F401  (fixture)

SLUG = "acme/shop-api"


@pytest.fixture()
def env(world, monkeypatch):
    world._patch_clock()
    monkeypatch.setattr(du, "LAND_INTERVAL", 0.05)
    monkeypatch.setattr(du, "spawn_land", lambda repo, unit: (du.land(repo, SLUG, unit["unit"]), 0)[1])
    world.policy(slots=2, budget={"tokens_per_day": 20_000_000, "per_unit": {"cost": 20}})
    return world


def cand(n):
    return dispatch_backlog.Candidate(key=f"issue-{n}", item=f"#{n}", kind="fix", title=f"issue {n}", labels=["triaged"], created="",
                                      text="", number=n)


def policy(world):
    return dispatch_policy.load(world.repo)


def begin(world, n=1, **behave):
    world.issue(n)
    world.behave(f"issue-{n}.1", **behave)
    res = du.start(world.repo, SLUG, cand(n), "single", 1, policy(world))
    assert res.unit, res
    world._settle(0, type("R", (), {"lines": res.lines})())
    return res


def test_start_claims_makes_the_worktree_and_spawns_headless_under_the_unit_run(env):
    env.behave(mode="wait")
    res = begin(env)
    [line] = res.lines
    assert re.match(r"started issue-1\.1 \(fix, single, slot 1\): .*--budget cost=20 .*/component:fix #1'  log: ", line)
    unit = res.unit
    assert git(unit["worktree"], "rev-parse", "--abbrev-ref", "HEAD") == "fix/issue-1"
    assert env.labels_of(1) == ["triaged", "in-progress"] and len(env.comments_of(1)) == 1
    [call] = env.calls()
    assert call["cwd"] == unit["worktree"] and unit["pid"] == call["pid"] and du.alive(unit["pid"])
    assert ds.read_unit(unit["worktree"])["status"] == "running" and ds.read_unit(unit["worktree"])["run_id"]


def test_a_claim_held_by_another_branch_is_refused_and_leaves_nothing(env):
    env.issue(1, labels=["triaged", "in-progress"], comments=["<!-- cplat-claim -->\nClaimed for branch `fix/other` (cplat dispatch)."])
    before = env.gh_writes()
    res = du.start(env.repo, SLUG, cand(1), "single", 1, policy(env))
    assert res.held == "claimed" and res.unit is None
    assert env.gh_writes() == before and env.calls() == [] and not ds.worktrees_dir(SLUG).exists()


def test_an_escalated_unit_is_labelled_released_and_recorded(env):
    res = begin(env, mode="now", then="escalate", reason="escalated: tests keep failing")
    env.wait_ended("issue-1.1")
    step = du.advance(env.repo, SLUG, ds.read_unit(res.unit["worktree"]), policy(env))
    assert step.lines == ["escalated issue-1.1: escalated: tests keep failing"]
    assert "needs-decision" in env.labels_of(1) and "in-progress" not in env.labels_of(1)
    assert any(du.ESCALATION_MARK in c and "tests keep failing" in c for c in env.comments_of(1))
    unit = ds.read_unit(res.unit["worktree"])
    assert unit["status"] == "escalated" and unit["cause"] == "decision"
    assert [e["kind"] for e in ds.load(SLUG)["events"]] == ["started", "escalated"]
    assert ds.load(SLUG)["history"][0]["outcome"] == "escalated"
    assert du.adopt(env.repo, SLUG) == []


def test_a_killed_unit_is_restarted_once_then_stuck(env):
    res = begin(env, then="die", die_after=0.05)
    pid = res.unit["pid"]
    env.wait_until(lambda: not du.alive(pid))
    unit = ds.read_unit(res.unit["worktree"])
    step = du.advance(env.repo, SLUG, unit, policy(env))
    assert step.lines == ["restarted issue-1.1 (start 2)"]
    env.wait_until(lambda: not du.alive(ds.read_unit(res.unit["worktree"])["pid"]))
    step = du.advance(env.repo, SLUG, ds.read_unit(res.unit["worktree"]), policy(env))
    unit = ds.read_unit(res.unit["worktree"])
    assert step.lines == [f"stuck issue-1.1: {unit['log']}"] and unit["status"] == "stuck"
    assert [n["kind"] for n in step.needs] == ["stuck"] and "environment" in step.needs[0]["reason"]
    assert len(env.calls_of("issue-1.1")) == 2 and len([c for c in env.comments_of(1) if "cplat-claim" in c]) == 1


def test_a_fix_unit_lands_and_finishes_done_with_its_tokens(env):
    res = begin(env, mode="now", then="done", tokens=4321)
    env.wait_ended("issue-1.1")
    wt = res.unit["worktree"]
    step = du.advance(env.repo, SLUG, ds.read_unit(wt), policy(env))
    assert re.fullmatch(r"landing issue-1\.1: https://github.com/acme/shop-api/pull/\d+", step.lines[0])
    assert ds.read_unit(wt)["landed"] == "merged"
    step = du.advance(env.repo, SLUG, ds.read_unit(wt), policy(env))
    assert re.fullmatch(r"done issue-1\.1: .*pull/\d+", step.lines[0])
    assert "in-progress" not in env.labels_of(1) and any("cplat-release" in c for c in env.comments_of(1))
    [entry] = ds.load(SLUG)["history"]
    assert entry["outcome"] == "done" and entry["tokens"] == 4321 and "pull/" in entry["pr"]
    assert os.path.isdir(wt)                                        # kept until a newer snapshot has seen the merge
    du.cleanup(env.repo, SLUG, "9999")
    assert not os.path.isdir(wt)


def test_a_red_pr_escalates_with_a_red_event_and_is_never_merged(env):
    env.set_default_checks([[{"name": "ci", "bucket": "fail"}]])
    res = begin(env, mode="now", then="done")
    env.wait_ended("issue-1.1")
    wt = res.unit["worktree"]
    du.advance(env.repo, SLUG, ds.read_unit(wt), policy(env))
    assert ds.read_unit(wt)["landed"] == "red"
    step = du.advance(env.repo, SLUG, ds.read_unit(wt), policy(env))
    assert step.lines[0].startswith("escalated issue-1.1")
    assert [e["kind"] for e in ds.load(SLUG)["events"]][-1] == "red" and not any(a[:2] == ["pr", "merge"] for a in env.gh_calls())
    assert ds.read_unit(wt)["cause"] == "code" and "needs-decision" in env.labels_of(1)


def test_a_finished_fix_without_a_pull_request_escalates_as_a_decision(env):
    res = begin(env, mode="now", then="done", pr=False)
    env.wait_ended("issue-1.1")
    step = du.advance(env.repo, SLUG, ds.read_unit(res.unit["worktree"]), policy(env))
    assert "ended without a pull request" in step.lines[0]
    assert ds.read_unit(res.unit["worktree"])["cause"] == "decision"


def test_adopt_finds_live_units_from_their_files_and_pause_flags_them(env):
    env.behave(mode="wait", honor_stop=True)
    res = begin(env)
    live = du.adopt(env.repo, SLUG)
    assert [u["unit"] for u in live] == ["issue-1.1"]
    assert du.adopted_lines(live) == [f"adopted issue-1.1 (pid {res.unit['pid']})"]
    assert du.pause_flags(live) == ["issue-1.1"] and ds.stop_path(res.unit["worktree"]).exists()
    env.wait_ended("issue-1.1")
    deadline = time.monotonic() + 15                     # the process may outlive its result file by a moment
    while True:
        assert du.advance(env.repo, SLUG, live[0], policy(env)).lines == []
        unit = ds.read_unit(res.unit["worktree"])
        if unit["status"] != "running" or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert unit["status"] == "paused"
    env.behave(mode="wait", honor_stop=False)
    step = du.resume_paused(env.repo, SLUG, unit, policy(env))
    assert step.lines == ["restarted issue-1.1 (resumed)"] and not ds.stop_path(res.unit["worktree"]).exists()
    resumed = ds.read_unit(res.unit["worktree"])
    assert resumed["starts"] == 1 and resumed["status"] == "running"
    os.kill(resumed["pid"], signal.SIGKILL)


def test_close_stale_comments_labels_and_closes(env):
    env.issue(1)
    assert du.close_stale(env.repo, SLUG, 1, "abc1234", "rounded since") == ["closed #1 as stale: abc1234"]
    issue = env.issue_of(1)
    assert issue["state"] == "CLOSED" and "stale-premise" in issue["labels"] and du.STALE_MARK in issue["comments"][0]["body"]


def test_start_resumes_a_dispatcher_claim_without_a_second_one(env):
    env.issue(1, labels=["triaged", "in-progress"], comments=[f"{claim.MARK}\nClaimed for branch `fix/issue-1` (cplat dispatch)."])
    res = du.start(env.repo, SLUG, cand(1), "single", 1, policy(env))
    assert res.unit and len(env.comments_of(1)) == 1
