"""Spec 210 module-level tests of the filler unit kinds `task` and `draft` (AC-210.9): start, classify, finish, escalate.

The seams are `spawn` (the process runs inline or not at all), `gh` and `alive`; the repo and the fake `gh` come from `dispatch_world`.
"""
import pytest

import dispatch_backlog
import dispatch_policy
import dispatch_state as ds
import dispatch_units as du
from dispatch_world import git, world  # noqa: F401  (fixture)

SLUG = "acme/shop-api"


@pytest.fixture()
def env(world, monkeypatch):
    world._patch_clock()
    world.policy(slots=2, budget={"mode": "plan"})
    monkeypatch.setattr(du, "alive", lambda pid: False)
    return world


def _cand(kind, key, text):
    return dispatch_backlog.Candidate(key=key, item=key, kind=kind, title=key, labels=[], created="", text=text)


def _start(env, monkeypatch, cand, run=None):
    """Start a filler unit; `run(unit)` plays the process that `spawn` would have started."""
    def spawn(unit, policy):
        if run:
            run(unit)
        return 4242
    monkeypatch.setattr(du, "spawn", spawn)
    res = du.start(env.repo, SLUG, cand, "single", 1, dispatch_policy.load(env.repo))
    assert res.unit, res
    return res


def _advance(env, unit):
    return du.advance(env.repo, SLUG, ds.read_unit(unit["worktree"]), dispatch_policy.load(env.repo))


def test_a_task_unit_has_a_detached_worktree_and_no_claim_ac_210_9(env, monkeypatch):  # AC-210.9
    res = _start(env, monkeypatch, _cand("task", "task-bench", "touch ran.marker"))
    unit = res.unit
    assert unit["branch"] is None and unit["tracks"] == [] and unit["command"] == "touch ran.marker"
    assert git(unit["worktree"], "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    [line] = res.lines
    assert line.startswith("started task-bench.1 (task, single, slot 1) (filler): touch ran.marker  log: ")
    assert env.gh_writes() == []


def test_a_task_that_ends_with_exit_0_is_done_and_exit_3_is_escalated_and_held_ac_210_9(env, monkeypatch):  # AC-210.9
    ok = _start(env, monkeypatch, _cand("task", "task-ok", "true"), run=lambda u: du.run_task(env.repo, SLUG, u["unit"]))
    assert ds.read_result(ok.unit["worktree"])["cost_usd"] == 0.0
    assert _advance(env, ok.unit).lines[0].startswith("done task-ok.1")
    bad = _start(env, monkeypatch, _cand("task", "task-bad", "exit 3"), run=lambda u: du.run_task(env.repo, SLUG, u["unit"]))
    assert ds.read_result(bad.unit["worktree"])["result"] == "exit 3"
    assert _advance(env, bad.unit).lines[0].startswith("escalated task-bad.1")
    assert ds.read_unit(bad.unit["worktree"])["status"] == "escalated"
    assert ds.load(SLUG)["steering"]["holds"]["task-bad"]["reason"] == "needs-decision"
    assert env.gh_writes() == []


def test_a_task_without_a_result_and_a_process_is_restarted_ac_210_9(env, monkeypatch):  # AC-210.9
    res = _start(env, monkeypatch, _cand("task", "task-x", "true"))
    assert _advance(env, res.unit).lines == ["restarted task-x.1 (start 2)"]


def _draft(env, monkeypatch, *, branch, pr):
    def run(unit):
        if branch:
            git(unit["worktree"], "checkout", "-q", "-b", branch)
        ds.write_json(ds.result_path(unit["worktree"]), {"unit": unit["unit"], "ended_at": ds.stamp(), "outcome": "done", "result": "finished",
                                                          "stop_reason": "finished", "tokens": 10})
    monkeypatch.setattr(du, "unit_pr", lambda repo, b: pr)
    return _start(env, monkeypatch, _cand("draft", "retro-90-1", "/component:spec add alpha #90"), run=run)


def test_a_draft_with_an_open_pull_request_is_done_and_releases_the_retro_claim_ac_210_9(env, monkeypatch):  # AC-210.9
    env.issue(90, labels=["retro"])
    res = _draft(env, monkeypatch, branch="feature/9-alpha", pr={"number": 7, "url": "https://github.com/acme/shop-api/pull/7", "state": "OPEN"})
    assert res.unit["retro_issue"] == 90 and res.unit["request"] == "/component:spec add alpha #90" and res.unit["branch"] is None
    step = _advance(env, res.unit)
    assert step.lines == ["done retro-90-1.1: https://github.com/acme/shop-api/pull/7"]
    assert any("retro draft retro-90-1.1 ended (cplat dispatch)" in c for c in env.comments_of(90))
    assert ds.load(SLUG)["filler"]["drafted"]["retro-90-1"] == {"unit": "retro-90-1.1", "branch": "feature/9-alpha",
                                                                  "pr": "https://github.com/acme/shop-api/pull/7"}
    assert not [a for a in env.gh_writes() if a[:2] in (["pr", "merge"], ["pr", "close"], ["pr", "ready"])]


def test_a_draft_without_a_pull_request_is_escalated_and_labels_no_issue_ac_210_9(env, monkeypatch):  # AC-210.9
    env.issue(90, labels=["retro"])
    res = _draft(env, monkeypatch, branch=None, pr=None)
    step = _advance(env, res.unit)
    assert step.lines[0].startswith("escalated retro-90-1.1: the draft run ended without a pull request")
    assert ds.read_unit(res.unit["worktree"])["cause"] == "decision"
    assert env.labels_of(90) == ["retro"] and not [a for a in env.gh_writes() if "--add-label" in a]
    assert "retro-90-1" in ds.load(SLUG)["filler"]["drafted"]
