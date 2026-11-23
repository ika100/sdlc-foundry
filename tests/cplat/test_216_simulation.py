"""Spec 216 acceptance tests: the driver against simulated repos, GitHub and Argo CD (AC-216.2, AC-216.3, AC-216.11).

The `cplat system ship` steps the driver takes must equal, in order, the sequence the `/system:ship` rules prescribe. The world is the one
of spec 097 (real git on a local bare origin, fake `gh`; Argo CD health is `ship.argo_health`), the repo sessions are
`appship_proc.spawn` / `alive` (the conftest records them; `sessions` also takes the answer of a resume), the clock is `waits.now` /
`waits.sleep` (`tick`: each sleep applies the next scripted change, here a repo session that ends or escalates) and the driver's
own seams are `support216.Sim` (spawn, alive, run_step). A step the world cannot produce offline (a `TIMEOUT:`, a `land` that exits 2)
is canned. The suite runs without network or cluster; the last test bounds it at 60 seconds.
"""
import time

import pytest

from support216 import (API_LIB, API_ONLY, API_WORKER, Sim, dw, escalate_repo_ship, finish_repo, progress, running_repo,  # noqa: F401
                        sessions, tick, timeout_line, timeout_step, wait_step)  # noqa: F401  (fixtures)

REASON = 'the plan splits "store" from "switch": which first? (needs your call)'
SUGGESTED = [{"text": "Which store holds the alerts?", "suggested": "redis"}, {"text": "How long do they live?", "suggested": "7 days"}]
PARTIAL = [{"text": "Which store holds the alerts?", "suggested": "redis"}, {"text": "How long do they live?", "suggested": None}]
JOINT = {"joint": True, "joint_pr": "https://github.com/acme/shop-gitops/pull/9"}


def canned_end(sim):
    """`complete` and `finish` are canned where the scenario is about the steps before them (the real ones are tested in AC-216.3 below)."""
    sim.can("complete", results=[(0, "## Shipped: 012-shop — Shop\nreport line\n")])
    sim.can("finish", results=[(0, "product ship ended; state archived to /archive/cplat-app-ship-012-shop.json\n")])


def passed_land(dw):
    dw.started(API_ONLY, phase="repos", states={"shop-api": "passed"}, **JOINT)


# ---------------- two dependent repos to DONE ----------------

def two_dependent_repos(dw, sim, tick):
    dw.started(API_LIB)                                              # phase publish: the spec and plan are on main
    canned_end(sim)
    tick.script = [lambda: finish_repo(dw, "shop-api"), lambda: finish_repo(dw, "shop-lib")]
    return sim.run()


def test_two_dependent_repos_run_in_plan_order_to_the_end_ac_216_11(dw, tick, monkeypatch):  # AC-216.11, AC-216.3, AC-216.2
    sim = Sim(dw, monkeypatch)
    assert two_dependent_repos(dw, sim, tick) == 0
    assert sim.steps == [("publish",), ("next",), ("repo", "start", "shop-api"), ("next",), ("next", "--wait"),
                         ("repo", "start", "shop-lib"), ("next",), ("next", "--wait"),
                         ("phase", "complete"), ("complete",), ("finish",)]
    assert [s[2] for s in sim.spawned] == []                          # the loop is run directly: nothing detached here
    st = dw.state()
    assert st["phase"] == "complete" and not st.get("escalated")
    assert {i: st["repos"][i]["state"] for i in ("shop-api", "shop-lib")} == {"shop-api": "passed", "shop-lib": "passed"}
    end = progress(dw)["end"]
    assert end["kind"] == "done" and "report line" in end["report"] and end["archive"] == "/archive/cplat-app-ship-012-shop.json"


def test_publish_exit_0_goes_on_with_the_repos_and_runs_the_other_phases_in_order_ac_216_3(dw, tick, monkeypatch):  # AC-216.3
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY)
    canned_end(sim)
    tick.script = [lambda: finish_repo(dw, "shop-api")]
    sim.run()
    assert sim.steps[0] == ("publish",) and sim.steps[1] == ("next",)
    assert dw.state()["phase"] in ("complete", "done") and dw.made("pr", "create") == []        # nothing to publish: no PR


def test_the_complete_phase_runs_complete_then_finish_and_ends_done_ac_216_3(dw, monkeypatch):  # AC-216.3
    from test_appship_097 import all_passed
    sim = Sim(dw, monkeypatch)
    all_passed(dw)                                                    # phase complete, every repo passed
    assert sim.run() == 0
    assert sim.steps == [("complete",), ("finish",)]                  # `phase complete` was set already
    end = progress(dw)["end"]
    assert end["kind"] == "done" and "## Shipped: 012-shop — Shop" in end["report"] and end["archive"].endswith(".json")
    assert not dw.state_file.exists()                                 # finish archived the state


