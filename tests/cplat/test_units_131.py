"""Spec 131 acceptance tests: `units.py` (design.md "Units" and "Stop hook in a unit session").

The unit list, the completion rules that read only the committed tree of the feature head, checkpoints and their validity, the
stall count, the 5.5 derivation and the unit Stop-hook answer. The module does not exist yet, so it is imported inside the tests.
The state file is `<git dir>/cplat-units.json`.
"""
import importlib
import json
import subprocess

import pytest

import ship
import spec
from test_spec import PLAN
from units131_support import BRANCH, SPEC_ID, commit, git, head, make_repo, plan_text



@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    """Spec 159: these tests are about units as spec 131 made them; batch units are tested in test_159_batch_units.py."""
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")

def units():
    return importlib.import_module("units")


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path)


def ids(data):
    return [u["id"] for u in data["units"]]


def status_of(data, unit):
    return next(u for u in data["units"] if u["id"] == unit)


def mark_done(repo, task, commit_it=True):
    spec.task_done(spec.find(repo, "7"), task)
    if commit_it:
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", f"feat: {task}")


# ---------------- AC-131.1: the unit list ----------------

def test_the_units_of_a_plan_with_3_tasks_are_7_in_dependency_order(repo):  # AC-131.1
    data = units().prepare(repo, "ship", SPEC_ID)
    assert ids(data) == ["plan", "red-tests", "task:t1", "task:t2", "task:t3", "verification", "land"]
    assert all(u["status"] in {"open", "done"} for u in data["units"])


def test_the_units_before_the_plan_exists(tmp_path):  # AC-131.1
    r = make_repo(tmp_path, plan=False)
    assert ids(units().prepare(r, "ship", SPEC_ID)) == ["plan", "red-tests", "verification", "land"]


def test_task_units_follow_the_levels_and_the_plan_order_inside_a_level(tmp_path):  # AC-131.1
    r = make_repo(tmp_path, plan=False)
    text = PLAN.format(hash=spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash())
    # t2 is declared before t1 and both are level 1; t3 depends on both
    lines = text.splitlines()
    i1 = next(i for i, ln in enumerate(lines) if "id: t1" in ln)
    i2 = next(i for i, ln in enumerate(lines) if "id: t2" in ln)
    lines[i1], lines[i2] = lines[i2], lines[i1]
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text("\n".join(lines) + "\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "plan")
    assert ids(units().prepare(r, "ship", SPEC_ID))[2:5] == ["task:t2", "task:t1", "task:t3"]


def test_the_state_file_lives_in_the_git_dir_and_has_the_documented_shape(repo):  # AC-131.1
    units().prepare(repo, "ship", SPEC_ID)
    data = json.loads((repo / ".git" / "cplat-units.json").read_text())
    assert data["version"] == 1 and data["command"] == "ship" and data["spec"] == SPEC_ID
    assert data["derived"] is None and data["escalated"] is None
    assert set(data["units"][0]) >= {"id", "status", "sessions", "stalls", "commit", "at", "hold"}
    assert "cplat-units.json" not in git(repo, "ls-files")


# ---------------- AC-131.3: completion rules and checkpoints ----------------

def test_the_plan_unit_is_complete_when_the_committed_plan_checks(repo):  # AC-131.3
    u = units()
    assert u.detect(repo, "ship", SPEC_ID, "plan") == head(repo)


def test_the_plan_unit_is_open_without_a_committed_plan(tmp_path):  # AC-131.3
    r = make_repo(tmp_path, plan=False)
    u = units()
    assert u.detect(r, "ship", SPEC_ID, "plan") is None
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(plan_text(r))   # written but not committed: does not count
    assert u.detect(r, "ship", SPEC_ID, "plan") is None
    git(r, "add", "-A")
    git(r, "commit", "-qm", "plan")
    assert u.detect(r, "ship", SPEC_ID, "plan") == head(r)


def test_a_stale_plan_does_not_complete_the_plan_unit(tmp_path):  # AC-131.3
    r = make_repo(tmp_path, plan=False)
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(PLAN.format(hash="stale"))
    git(r, "add", "-A")
    git(r, "commit", "-qm", "plan")
    assert units().detect(r, "ship", SPEC_ID, "plan") is None


def test_a_task_unit_counts_only_the_committed_done_flag(repo):  # AC-131.3
    u = units()
    assert u.detect(repo, "ship", SPEC_ID, "task:t1") is None
    mark_done(repo, "t1", commit_it=False)
    assert u.detect(repo, "ship", SPEC_ID, "task:t1") is None          # in the working tree only
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "feat: t1")
    assert u.detect(repo, "ship", SPEC_ID, "task:t1") == head(repo)
    assert u.detect(repo, "ship", SPEC_ID, "task:t2") is None


