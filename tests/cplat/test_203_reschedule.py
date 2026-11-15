"""Spec 203 acceptance tests: a changed committed plan reschedules the units before the next unit (AC-203.3, AC-203.4).

Seams (design.md): `units.plan_key(sp)`, `units.reschedule(repo, command, spec_id)`, `units.prepare` on a real git repo
(`units131_support.make_repo`, the plan of `test_spec.PLAN`: t1 and t2 independent, t3 after both), and the spec 131 supervisor
world (`units131_support.World`: a fake `claude` that does one unit per session). A plan change is made like an answered
escalation makes it: a commit on the feature branch after a unit's session (`supervisor._run_session` wrapped).
"""
import copy
import importlib

import pytest
import yaml

import buildcmd
import headless
import spec
import supervisor
from units131_support import SPEC_ID, World, git, make_repo


@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")


def units():
    return importlib.import_module("units")


def put_plan(repo, edit, body=None, msg="plan: change"):
    """Rewrite plan.md by `edit(tasks)` (task dicts, `done` flags kept) and commit it on the current branch."""
    d = repo / "docs" / "specs" / SPEC_ID
    meta, text = spec.read(d).plan
    meta = copy.deepcopy(meta)
    edit(meta["tasks"])
    (d / "plan.md").write_text("---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\n" + (text if body is None else body))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


def add_t0(tasks):
    """The journey's change: a new first task that the last task depends on."""
    tasks.append({"id": "t0", "title": "prepare", "files": ["z.py"], "covers": ["AC-007.1"], "parallel_safe": True, "depends_on": []})
    next(t for t in tasks if t["id"] == "t3")["depends_on"].append("t0")


def mark_done(tasks, *ids):
    for t in tasks:
        if t["id"] in ids:
            t["done"] = True


def ids_of(data):
    return [u["id"] for u in data["units"]]


def entry(data, unit):
    return next(u for u in data["units"] if u["id"] == unit)


def committed(repo):
    u = units()
    return u._committed(repo, SPEC_ID, u.feature_head(repo, SPEC_ID))


def started(tmp_path, done=("t1",)):
    """A repo whose units file exists and whose `done` tasks have checkpoints."""
    r = make_repo(tmp_path)
    u = units()
    u.prepare(r, "ship", SPEC_ID)
    if done:
        put_plan(r, lambda ts: mark_done(ts, *done))
        u.prepare(r, "ship", SPEC_ID)
    return r


# ---------------- plan_key: only ids, files and dependencies count (A5) ----------------

def test_the_plan_key_follows_ids_files_and_dependencies_only_ac_203_4(tmp_path):  # AC-203.4
    r = make_repo(tmp_path)
    u = units()
    base = u.plan_key(committed(r))
    assert base and len(base) == 12

    def key_after(edit, body=None):
        put_plan(r, edit, body)
        return u.plan_key(committed(r))
    same = [lambda ts: ts[0].update(title="a new title"), lambda ts: ts[0].update(covers=["AC-007.1", "AC-007.2"]),
            lambda ts: mark_done(ts, "t1")]
    for edit in same:
        assert key_after(edit) == base
    assert key_after(lambda ts: None, "## t1 - other words\n\nA longer description.\n") == base
    for edit in (add_t0, lambda ts: ts[2].update(depends_on=["t1"]), lambda ts: ts[0].update(files=["a.py", "q.py"]),
                 lambda ts: ts.pop(1)):
        key = key_after(edit)
        assert key != base
        git(r, "reset", "-q", "--hard", "HEAD~1")


def test_a_repo_without_a_plan_has_no_plan_key_ac_203_4(tmp_path):  # AC-203.4
    r = make_repo(tmp_path, plan=False)
    assert units().plan_key(committed(r)) is None


# ---------------- AC-203.3: the next unit comes from the changed plan ----------------

