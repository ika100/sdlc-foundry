"""Spec 211 acceptance tests: less bookkeeping. `cplat quiet ci` records the gate and the stage (AC-211.7); the commands that start
a phase set its marker, forward only, in one run record (AC-211.9).

Seams: `quiet.main(["ci"])` with a fake `devbox` on PATH; `runs.main([...])` for begin/phase/gate on the spec 087 fixtures; `spec.main`,
`jbuild` and `mutation` for the commands that set a marker. The contract is design.md sections 4 and 5."""
import json
import os
import stat

import pytest

import budget
import quiet
import runs
import spec
from test_152_mutation import passing_when
from test_build_parallel_501 import _feature
from test_replan import jbuild
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import git, repo  # noqa: F401  (fixtures)
from waiting import fake_prelude

SPEC = "007-price-alerts"
MARKERS = ["build:tests", "build:implement", "build:qa", "build:verify", "build:image", "build:close"]
FAKE_DEVBOX = """#!/bin/sh
echo "ci output line"
exit "${FAKE_RC:-0}"
"""


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_UNIT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def ci_repo(repo, tmp_path, monkeypatch, store):
    """The spec 007 repo with a devbox.json that has a `ci` script, a fake `devbox` first on PATH, the cwd set to the repo."""
    (repo / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "x", "test-fast": "y"}}}))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "devbox"
    fake.write_text(FAKE_DEVBOX.replace("\n", "\n" + fake_prelude("sh") + "\n", 1))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.chdir(repo)
    return repo


def begin_build(repo, *extra):
    assert runs.main(["begin", "build", "--spec", SPEC, "--dir", str(repo), *extra]) == 0
    return runs.current_run(repo)


def record(rid):
    return runs.active(rid)


def build_markers(rid):
    return [p["name"] for p in record(rid)["phases"] if p["name"].startswith("build:")]


def stage_result(rid, name):
    stages = budget.find(rid)[1].get("stages") or {}
    return (stages.get(name) or {}).get("result")


# ---------------- AC-211.7: quiet ci ----------------

def test_a_green_ci_records_the_gate_and_the_stage_and_says_so_ac_211_7(ci_repo, capsys):  # AC-211.7
    rid = begin_build(ci_repo)
    capsys.readouterr()
    assert quiet.main(["ci"]) == 0
    out = capsys.readouterr().out
    assert f"recorded for build run {rid}: gate security passed, budget stage ci passed" in out.splitlines()
    assert record(rid)["gates"]["security"] == "passed" and stage_result(rid, "ci") == "passed"


def test_a_red_ci_records_only_the_stage_and_keeps_its_exit_code_ac_211_7(ci_repo, capsys, monkeypatch):  # AC-211.7
    rid = begin_build(ci_repo)
    monkeypatch.setenv("FAKE_RC", "1")
    capsys.readouterr()
    assert quiet.main(["ci"]) == 1
    out = capsys.readouterr().out
    assert f"recorded for build run {rid}: budget stage ci failed" in out.splitlines()
    assert (record(rid).get("gates") or {}).get("security") in (None, "not run") and stage_result(rid, "ci") == "failed"


def test_the_raw_form_records_too_ac_211_7(ci_repo, capsys):  # AC-211.7
    rid = begin_build(ci_repo)
    assert quiet.main(["--raw", "ci"]) == 0
    assert record(rid)["gates"]["security"] == "passed" and stage_result(rid, "ci") == "passed"


def test_a_build_run_inside_a_ship_is_recorded_on_the_ship_run_ac_211_7(ci_repo, capsys):  # AC-211.7
    import ship
    st = ship.start(ci_repo, "7", True)
    assert runs.main(["begin", "build", "--spec", SPEC, "--dir", str(ci_repo)]) == 0
    assert quiet.main(["ci"]) == 0
    assert record(st["run_id"])["gates"]["security"] == "passed" and stage_result(st["run_id"], "ci") == "passed"


def test_without_a_build_run_nothing_is_recorded_and_the_output_is_unchanged_ac_211_7(ci_repo, capsys):  # AC-211.7
    capsys.readouterr()
    assert quiet.main(["ci"]) == 0
    out = capsys.readouterr().out
    assert "recorded for build run" not in out and out.startswith("ok: devbox run ci (")
    assert runs.current_run(ci_repo) is None


def test_an_explicit_call_afterwards_adds_no_second_entry_ac_211_7(ci_repo):  # AC-211.7
    rid = begin_build(ci_repo)
    assert quiet.main(["ci"]) == 0
    before = build_markers(rid)
    assert runs.main(["gate", "security", "passed", "--dir", str(ci_repo)]) == 0
    budget.record_stage(ci_repo, "ci", "passed")
    rec = record(rid)
    assert rec["gates"] == {"security": "passed"}                       # one entry, overwritten in place
    assert build_markers(rid) == before == ["build:verify"]
    assert stage_result(rid, "ci") == "passed"
    stages = budget.find(rid)[1]["stages"]
    assert list(stages) == ["ci"]                                       # one stage entry, not a second one


# ---------------- AC-211.9: markers set by commands ----------------

def test_the_unit_starts_of_a_plain_build_keep_one_run_and_set_their_markers_ac_211_9(ci_repo, capsys, monkeypatch, store):  # AC-211.9
    monkeypatch.setenv("CPLAT_UNIT", "red-tests")
    rid = begin_build(ci_repo)
    assert build_markers(rid) == ["build:tests"]
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    capsys.readouterr()
    assert runs.main(["begin", "build", "--spec", SPEC, "--dir", str(ci_repo)]) == 0
    assert f"run {rid} (continued)" in capsys.readouterr().out.splitlines()
    assert runs.current_run(ci_repo) == rid and runs.active(rid) is not None
    assert build_markers(rid) == ["build:tests", "build:implement"]
    assert stored(store) == []                                          # nothing was abandoned