def test_a_complete_action_sets_the_phase_then_completes_and_finishes_ac_216_3(dw, monkeypatch):  # AC-216.3
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY, phase="repos", states={"shop-api": "passed"})
    canned_end(sim)
    assert sim.run() == 0
    assert sim.steps == [("next",), ("phase", "complete"), ("complete",), ("finish",)]


# ---------------- an escalated repo with cause decision ----------------

def api_and_worker(dw, tick, reason, cause, questions):
    dw.started(API_WORKER, phase="repos")
    tick.script = [lambda: (running_repo(dw, "shop-worker"), escalate_repo_ship(dw, "shop-api", reason, cause, questions))]


def test_a_decision_with_a_suggestion_for_every_question_is_resumed_with_them_ac_216_11(dw, tick, sessions, monkeypatch):  # AC-216.11, AC-216.2
    sim = Sim(dw, monkeypatch)
    api_and_worker(dw, tick, REASON, "decision", SUGGESTED)
    tick.script.append(lambda: (finish_repo(dw, "shop-api"), finish_repo(dw, "shop-worker")))
    canned_end(sim)
    assert sim.run() == 0
    answer = "Which store holds the alerts?: redis; How long do they live?: 7 days"           # A6: question order, `; ` between
    assert sim.steps == [("next",), ("repo", "start", "shop-api"), ("repo", "start", "shop-worker"), ("next",), ("next", "--wait"),
                         ("repo", "resume", "shop-api", "--answer", answer), ("next",), ("next", "--wait"),
                         ("phase", "complete"), ("complete",), ("finish",)]
    assert sessions[-1]["clone"] == "shop-api" and sessions[-1]["answer"] == answer               # the repo session got the answer


def test_a_repo_without_a_suggestion_is_held_then_the_run_escalates_with_its_cause_ac_216_11(dw, tick, sessions, monkeypatch):  # AC-216.11, AC-216.2
    sim = Sim(dw, monkeypatch)
    api_and_worker(dw, tick, REASON, "decision", PARTIAL)
    tick.script.append(lambda: finish_repo(dw, "shop-worker"))
    assert sim.run() == 0
    reason = dw.state()["repos"]["shop-api"]["reason"]
    assert sim.steps == [("next",), ("repo", "start", "shop-api"), ("repo", "start", "shop-worker"), ("next",), ("next", "--wait"),
                         ("repo", "hold", "shop-api"), ("next",), ("next", "--wait"), ("escalate", reason)]
    assert "--cause" not in sim.steps[-1]                              # the repo's cause stays
    st = dw.state()
    assert st["escalated"] and st["cause"] == "decision" and st["repos"]["shop-api"]["held"]
    assert progress(dw)["end"] is None                                 # `escalate` ends the driver without an end record: the state tells


def test_a_cause_that_is_not_a_decision_is_held_even_with_suggestions_ac_216_2(dw, tick, sessions, monkeypatch):  # AC-216.2
    sim = Sim(dw, monkeypatch)
    api_and_worker(dw, tick, "CI red after 3 rounds", "code", SUGGESTED)
    tick.script.append(lambda: finish_repo(dw, "shop-worker"))
    sim.run()
    assert ("repo", "hold", "shop-api") in sim.steps and not [s for s in sim.steps if s[:2] == ("repo", "resume")]
    assert sim.steps[-1][0] == "escalate" and "--cause" not in sim.steps[-1] and dw.state()["cause"] == "code"


# ---------------- TIMEOUT: three in a row escalate, a WAIT: resets the count ----------------

def test_three_timeouts_in_a_row_escalate_with_cause_environment_ac_216_11(dw, monkeypatch):  # AC-216.11, AC-216.2
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY, phase="repos")
    sim.can("next", "--wait", results=[timeout_step(1), timeout_step(2), timeout_step(3)])
    assert sim.run() == 0
    assert sim.steps == [("next",), ("repo", "start", "shop-api"), ("next",), ("next", "--wait"), ("next", "--wait"), ("next", "--wait"),
                         ("escalate", timeout_line(3), "--cause", "environment")]
    st = dw.state()
    assert st["escalated"] and st["cause"] == "environment" and timeout_line(3) in st["escalated"]