def test_a_new_task_runs_before_its_dependants_and_done_units_keep_their_checkpoint_ac_203_3(tmp_path):  # AC-203.3
    r = started(tmp_path)
    u = units()
    before = entry(u._read(r), "task:t1")
    assert before["status"] == "done" and before["commit"]
    put_plan(r, add_t0)
    result = u.reschedule(r, "ship", SPEC_ID)
    assert result and "error" not in result and "task:t0" in result["new"] and "task:t0" not in result["old"]
    data = u._read(r)
    ids = ids_of(data)
    assert ids.index("task:t0") < ids.index("task:t3")
    assert ids.count("task:t1") == 1 and entry(data, "task:t1") == before        # not run again, nothing changed
    assert u.next_open(data) not in {"task:t1", "task:t3"}
    assert not data.get("escalated")


def test_the_build_schedule_shows_the_new_batches_at_once_ac_203_3(tmp_path):  # AC-203.3
    r = started(tmp_path)
    u = units()
    put_plan(r, add_t0)
    assert u.reschedule(r, "ship", SPEC_ID)
    levels = buildcmd.schedule(r, "7")["levels"]
    flat = [t for level in levels for batch in level for t in batch["tasks"]]
    assert "t0" in flat and flat.index("t0") < flat.index("t3") and "t1" not in flat


def test_a_removed_task_leaves_the_units_and_a_second_reschedule_changes_nothing_ac_203_3(tmp_path):  # AC-203.3
    r = started(tmp_path)
    u = units()
    put_plan(r, lambda ts: (ts.pop(1), next(t for t in ts if t["id"] == "t3").update(depends_on=["t1"])))
    result = u.reschedule(r, "ship", SPEC_ID)
    assert result and "task:t2" in result["old"] and "task:t2" not in result["new"]
    assert "task:t2" not in ids_of(u._read(r))
    assert u.reschedule(r, "ship", SPEC_ID) is None                              # the plan did not change again


def test_a_changed_dependency_is_a_change_of_the_plan_ac_203_3(tmp_path):  # AC-203.3
    r = started(tmp_path, done=())
    u = units()
    old_key = u._read(r)["plan_key"]
    put_plan(r, lambda ts: next(t for t in ts if t["id"] == "t3").update(depends_on=["t1"]))
    u.reschedule(r, "ship", SPEC_ID)
    assert u._read(r)["plan_key"] == u.plan_key(committed(r)) != old_key


def test_an_uncommitted_plan_change_changes_nothing_ac_203_3(tmp_path):  # AC-203.3
    r = started(tmp_path)
    u = units()
    before = u._read(r)
    d = r / "docs" / "specs" / SPEC_ID
    meta, body = spec.read(d).plan
    add_t0(meta["tasks"])
    (d / "plan.md").write_text("---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\n" + body)   # working tree only
    assert u.reschedule(r, "ship", SPEC_ID) is None
    assert ids_of(u._read(r)) == ids_of(before)


# ---------------- AC-203.4: replaced units start fresh, text changes nothing, a bad plan escalates ----------------

def test_a_batch_that_gained_a_task_is_replaced_by_a_fresh_unit_ac_203_4(tmp_path, monkeypatch):  # AC-203.4
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "3")
    r = make_repo(tmp_path)
    u = units()
    data = u.prepare(r, "ship", SPEC_ID)
    assert "batch:t1,t2" in ids_of(data)
    u.start_session(r, "batch:t1,t2")
    u.end_session(r, "ship", SPEC_ID, "batch:t1,t2", u.feature_head(r, SPEC_ID))       # a session without a checkpoint: one stall
    assert entry(u._read(r), "batch:t1,t2")["sessions"] == 1

    def add_t4(tasks):
        tasks.append({"id": "t4", "title": "more", "files": ["y.py"], "covers": ["AC-007.2"], "parallel_safe": True, "depends_on": []})
    put_plan(r, add_t4)
    result = u.reschedule(r, "ship", SPEC_ID)
    assert result and "batch:t1,t2" in result["old"] and "batch:t1,t2,t4" in result["new"]
    data = u._read(r)
    assert "batch:t1,t2" not in ids_of(data)
    fresh = entry(data, "batch:t1,t2,t4")
    assert (fresh["status"], fresh["sessions"], fresh["stalls"], fresh["commit"]) == ("open", 0, 0, None)