def test_a_second_begin_in_the_same_unit_sets_no_marker_twice_ac_211_9(ci_repo, monkeypatch):  # AC-211.9
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rid = begin_build(ci_repo)
    assert begin_build(ci_repo) == rid
    assert build_markers(rid) == ["build:implement"]


def test_a_begin_for_another_spec_or_without_a_unit_starts_a_new_run_as_before_ac_211_9(ci_repo, monkeypatch):  # AC-211.9
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rid = begin_build(ci_repo)
    monkeypatch.delenv("CPLAT_UNIT")
    assert begin_build(ci_repo) != rid


def test_a_begin_for_another_spec_in_a_unit_session_starts_a_new_run_ac_211_9(ci_repo, monkeypatch):  # AC-211.9
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rid = begin_build(ci_repo)
    assert runs.main(["begin", "build", "--spec", "008-other-thing", "--dir", str(ci_repo)]) == 0
    other = runs.current_run(ci_repo)
    assert other and other != rid
    assert build_markers(other) == ["build:implement"]


def test_the_gates_set_qa_and_verify_ac_211_9(ci_repo):  # AC-211.9
    rid = begin_build(ci_repo)
    d = ["--dir", str(ci_repo)]
    runs.main(["gate", "acceptance", "passed", *d])
    assert build_markers(rid) == ["build:qa"]
    runs.main(["gate", "security", "failed", *d])
    assert build_markers(rid) == ["build:qa", "build:verify"]
    runs.main(["gate", "security", "passed", *d])
    runs.main(["gate", "acceptance", "passed", *d])
    assert build_markers(rid) == ["build:qa", "build:verify"]


def test_markers_only_move_forward_and_an_explicit_call_is_still_accepted_ac_211_9(ci_repo):  # AC-211.9
    rid = begin_build(ci_repo)
    d = ["--dir", str(ci_repo)]
    runs.main(["phase", "build:tests", *d])
    runs.main(["phase", "build:verify", *d])
    runs.main(["phase", "build:implement", *d])                         # earlier than build:verify: refused
    runs.main(["phase", "build:verify", *d])                            # already set: not set again
    runs.main(["phase", "build:close", *d])
    assert build_markers(rid) == ["build:tests", "build:verify", "build:close"]
    runs.main(["phase", "build:pr", *d])
    assert build_markers(rid)[-1] == "build:pr"


def test_phases_that_are_no_build_markers_are_not_affected_ac_211_9(ci_repo):  # AC-211.9
    rid = begin_build(ci_repo)
    d = ["--dir", str(ci_repo)]
    runs.main(["phase", "build:close", *d])
    runs.main(["phase", "plan", *d])
    assert [p["name"] for p in record(rid)["phases"]][-2:] == ["build:close", "plan"]


def test_build_schedule_sets_build_implement_ac_211_9(ci_repo, capsys):  # AC-211.9
    _feature(ci_repo)
    rid = begin_build(ci_repo)
    jbuild(capsys, ci_repo, "schedule")
    assert build_markers(rid) == ["build:implement"]
    jbuild(capsys, ci_repo, "schedule")
    assert build_markers(rid) == ["build:implement"]


def test_spec_set_status_done_sets_build_close_ac_211_9(ci_repo, monkeypatch):  # AC-211.9
    d = spec.find(ci_repo, "007").dir
    (d / "spec.md").write_text((d / "spec.md").read_text().replace("status: approved", "status: building"))
    (d / "verification.md").write_text("# Verification\n\n**Result:** pass\n")
    rid = begin_build(ci_repo)
    assert spec.main(["--repo", str(ci_repo), "set-status", "007", "done"]) == 0
    assert build_markers(rid) == ["build:close"]


def test_spec_mutate_write_sets_build_image_ac_211_9(tmp_path, monkeypatch, store):  # AC-211.9
    import test_152_mutation as m
    monkeypatch.setattr(spec, "repo_shape", lambda root: "service-python")
    root = tmp_path / "mut"
    root.mkdir()
    (root / "src/app").mkdir(parents=True)
    (root / "src/app/rules.py").write_text(m.BASE)
    (root / "tests").mkdir()
    (root / "tests/test_rules.py").write_text("def test_ac_007_1(): ...  # AC-007.1\n")
    from test_spec import make
    make(root, plan=False)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "checkout", "-qb", "feature/007")
    (root / "src/app/rules.py").write_text(m.CHANGED)
    git(root, "commit", "-qam", "feature")
    monkeypatch.setattr(m.mutation, "run_tests", passing_when((30, True)))
    monkeypatch.chdir(root)
    rid = begin_build(root)
    (spec.find(root, "007").dir / "verification.md").write_text("# Verification\n\n**Result:** pass\n")
    assert spec.main(["--repo", str(root), "mutate", "007", "--base", "main", "--write"]) == 0
    assert build_markers(rid) == ["build:image"]


def test_all_six_markers_stand_in_order_once_the_commands_ran_ac_211_9(ci_repo, monkeypatch):  # AC-211.9
    monkeypatch.setenv("CPLAT_UNIT", "red-tests")
    rid = begin_build(ci_repo)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    begin_build(ci_repo)
    d = ["--dir", str(ci_repo)]
    runs.main(["gate", "acceptance", "passed", *d])
    assert quiet.main(["ci"]) == 0
    runs.main(["phase", "build:image", *d])
    runs.main(["phase", "build:close", *d])
    assert build_markers(rid) == MARKERS