def test_the_red_tests_unit_needs_a_traced_acceptance_test_commit(repo):  # AC-131.3
    u = units()
    assert u.detect(repo, "ship", SPEC_ID, "red-tests") is None
    (repo / "tests").mkdir()
    (repo / "tests" / "test_alerts.py").write_text("# AC-007.1 AC-007.2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wip tests")                             # traced, but not an acceptance tests commit
    assert u.detect(repo, "ship", SPEC_ID, "red-tests") is None
    git(repo, "checkout", "-qb", BRANCH)
    commit(repo, "more.txt", "test(007): acceptance tests for AC-007.1-AC-007.2")
    assert u.detect(repo, "ship", SPEC_ID, "red-tests") == head(repo)


def test_a_checkpointed_unit_is_not_started_again_and_a_dropped_commit_reopens_it(repo):  # AC-131.3
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    mark_done(repo, "t1")
    first = head(repo)
    data = u.prepare(repo, "ship", SPEC_ID)
    assert status_of(data, "task:t1")["status"] == "done" and status_of(data, "task:t1")["commit"] == first
    commit(repo, "g.txt", "feat: more")
    git(repo, "reset", "-q", "--hard", "HEAD~2")                         # the commit of t1 is no longer on the branch
    again = u.prepare(repo, "ship", SPEC_ID)
    t1 = status_of(again, "task:t1")
    assert t1["status"] == "open" and t1["commit"] is None


def test_a_checkpoint_survives_further_commits(repo):  # AC-131.3
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    mark_done(repo, "t1")
    sha = head(repo)
    u.prepare(repo, "ship", SPEC_ID)
    commit(repo, "g.txt", "feat: other work")
    data = u.prepare(repo, "ship", SPEC_ID)
    assert status_of(data, "task:t1")["commit"] == sha and status_of(data, "task:t1")["status"] == "done"


# ---------------- AC-131.4: an interrupted supervisor ----------------

def test_a_unit_left_running_by_a_killed_supervisor_is_open_again_with_its_sessions_kept(repo):  # AC-131.4
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    u.prepare(repo, "ship", SPEC_ID)
    u.start_session(repo, "task:t1", "sid-1")
    running = json.loads((repo / ".git" / "cplat-units.json").read_text())
    assert status_of(running, "task:t1")["status"] == "running" and status_of(running, "task:t1")["sessions"] == 1
    data = u.prepare(repo, "ship", SPEC_ID)                              # the same command started again
    t1 = status_of(data, "task:t1")
    assert t1["status"] == "open" and t1["sessions"] == 1
    assert status_of(data, "plan")["status"] == "done"                   # what had a checkpoint stays done


def test_a_broken_state_file_is_recreated(repo):  # AC-131.4
    (repo / ".git" / "cplat-units.json").write_text("{not json")
    assert ids(units().prepare(repo, "ship", SPEC_ID))[0] == "plan"


# ---------------- AC-131.5: stalls ----------------

def test_the_stall_limit_is_two():  # AC-131.5
    assert units().STALL_LIMIT == 2


def test_sessions_without_a_commit_count_as_stalls_and_a_commit_resets_them(repo):  # AC-131.5
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    u.prepare(repo, "ship", SPEC_ID)

    def session(commit_something):
        before = head(repo)
        u.start_session(repo, "task:t1", "sid")
        if commit_something:
            commit(repo, "w.txt", "wip")
        u.end_session(repo, "ship", SPEC_ID, "task:t1", before)
        return status_of(json.loads((repo / ".git" / "cplat-units.json").read_text()), "task:t1")

    assert session(False)["stalls"] == 1
    assert session(True)["stalls"] == 0                                  # a commit without the checkpoint resets the count
    assert session(False)["stalls"] == 1
    last = session(False)
    assert last["stalls"] == 2 and last["status"] == "open" and last["sessions"] == 4


def test_a_session_that_reaches_the_checkpoint_records_the_commit(repo):  # AC-131.5
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    u.prepare(repo, "ship", SPEC_ID)
    before = head(repo)
    u.start_session(repo, "task:t1", "sid")
    mark_done(repo, "t1")
    u.end_session(repo, "ship", SPEC_ID, "task:t1", before)
    t1 = status_of(json.loads((repo / ".git" / "cplat-units.json").read_text()), "task:t1")
    assert t1["status"] == "done" and t1["commit"] == head(repo) and t1["stalls"] == 0


# ---------------- AC-131.2: the Stop hook answer of a unit session ----------------

def hook(repo, **extra):
    return {"session_id": "S", "cwd": str(repo), **extra}


def test_a_session_that_has_not_reached_its_checkpoint_is_held_once_per_head(repo):  # AC-131.2
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    u.prepare(repo, "ship", SPEC_ID)
    first = u.gate(repo, "task:t1", hook(repo))
    assert first["decision"] == "block"
    assert first["reason"].startswith(f"Unit task:t1 of {SPEC_ID} is not finished: ")
    assert "Commit your work. Stop when the unit is done; never start another unit." in first["reason"]
    assert u.gate(repo, "task:t1", hook(repo)) is None                    # a stop without a new commit: the session stops
    commit(repo, "w.txt", "wip")
    assert u.gate(repo, "task:t1", hook(repo))["decision"] == "block"     # new work: held once more


