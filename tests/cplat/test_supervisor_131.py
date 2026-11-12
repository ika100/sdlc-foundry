"""Spec 131 acceptance tests: the supervisor (`cplat headless` running a unit ship), design.md "Supervisor".

A fake `claude` (units131_support.py) does one unit of work per session and records `CPLAT_UNIT`, its arguments and its
environment. `cplat headless` is called as in the other headless tests: `headless.main([prompt, "--repo", repo, ...])`.
"""
import re

import pytest

import headless
import ship
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import BRANCH, SPEC_ID, World, git


@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    """Spec 159: these tests are about units as spec 131 made them; batch units are tested in test_159_batch_units.py."""
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")

SEVEN = ["plan", "red-tests", "task:t1", "task:t2", "task:t3", "verification", "land"]


@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=False)


@pytest.fixture()
def planned(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=True)


# ---------------- AC-131.1 ----------------

def test_a_ship_of_a_plan_with_3_tasks_runs_7_sessions_one_after_the_other(w, capsys):  # AC-131.1
    assert w.run() == 0
    assert w.units_run() == SEVEN
    out = capsys.readouterr().out
    assert f"HEADLESS shop-api: shipped {SPEC_ID}" in out


def test_each_prompt_names_its_unit(w):  # AC-131.1
    w.run()
    for s in w.sessions():
        assert s["argv"][0] == "-p"
        assert s["argv"][1] == f"/component:ship 7 --unit {s['unit']}"


def test_the_prompt_keeps_the_other_arguments(tmp_path, monkeypatch):  # AC-131.1
    w = World(tmp_path, monkeypatch, plan=False)
    assert w.run(prompt="/component:ship 7 --no-merge") == 0
    assert [s["argv"][1] for s in w.sessions()][1] == "/component:ship 7 --no-merge --unit red-tests"


def test_the_summary_log_has_one_line_per_session_naming_unit_and_ending(w):  # AC-131.1
    w.run()
    lines = [ln for ln in w.summary() if " unit " in ln]
    assert len(lines) == 7
    for unit, ln in zip(SEVEN, lines):
        assert re.match(rf"\d{{4}}-\d\d-\d\d \d\d:\d\d HEADLESS shop-api: {SPEC_ID} unit {re.escape(unit)} session 1: "
                        rf"checkpoint [0-9a-f]{{7}}  \(.+\.log\)$", ln), ln
    assert w.summary()[-1].split("HEADLESS shop-api: ")[1].startswith(f"shipped {SPEC_ID}")


def test_a_unit_that_is_already_complete_is_skipped(planned):  # AC-131.1
    assert planned.run() == 0
    assert planned.units_run() == SEVEN[1:]


@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_a_session_that_ends_without_checkpoint_is_named_so_in_the_summary(w):  # AC-131.1
    w.behave({"task:t2": ["die", "ok"]})
    w.run()
    lines = [ln for ln in w.summary() if "unit task:t2 session" in ln]
    assert "session 1: no checkpoint (exit 1)" in lines[0] and "session 2: checkpoint " in lines[1]


# ---------------- AC-131.2 ----------------

def test_every_unit_gets_its_own_fresh_session_with_its_unit_in_the_environment(w):  # AC-131.2
    w.run()
    ids = []
    for s in w.sessions():
        ids.append(s["argv"][s["argv"].index("--session-id") + 1])
    assert len(set(ids)) == 7
    assert [s["unit"] for s in w.sessions()] == SEVEN                 # CPLAT_UNIT of the session


# ---------------- AC-131.3 ----------------

@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_a_unit_that_ends_early_is_started_again_from_its_checkpoint_and_done_units_never_repeat(w):  # AC-131.3
    w.behave({"task:t2": ["nothing", "ok"], "red-tests": ["partial", "ok"]})
    assert w.run() == 0
    assert w.units_run() == ["plan", "red-tests", "red-tests", "task:t1", "task:t2", "task:t2", "task:t3", "verification", "land"]


@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_a_session_killed_without_a_commit_leaves_the_checkpoints_of_earlier_units(w):  # AC-131.3
    w.behave({"task:t3": ["die", "ok"]})
    w.run()
    first_t3 = w.units_run().index("task:t3")
    assert w.units_run()[:first_t3].count("plan") == 1 and w.units_run().count("task:t1") == 1 and w.units_run().count("task:t2") == 1


# ---------------- AC-131.5 ----------------

@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_two_sessions_without_a_commit_escalate_instead_of_a_third(w, store, capsys):  # AC-131.5
    w.behave({"task:t2": ["nothing", "nothing", "ok"]})
    assert w.run() == 1
    assert w.units_run().count("task:t2") == 2 and "task:t3" not in w.units_run()
    reason = f"no progress: unit task:t2 after 2 sessions without a commit"
    assert reason in capsys.readouterr().out
    st = ship.load_state(w.repo)
    assert st["escalated"].startswith(reason)
    rec = stored(store)[-1]
    assert rec["outcome"] == "escalated" and rec["escalation"]["reason"].startswith(reason)