def test_two_timeouts_around_a_wait_do_not_escalate_ac_216_11(dw, tick, monkeypatch):  # AC-216.11, AC-216.2
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY, phase="repos")
    sim.can("next", "--wait", results=[timeout_step(1), wait_step(), timeout_step(2)])
    canned_end(sim)
    tick.script = [lambda: finish_repo(dw, "shop-api")]
    assert sim.run() == 0
    waits = [s for s in sim.steps if s == ("next", "--wait")]
    assert len(waits) == 4 and not [s for s in sim.steps if s[0] == "escalate"]       # T, W, T, then the world's answer
    assert not dw.state().get("escalated") and progress(dw)["end"]["kind"] == "done"


def test_a_wait_starts_the_timeout_count_again_ac_216_2(dw, tick, monkeypatch):  # AC-216.2
    sim = Sim(dw, monkeypatch)
    dw.started(API_ONLY, phase="repos")
    sim.can("next", "--wait", results=[timeout_step(1), timeout_step(2), wait_step(), timeout_step(3), timeout_step(4)])
    canned_end(sim)
    tick.script = [lambda: finish_repo(dw, "shop-api")]
    assert sim.run() == 0
    assert len([s for s in sim.steps if s == ("next", "--wait")]) == 6 and not [s for s in sim.steps if s[0] == "escalate"]
    assert not dw.state().get("escalated")


# ---------------- land: exit 2 twice and then 0; three times escalates ----------------

def test_land_exiting_2_twice_and_then_0_goes_on_to_complete_ac_216_11(dw, monkeypatch):  # AC-216.11, AC-216.3
    sim = Sim(dw, monkeypatch)
    passed_land(dw)
    sim.can("land", results=[timeout_step(1), timeout_step(2), (0, "dev landed\n")])
    canned_end(sim)
    assert sim.run() == 0
    assert sim.steps == [("next",), ("land",), ("land",), ("land",), ("phase", "complete"), ("complete",), ("finish",)]
    assert progress(dw)["end"]["kind"] == "done" and not dw.state().get("escalated")


def test_land_exiting_2_three_times_escalates_with_cause_environment_ac_216_11(dw, monkeypatch):  # AC-216.11, AC-216.3
    sim = Sim(dw, monkeypatch)
    passed_land(dw)
    sim.can("land", results=[timeout_step(1), timeout_step(2), timeout_step(3)])
    assert sim.run() == 0
    assert sim.steps == [("next",), ("land",), ("land",), ("land",), ("escalate", timeout_line(3), "--cause", "environment")]
    st = dw.state()
    assert st["escalated"] and st["cause"] == "environment"


def test_land_exiting_1_has_escalated_the_run_so_the_driver_ends_ac_216_3(dw, monkeypatch):  # AC-216.3
    sim = Sim(dw, monkeypatch)
    passed_land(dw)
    sim.can("land", results=[(1, "dev PR is red: smoke failed\n")])
    assert sim.run() == 0
    assert sim.steps == [("next",), ("land",)]                         # no `escalate` of its own, no `complete`


# ---------------- a preflight failure leaves one repo escalated, the others go on ----------------

def test_a_preflight_failed_repo_is_escalated_and_the_other_repo_goes_on_ac_216_11(dw, tick, monkeypatch):  # AC-216.11, AC-216.2
    import preflight
    sim = Sim(dw, monkeypatch)

    def check(path, slug):
        return preflight.Failure("environment", "no gh login") if str(path).endswith("shop-api") else None
    monkeypatch.setattr(preflight, "check_repo", check)
    dw.started(API_WORKER, phase="repos")
    tick.script = [lambda: finish_repo(dw, "shop-worker")]
    assert sim.run() == 0
    assert sim.steps == [("next",), ("repo", "start", "shop-api"), ("repo", "start", "shop-worker"), ("next",),
                         ("repo", "hold", "shop-api"), ("next",), ("next", "--wait"), ("escalate", "preflight failed: environment")]
    st = dw.state()
    assert st["repos"]["shop-api"]["state"] == "escalated" and st["repos"]["shop-worker"]["state"] == "passed"
    assert st["escalated"] and st["cause"] == "environment"


# ---------------- offline and fast ----------------

def test_the_simulation_runs_offline_in_under_60_seconds_ac_216_11(dw, tick, monkeypatch):  # AC-216.11
    start = time.monotonic()
    sim = Sim(dw, monkeypatch)
    assert two_dependent_repos(dw, sim, tick) == 0
    assert time.monotonic() - start < 60
    assert tick.slept > 0                                              # the waits ran on the scripted clock, not the real one
    assert all(c[0] in ("pr", "repo", "run", "api", "secret") for c in dw.calls())     # only the fake `gh` answered