def test_a_task_merged_into_another_leaves_its_unit_ac_203_4(tmp_path):  # AC-203.4
    r = started(tmp_path, done=())
    u = units()
    assert "task:t3" in ids_of(u._read(r))

    def merge(tasks):                  # t3 merged into t2
        t2 = next(t for t in tasks if t["id"] == "t2")
        t2.update(files=["b.py", "c.py"], covers=["AC-007.1", "AC-007.2"])
        tasks.remove(next(t for t in tasks if t["id"] == "t3"))
    put_plan(r, merge)
    result = u.reschedule(r, "ship", SPEC_ID)
    assert result and "task:t3" in result["old"] and "task:t3" not in result["new"]
    assert "task:t3" not in ids_of(u._read(r))


def test_a_change_of_the_text_only_changes_no_unit_ac_203_4(tmp_path):  # AC-203.4
    r = started(tmp_path)
    u = units()
    u.start_session(r, "task:t2")
    u.end_session(r, "ship", SPEC_ID, "task:t2", u.feature_head(r, SPEC_ID))
    before = u._read(r)["units"]
    put_plan(r, lambda ts: ts[1].update(title="hook, reworded"), "## t2 - reworded\n\nNothing about files or dependencies changed.\n")
    assert u.reschedule(r, "ship", SPEC_ID) is None
    assert u._read(r)["units"] == before                                       # sessions, stalls and checkpoints too


def test_a_changed_plan_that_fails_the_check_returns_its_first_error_and_writes_nothing_ac_203_4(tmp_path):  # AC-203.4
    r = started(tmp_path)
    u = units()
    stored = u._path(r).read_text()
    put_plan(r, lambda ts: ts[1].update(depends_on=["tX"]))
    sp = committed(r)
    first = spec.check_plan(sp, *sp.plan)[0]
    result = u.reschedule(r, "ship", SPEC_ID)
    assert result == {"error": first} and "tX" in first
    assert u._path(r).read_text() == stored


# ---------------- the supervisor: the run goes on from the changed plan ----------------

def change_plan_after(monkeypatch, unit, edit):
    """After the session of `unit` the plan is changed and committed, once (as an answered escalation does)."""
    real, fired = supervisor._run_session, []

    def wrapped(h, cmd, repo, log, minutes, rid, sid, env):
        code = real(h, cmd, repo, log, minutes, rid, sid, env)
        if env.get("CPLAT_UNIT") == unit and not fired:
            fired.append(unit)
            put_plan(repo, edit, msg="plan: answer adds a task")
        return code
    monkeypatch.setattr(supervisor, "_run_session", wrapped)


@pytest.fixture()
def planned(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=True)


def test_the_run_goes_on_from_the_changed_plan_and_never_runs_a_done_unit_again_ac_203_3(planned, monkeypatch, capsys):  # AC-203.3
    change_plan_after(monkeypatch, "task:t1", add_t0)
    assert planned.run() == 0
    run = planned.units_run()
    assert run.count("task:t1") == 1 and run.count("task:t0") == 1
    assert run.index("task:t0") < run.index("task:t3")
    assert run[-2:] == ["verification", "land"]
    assert not (planned.units_file() or {}).get("escalated")
    import ship
    assert not (ship.load_state(planned.repo) or {}).get("escalated")


def test_a_changed_plan_that_fails_its_check_escalates_with_cause_code_and_starts_no_unit_ac_203_4(planned, monkeypatch, capsys):  # AC-203.4
    change_plan_after(monkeypatch, "task:t1", lambda ts: ts[1].update(depends_on=["tX"]))
    assert planned.run() == headless.EXIT_STOPPED
    assert planned.units_run() == ["red-tests", "task:t1"]                       # no unit starts after the change
    import ship
    st = ship.load_state(planned.repo)
    assert st["cause"] == "code" and "tX" in st["escalated"]
