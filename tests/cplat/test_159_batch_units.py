"""Spec 159 acceptance tests: unit mode runs independent tasks at once, in one batch unit.

Seams: `units.py` on a real git repo (`units131_support.make_repo`, the plan of `test_spec.PLAN`: t1 and t2 `parallel_safe`
with disjoint files, t3 depending on both), and the spec 131 world (`units131_support.World`: a fake `claude` that does one
unit per session; for `batch:` units it marks the batch's tasks done, or only the first with behaviour `first-only`).
"""
import importlib
from pathlib import Path

import pytest

import spec
from units131_support import SPEC_ID, World, git, make_repo, plan_for

ROOT = Path(__file__).resolve().parents[2]


def units():
    return importlib.import_module("units")


def ids(data):
    return [u["id"] for u in data["units"]]


def with_plan(tmp_path, tasks, edit=None):
    r = make_repo(tmp_path, plan=False)
    text = plan_for(tasks, 3, spec.read(r / "docs" / "specs" / SPEC_ID).ac_hash())
    (r / "docs" / "specs" / SPEC_ID / "plan.md").write_text(edit(text) if edit else text)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "plan")
    return r


# ---------------- AC-159.1: one unit per batch, at most --parallel tasks ----------------

def test_independent_tasks_share_a_batch_unit_and_a_dependent_one_follows_ac_159_1_ac_159_5(tmp_path):  # AC-159.1, AC-159.5
    r = make_repo(tmp_path)
    assert ids(units().prepare(r, "ship", SPEC_ID)) == ["plan", "red-tests", "batch:t1,t2", "task:t3", "verification", "land"]


def test_a_batch_holds_at_most_parallel_tasks_ac_159_1(tmp_path, monkeypatch):  # AC-159.1
    r = with_plan(tmp_path, 5)
    assert ids(units().prepare(r, "ship", SPEC_ID))[2:4] == ["batch:t1,t2,t3", "batch:t4,t5"]      # the default, 3
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "2")
    assert ids(units().prepare(r, "ship", SPEC_ID))[2:5] == ["batch:t1,t2", "batch:t3,t4", "task:t5"]


def test_tasks_sharing_a_file_never_share_a_batch_ac_159_1(tmp_path):  # AC-159.1
    r = with_plan(tmp_path, 3, lambda t: t.replace("files: [f2.py]", "files: [f1.py]"))
    assert ids(units().prepare(r, "ship", SPEC_ID))[2:4] == ["batch:t1,t3", "task:t2"]


def test_a_task_not_parallel_safe_is_a_unit_of_its_own_ac_159_5(tmp_path):  # AC-159.5
    r = with_plan(tmp_path, 3, lambda t: t.replace("id: t2, title: task 2, files: [f2.py], covers: [AC-007.2], parallel_safe: true",
                                                       "id: t2, title: task 2, files: [f2.py], covers: [AC-007.2], parallel_safe: false"))
    assert ids(units().prepare(r, "ship", SPEC_ID))[2:4] == ["batch:t1,t3", "task:t2"]


def test_parallel_1_keeps_one_unit_per_task_ac_159_8(tmp_path, monkeypatch):  # AC-159.8
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")
    r = make_repo(tmp_path)
    assert ids(units().prepare(r, "ship", SPEC_ID))[2:5] == ["task:t1", "task:t2", "task:t3"]


def test_headless_passes_parallel_to_units_and_sessions_ac_159_1(monkeypatch):  # AC-159.1
    import os

    import headless
    from core import PlatformError
    monkeypatch.setattr(headless, "settings", type("S", (), {"coordinator_model": staticmethod(lambda *a: ("sonnet", "test"))}))
    with pytest.raises(PlatformError, match="at least 1"):
        headless.main(["--parallel", "0", "--dry-run", "/component:build 7"])
    headless.main(["--parallel", "2", "--dry-run", "/component:build 7"])
    assert os.environ["CPLAT_PARALLEL_TASKS"] == "2"


# ---------------- AC-159.2 / AC-159.4: done when every task is, and a partly done batch ----------------

def test_a_batch_is_done_only_when_all_its_tasks_are_ac_159_2(tmp_path):  # AC-159.2
    r = make_repo(tmp_path)
    git(r, "checkout", "-q", "-B", f"feature/{SPEC_ID}")
    u = units()
    spec.task_done(spec.find(r, "7"), "t1")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "feat: t1")
    assert u.detect(r, "ship", SPEC_ID, "batch:t1,t2") is None
    assert "`done: true` for t2 in a commit" in u.missing(r, "ship", SPEC_ID, "batch:t1,t2")
    spec.task_done(spec.find(r, "7"), "t2")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "feat: t2")
    assert u.detect(r, "ship", SPEC_ID, "batch:t1,t2") == git(r, "rev-parse", "HEAD")


def test_the_next_step_of_a_batch_names_its_tasks_and_the_merge_ac_159_2():  # AC-159.2
    step = units().next_step("batch:t1,t2", SPEC_ID)
    assert "tasks t1, t2" in step and "cplat component build merge" in step  # interface: next_step output names the merge command


@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=False)


def test_a_ship_runs_one_session_for_the_batch_ac_159_1_ac_159_6(w):  # AC-159.1, AC-159.6
    assert w.run() == 0
    assert w.units_run() == ["plan", "red-tests", "batch:t1,t2", "task:t3", "verification", "land"]
    assert [s["argv"][1] for s in w.sessions()][2] == "/component:ship 7 --unit batch:t1,t2"


def test_a_partly_done_batch_runs_again_for_the_rest_and_is_no_stall_ac_159_4(w):  # AC-159.4
    w.behave({"batch:t1,t2": ["first-only", "ok"]})
    assert w.run() == 0
    assert w.units_run() == ["plan", "red-tests", "batch:t1,t2", "batch:t1,t2", "task:t3", "verification", "land"]
    lines = [ln for ln in w.summary() if "unit batch:t1,t2" in ln]
    assert "session 1: no checkpoint" in lines[0] and "session 2: checkpoint" in lines[1]     # moved the head: no stall


@pytest.mark.usefixtures("silent_sessions_are_not_pauses")
def test_a_batch_session_without_progress_stalls_as_any_unit_ac_159_4(w):  # AC-159.4
    w.behave({"batch:t1,t2": ["nothing", "nothing"]})
    assert w.run() != 0
    assert w.units_run().count("batch:t1,t2") == 2 and "task:t3" not in w.units_run()


# ---------------- AC-159.3 / AC-159.7: the batch follows build Phase 2 ----------------

def test_the_batch_unit_runs_build_phase_2s_parallel_batch_ac_159_2_ac_159_3_ac_159_7():  # AC-159.2, AC-159.3, AC-159.7
    text = (ROOT / "plugins" / "component" / "references" / "unit-mode.md").read_text()
    row = next(ln for ln in text.splitlines() if ln.startswith("| `batch:"))
    assert 'isolation: \\"worktree\\"' not in row and "worktree" in row
    assert "build merge" in row and "re-plan rule" in row
    assert "build-worktree-fallback.md" in row


def test_the_supervisor_docs_name_batch_units_ac_159_1():  # AC-159.1
    text = (ROOT / "scripts" / "cplat" / "headless.py").read_text()
    assert "--parallel N" in text and "spec 159" in text
