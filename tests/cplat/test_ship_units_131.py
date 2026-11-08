"""Spec 131 acceptance tests: `ship.py` knows the units (design.md "Units", "Stop hook in a unit session").

`ship.gate` with `CPLAT_UNIT`, the units block of `cplat component ship status`, `cplat component ship unit`, the rescale on
`phase build` and the end of the grace on `phase pr`.
"""
import importlib
import json

import pytest

import budget
import ship
import spec
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import repo  # noqa: F401  (fixture)
from units131_support import BRANCH, SPEC_ID, git, head, make_repo, plan_for



@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    """Spec 159: these tests are about units as spec 131 made them; batch units are tested in test_159_batch_units.py."""
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")

def units():
    return importlib.import_module("units")


def mark_done(repo, task):
    spec.task_done(spec.find(repo, "7"), task)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"feat: {task}")


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_SESSION_ID", raising=False)
    monkeypatch.delenv("CPLAT_UNIT", raising=False)


def status(repo, capsys, *args):
    capsys.readouterr()
    assert ship.main(["--repo", str(repo), "status", *args]) == 0
    return capsys.readouterr().out


# ---------------- AC-131.2: the hook in a unit session ----------------

def test_ship_gate_with_a_unit_holds_a_session_that_has_not_finished_its_unit(repo, monkeypatch):  # AC-131.2
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    units().prepare(repo, "ship", SPEC_ID)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    ans = ship.gate(repo, {"session_id": "S", "cwd": str(repo)}, run_tests=False)
    assert ans["decision"] == "block" and ans["reason"].startswith(f"Unit task:t1 of {SPEC_ID} is not finished")
    assert ship.gate(repo, {"session_id": "S", "cwd": str(repo)}, run_tests=False) is None      # no new commit: it stops
    assert not ship.load_state(repo).get("escalated")                                           # a unit session is never escalated


def test_ship_gate_with_a_unit_lets_a_session_at_its_checkpoint_stop(repo, monkeypatch):  # AC-131.2
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    units().prepare(repo, "ship", SPEC_ID)
    mark_done(repo, "t1")
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    assert ship.gate(repo, {"session_id": "S", "cwd": str(repo)}, run_tests=False) is None


def test_ship_gate_with_a_unit_works_without_a_ship_state(repo, monkeypatch):  # AC-131.2
    git(repo, "checkout", "-qb", BRANCH)
    units().prepare(repo, "build", SPEC_ID)
    monkeypatch.setenv("CPLAT_UNIT", "task:t2")
    assert ship.gate(repo, {"session_id": "S", "cwd": str(repo)}, run_tests=False)["decision"] == "block"


def test_the_unit_hold_ignores_the_owner_logic_of_126(repo, monkeypatch):  # AC-131.2
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "A")
    ship.start(repo, "7", True)                                       # A owns the run
    git(repo, "checkout", "-qb", BRANCH)
    units().prepare(repo, "ship", SPEC_ID)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    assert ship.gate(repo, {"session_id": "B", "cwd": str(repo)}, run_tests=False)["decision"] == "block"


# ---------------- AC-131.7: the status ----------------

def test_the_status_lists_every_unit_with_state_sessions_and_checkpoint(repo, capsys):  # AC-131.7
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    u = units()
    u.prepare(repo, "ship", SPEC_ID)
    plan_sha = head(repo)                                 # the head prepare() derived the plan checkpoint at
    mark_done(repo, "t1")
    u.start_session(repo, "task:t2", "s1")
    out = status(repo, capsys)
    assert f"ship {SPEC_ID}: phase build" in out
    assert "  units:\n" in out
    rows = out.split("  units:\n")[1].splitlines()
    assert rows[0].startswith("    plan ")
    by_id = {r.split()[0]: r.split() for r in rows if r.startswith("    ") and not r.startswith("next")}
    assert list(by_id) == ["plan", "red-tests", "task:t1", "task:t2", "task:t3", "verification", "land"]
    assert by_id["plan"][1] == "done" and by_id["plan"][-1] == plan_sha[:7]
    assert by_id["task:t1"][1] == "done" and by_id["task:t1"][-1] == head(repo)[:7]
    assert by_id["task:t2"][1:4] == ["running", "1", "session"] and by_id["task:t2"][-1] == "-"
    assert by_id["task:t3"][1:4] == ["open", "0", "sessions"]