def test_a_session_at_its_checkpoint_is_let_go_and_the_checkpoint_is_recorded(repo):  # AC-131.2
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    u.prepare(repo, "ship", SPEC_ID)
    mark_done(repo, "t1")
    assert u.gate(repo, "task:t1", hook(repo)) is None
    data = json.loads((repo / ".git" / "cplat-units.json").read_text())
    assert status_of(data, "task:t1")["status"] == "done" and status_of(data, "task:t1")["commit"] == head(repo)


def test_an_escalated_units_file_lets_the_session_stop(repo):  # AC-131.2
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    u.prepare(repo, "ship", SPEC_ID)
    u.escalate(repo, "stuck on the database", "code")
    assert json.loads((repo / ".git" / "cplat-units.json").read_text())["escalated"] == {"reason": "stuck on the database", "cause": "code"}
    assert u.gate(repo, "task:t1", hook(repo)) is None


# ---------------- AC-131.19: runs of platform 5.5 ----------------

def test_a_5_5_run_in_phase_build_continues_at_the_first_unfinished_task(repo):  # AC-131.19
    u = units()
    ship.start(repo, "7", True)                                          # phase build, no units file (as 5.5 left it)
    git(repo, "checkout", "-qb", BRANCH)
    mark_done(repo, "t1")
    assert not (repo / ".git" / "cplat-units.json").exists()
    data = u.prepare(repo, "ship", SPEC_ID)
    assert data["derived"] == "5.5"
    assert status_of(data, "plan")["status"] == "done"
    assert status_of(data, "task:t1")["status"] == "done" and status_of(data, "task:t1")["commit"] == head(repo)
    assert status_of(data, "task:t2")["status"] == "open"
    assert status_of(data, "red-tests")["status"] == "open"              # found by the rule, not by the phase


@pytest.mark.parametrize("phase", ["pr", "land", "deploy"])
def test_a_5_5_run_after_the_build_has_everything_up_to_verification_checkpointed(repo, phase):  # AC-131.19
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    for t in ("t1", "t2", "t3"):
        mark_done(repo, t)
    ship.set_phase(repo, phase)
    data = units().prepare(repo, "ship", SPEC_ID)
    assert data["derived"] == "5.5"
    done = [x["id"] for x in data["units"] if x["status"] == "done"]
    assert done == ["plan", "red-tests", "task:t1", "task:t2", "task:t3", "verification"]
    assert status_of(data, "land")["status"] == "open"


def test_an_escalated_5_5_run_is_not_derived(repo):  # AC-131.19
    ship.start(repo, "7", True)
    ship.escalate(repo, "merge conflict", "code")
    data = units().prepare(repo, "ship", SPEC_ID)
    assert data["derived"] is None


# ---------------- AC-131.15: only verification left ----------------

def test_only_verification_left_with_a_units_file(repo):  # AC-131.15
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    u.prepare(repo, "ship", SPEC_ID)
    assert u.only_verification_left(repo) is False
    data = json.loads((repo / ".git" / "cplat-units.json").read_text())
    for x in data["units"]:
        if x["id"] not in {"verification", "land"}:
            x.update(status="done", commit=head(repo))
    (repo / ".git" / "cplat-units.json").write_text(json.dumps(data))
    assert u.only_verification_left(repo) is True
    for x in data["units"]:
        if x["id"] == "verification":
            x.update(status="done", commit=head(repo))
    (repo / ".git" / "cplat-units.json").write_text(json.dumps(data))
    assert u.only_verification_left(repo) is False                       # verification itself is done: nothing to grace


def test_only_verification_left_without_a_units_file_reads_the_ship_phase_and_the_plan(repo):  # AC-131.15
    u = units()
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    for t in ("t1", "t2", "t3"):
        mark_done(repo, t)
    assert u.only_verification_left(repo) is False                       # the red-tests commit is missing
    (repo / "tests").mkdir()
    (repo / "tests" / "test_alerts.py").write_text("# AC-007.1 AC-007.2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "test(007): acceptance tests for AC-007.1-AC-007.2")
    assert u.only_verification_left(repo) is True


def test_a_land_unit_left_done_by_an_earlier_run_reopens_unless_its_pr_is_found(repo, monkeypatch):  # AC-131.3
    """A benchmark reuses its clone: the units file of an earlier run of the same spec said land was done, so a later build
    stopped after verification without a PR (found by the 5.13.1 eval gate)."""
    u = units()
    git(repo, "checkout", "-qb", BRANCH)
    data = u.prepare(repo, "build", SPEC_ID)
    u._update(repo, lambda d: u._checkpoint(u._unit(d, "land"), "0" * 40))      # a commit this clone never had
    monkeypatch.setattr(u, "_pr_pushed", lambda repo, spec_id, head: False)
    assert status_of(u.prepare(repo, "build", SPEC_ID), "land")["status"] == "open"
    u._update(repo, lambda d: u._checkpoint(u._unit(d, "land"), "0" * 40))
    monkeypatch.setattr(u, "_pr_pushed", lambda repo, spec_id, head: True)      # a squash merge: its PR is still found
    assert status_of(u.prepare(repo, "build", SPEC_ID), "land")["status"] == "done"