def test_the_cause_of_the_stall_is_chosen_as_in_126_7(w):  # AC-131.5
    w.behave({"task:t1": ["say-approval", "say-approval"]})
    assert w.run() == 1
    st = ship.load_state(w.repo)
    assert st["cause"] == "environment" and st["escalated"].startswith("no progress: unit task:t1 after 2 sessions without a commit")


@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_a_cause_without_a_rule_is_a_decision_or_code_never_environment(w):  # AC-131.5
    w.behave({"task:t1": ["nothing", "nothing"]})
    w.run()
    assert ship.load_state(w.repo)["cause"] in {"code", "decision"}


@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_sessions_that_add_commits_reset_the_count_and_are_bounded_only_by_the_budget(w):  # AC-131.5
    w.behave({"task:t2": ["partial", "partial", "partial", "partial", "nothing", "ok"]})
    assert w.run() == 0
    assert w.units_run().count("task:t2") == 6


@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_a_commit_between_two_idle_sessions_prevents_the_escalation(w):  # AC-131.5
    w.behave({"task:t2": ["nothing", "partial", "nothing", "ok"]})
    assert w.run() == 0
    assert w.units_run().count("task:t2") == 4


# ---------------- AC-131.14: rescale at the plan checkpoint ----------------

def test_the_limits_are_raised_when_the_plan_unit_ends_and_the_new_limits_are_shown(tmp_path, monkeypatch, capsys):  # AC-131.14
    w = World(tmp_path, monkeypatch, plan=False, tasks=8, acs=14)
    assert w.run("--max-runs", "2") == 1                              # plan, red-tests
    out = capsys.readouterr().out
    limits = [ln for ln in out.splitlines() if ln.startswith("budget: ")]
    assert "cost $15" in limits[0] and "(plan:" not in limits[0]
    assert limits[-1] == "budget: minutes 250, invocations 74, reruns 6, cost $29 (plan: T=8, C=14)  (cplat budget show)"
    (ledger,) = w.ledgers()
    assert ledger["limits"] == {"minutes": 250, "invocations": 74, "reruns": 6, "cost": 29}
    assert any(c["limit"] == "cost" and c["from"] == 15 and c["to"] == 29 and c["reason"] == f"plan of {SPEC_ID}: T=8, C=14"
               for c in ledger["changes"])


def test_the_limits_are_never_lowered_when_the_plan_is_small(w):  # AC-131.14
    w.run("--max-runs", "1", "--budget", "invocations=100", "--budget", "minutes=500")
    (ledger,) = w.ledgers()
    assert ledger["limits"]["invocations"] == 100 and ledger["limits"]["minutes"] == 500


# ---------------- AC-131.15, AC-131.16: the verification grace ----------------

def test_the_grace_lets_the_verification_start_and_never_land(planned, store, capsys):  # AC-131.15
    assert planned.run("--budget", "invocations=4") == 1              # red-tests + 3 tasks use all 4
    out = capsys.readouterr().out
    assert "budget grace: verification" in out
    assert planned.units_run() == ["red-tests", "task:t1", "task:t2", "task:t3", "verification"]
    assert "budget exhausted: invocations" in out
    rec = [r for r in stored(store) if r["kind"] == "headless"][-1]   # its ship record has the same frozen ended_at
    assert rec["stop_reason"] == "budget" and rec["budget"]["grace"]["for"] == "verification"
    assert rec["budget"]["verification_left"] in (True, False)


def test_the_grace_is_given_once(planned, capsys):  # AC-131.15
    planned.run("--budget", "invocations=4")
    assert capsys.readouterr().out.count("budget grace: verification") == 1


def test_no_grace_while_an_earlier_unit_is_open(planned, capsys):  # AC-131.15
    assert planned.run("--budget", "invocations=3") == 1              # red-tests, t1, t2 use all 3; t3 is open
    out = capsys.readouterr().out
    assert "budget grace" not in out and "budget exhausted: invocations" in out
    assert planned.units_run() == ["red-tests", "task:t1", "task:t2"]


def test_a_used_up_grace_escalates_with_the_reason(planned, capsys):  # AC-131.16
    planned.behave({"verification": ["partial"] * 40})                 # commits but never reaches the checkpoint
    assert planned.run("--budget", "invocations=4") == 1
    out = capsys.readouterr().out
    assert "budget exhausted: invocations (grace used)" in out
    assert "land" not in planned.units_run()
    assert planned.units_run().count("verification") == 10            # the grace adds max(10, ceil(0.2 * 4)) invocations


# ---------------- AC-131.19: runs of platform 5.5 ----------------

def test_a_5_5_run_resumes_without_a_question(planned, capsys):  # AC-131.19
    ship.start(planned.repo, "7", True)                               # phase build, as 5.5 left it
    git(planned.repo, "checkout", "-qb", BRANCH)
    import spec
    spec.task_done(spec.find(planned.repo, "7"), "t1")
    git(planned.repo, "add", "-A")
    git(planned.repo, "commit", "-qm", "feat: t1")
    assert not (planned.repo / ".git" / "cplat-units.json").exists()
    assert planned.run() == 0
    assert planned.units_run() == ["red-tests", "task:t2", "task:t3", "verification", "land"]
    assert "HEADLESS shop-api: shipped" in capsys.readouterr().out