def test_the_status_json_lists_the_units(repo, capsys):  # AC-131.7
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    units().prepare(repo, "ship", SPEC_ID)
    mark_done(repo, "t1")
    units().prepare(repo, "ship", SPEC_ID)
    data = json.loads(status(repo, capsys, "--json"))
    rows = {u["id"]: u for u in data["units"]}
    assert set(rows["task:t1"]) == {"id", "status", "sessions", "commit"}
    assert rows["task:t1"]["status"] == "done" and rows["task:t1"]["commit"] == head(repo)
    assert rows["task:t2"]["status"] == "open" and rows["task:t2"]["commit"] is None


def test_the_status_without_a_units_file_is_unchanged(repo, capsys):  # AC-131.7
    ship.start(repo, "7", True)
    out = status(repo, capsys)
    assert "units:" not in out and "units" not in json.loads(status(repo, capsys, "--json"))


def test_a_build_without_a_ship_state_prints_the_units(repo, capsys):  # AC-131.7
    units().prepare(repo, "build", SPEC_ID)
    out = status(repo, capsys)
    assert out.startswith(f"build {SPEC_ID}:") and "    plan " in out and "    land " in out


def test_the_status_of_a_derived_5_5_run_shows_its_checkpoints(repo, capsys):  # AC-131.19
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    mark_done(repo, "t1")
    units().prepare(repo, "ship", SPEC_ID)
    rows = {u["id"]: u for u in json.loads(status(repo, capsys, "--json"))["units"]}
    assert rows["plan"]["status"] == "done" and rows["task:t1"]["status"] == "done" and rows["task:t2"]["status"] == "open"


def test_the_unit_command_tells_whether_the_unit_has_its_checkpoint(repo, capsys, monkeypatch):  # AC-131.7
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    units().prepare(repo, "ship", SPEC_ID)
    capsys.readouterr()
    assert ship.main(["--repo", str(repo), "unit"]) == 2
    assert "not a unit session" in capsys.readouterr().out
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    assert ship.main(["--repo", str(repo), "unit"]) == 0
    assert capsys.readouterr().out.startswith("unit task:t1: open: ")
    mark_done(repo, "t1")
    assert ship.main(["--repo", str(repo), "unit"]) == 0
    assert capsys.readouterr().out.strip() == f"unit task:t1: done at {head(repo)[:7]}"


# ---------------- AC-131.14: rescale on phase build ----------------

def test_phase_build_raises_the_limits_to_the_plan(tmp_path, store):  # AC-131.14
    r = make_repo(tmp_path, plan=False, tasks=8, acs=14)
    st = ship.start(r, "7", True)                                     # phase plan: no plan yet
    rid = st["run_id"]
    assert budget.find(rid)[1]["limits"]["cost"] == 15
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(plan_for(8, 14, spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash()))
    ship.set_phase(r, "build")
    data = budget.find(rid)[1]
    assert data["limits"] == {"minutes": 250, "invocations": 74, "reruns": 6, "cost": 29}
    assert data["changes"][-1]["reason"] == f"plan of {SPEC_ID}: T=8, C=14"


# ---------------- AC-131.15: the grace ends at the PR ----------------

def test_phase_pr_ends_the_grace(repo, store):  # AC-131.15
    st = ship.start(repo, "7", True)
    rid = st["run_id"]
    path, data = budget.find(rid)
    data["grace"] = {"for": "verification", "limit": "invocations", "granted_at": "2026-10-24T08:00:00Z", "state": "active",
                     "add": {"minutes": 30, "invocations": 10, "cost": 3, "reruns": 2}}
    budget._write(path, data)
    ship.set_phase(repo, "pr")
    assert budget.find(rid)[1]["grace"]["state"] == "ended"
