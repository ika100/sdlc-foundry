"""Spec 211 acceptance tests: `cplat component ship start <spec> --unit <unit>` and `cplat component ship unit` (AC-211.1,
AC-211.6, and the unit-start marker of AC-211.9).

Seam: `ship.main([...])` on the spec 131 fixtures (a repo with an approved spec 007 and a prepared units file); stdout is read
as lines. The contract is design.md section 3."""
import json

import pytest

import ship
import units  # noqa: F401  (imported so that a rename shows up here)
from support_211 import KNOWN, briefing
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import repo  # noqa: F401  (fixture)
from units131_support import BRANCH, SPEC_ID, git


@pytest.fixture(autouse=True)
def one_task_per_unit(monkeypatch):
    monkeypatch.setenv("CPLAT_PARALLEL_TASKS", "1")
    for name in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_UNIT"):
        monkeypatch.delenv(name, raising=False)


def prepared(repo, command="ship"):
    """A repo whose units file is written; with `ship` a ship run exists as well."""
    if command == "ship":
        ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", BRANCH)
    import importlib
    importlib.import_module("units").prepare(repo, command, SPEC_ID)


def run(repo, capsys, *argv):
    capsys.readouterr()
    try:
        rc = ship.main(["--repo", str(repo), *argv])
    except SystemExit as e:                     # an option the command does not know yet
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def line_index(lines, prefix):
    return next(i for i, ln in enumerate(lines) if ln.startswith(prefix))


def shape_line(line):
    assert line.startswith("shape: ")
    return json.loads(line[len("shape: "):])


def state_without_updated(repo):
    st = dict(ship.load_state(repo) or {})
    st.pop("updated", None)
    return st


def snapshot(repo):
    import runs
    st = ship.load_state(repo) or {}
    units_file = repo / ".git" / "cplat-units.json"
    rec = runs.active(st.get("run_id")) if st.get("run_id") else None
    return state_without_updated(repo), units_file.read_text() if units_file.is_file() else None, rec


# ---------------- AC-211.1: shape, where the run stands, the briefing ----------------

def test_ship_unit_prints_shape_then_the_run_then_the_unit_then_the_briefing_ac_211_1(repo, capsys, monkeypatch):  # AC-211.1
    prepared(repo)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rc, out, _ = run(repo, capsys, "unit")
    lines = out.splitlines()
    assert rc == 0
    assert "shape" in shape_line(lines[0])
    unit_at = line_index(lines, "unit task:t1: ")
    assert unit_at >= 2, "where the run stands comes between the shape line and the unit line"
    assert lines[unit_at + 1].startswith("next unit: ")
    assert lines[unit_at + 2] == ""
    assert lines[unit_at + 3].startswith("briefing for unit task:t1 (ship)")
    assert "\n".join(lines[unit_at + 3:]).rstrip("\n") == briefing.build("task:t1", "ship").rstrip("\n")


def test_ship_start_with_a_unit_prints_the_same_parts_in_the_same_order_ac_211_1(repo, capsys):  # AC-211.1
    prepared(repo)
    rc, out, err = run(repo, capsys, "start", "7", "--unit", "task:t1")
    lines = out.splitlines()
    assert rc == 0, err
    assert "shape" in shape_line(lines[0])
    unit_at = line_index(lines, "unit task:t1: ")
    assert unit_at >= 2 and lines[unit_at + 1].startswith("next unit: ") and lines[unit_at + 2] == ""
    assert "\n".join(lines[unit_at + 3:]).rstrip("\n") == briefing.build("task:t1", "ship").rstrip("\n")


def test_a_second_call_prints_the_same_and_changes_no_state_ac_211_1(repo, capsys, monkeypatch, store):  # AC-211.1
    prepared(repo)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    _, first, _ = run(repo, capsys, "unit")
    assert first.startswith("shape: ") and "briefing for unit task:t1" in first
    before = snapshot(repo)
    _, second, _ = run(repo, capsys, "unit")
    assert second == first and snapshot(repo) == before
    _, start_one, _ = run(repo, capsys, "start", "7", "--unit", "task:t1")
    before = snapshot(repo)
    _, start_two, _ = run(repo, capsys, "start", "7", "--unit", "task:t1")
    assert start_two == start_one and snapshot(repo) == before


def test_a_unit_of_a_build_prints_its_run_as_a_build_and_its_briefing_ac_211_1(repo, capsys, monkeypatch):  # AC-211.1
    prepared(repo, command="build")
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rc, out, _ = run(repo, capsys, "unit")
    lines = out.splitlines()
    assert rc == 0 and "shape" in shape_line(lines[0])
    assert any(ln.startswith("build ") and ln.endswith(":") for ln in lines[1:])
    unit_at = line_index(lines, "unit task:t1: ")
    assert lines[unit_at + 3].startswith("briefing for unit task:t1 (build)")


def test_without_a_units_file_the_unit_line_says_so_and_there_is_no_next_unit_ac_211_1(repo, capsys, monkeypatch):  # AC-211.1
    ship.start(repo, "7", True)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rc, out, _ = run(repo, capsys, "unit")
    assert rc == 0 and out.startswith("shape: ") and "unit task:t1: open: no units file" in out.splitlines()
    assert not any(ln.startswith("next unit:") for ln in out.splitlines())


def test_unit_json_keeps_its_keys_and_adds_shape_and_briefing_ac_211_1(repo, capsys, monkeypatch):  # AC-211.1
    prepared(repo)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rc, out, _ = run(repo, capsys, "unit", "--json")
    data = json.loads(out)
    assert rc == 0 and {"shape", "next_unit", "briefing", "briefing_unavailable"} <= set(data)
    assert isinstance(data["shape"], dict) and "shape" in data["shape"]
    assert isinstance(data["next_unit"], str)
    assert data["briefing"] == briefing.build("task:t1", "ship") and data["briefing_unavailable"] is None


# ---------------- AC-211.6: unavailable briefing, unknown unit ----------------

def test_an_unavailable_briefing_prints_the_reason_and_still_exits_zero_ac_211_6(repo, capsys, monkeypatch, tmp_path):  # AC-211.6
    prepared(repo)
    import briefing as module
    monkeypatch.setattr(module, "PLUGIN_ROOT", tmp_path / "no-plugin")
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    for argv in (("unit",), ("start", "7", "--unit", "task:t1")):
        rc, out, _ = run(repo, capsys, *argv)
        lines = out.splitlines()
        assert rc == 0 and "shape" in shape_line(lines[0])
        unit_at = line_index(lines, "unit task:t1: ")
        assert lines[unit_at + 1].startswith("next unit: ") and lines[unit_at + 2] == ""
        last = lines[unit_at + 3]
        assert last.startswith("briefing unavailable: ") and last.endswith("; read the build instructions and the unit-mode reference in full")
        assert len(lines) == unit_at + 4


def test_unit_json_names_the_reason_when_unavailable_ac_211_6(repo, capsys, monkeypatch, tmp_path):  # AC-211.6
    prepared(repo)
    import briefing as module
    monkeypatch.setattr(module, "PLUGIN_ROOT", tmp_path / "no-plugin")
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    rc, out, _ = run(repo, capsys, "unit", "--json")
    data = json.loads(out)
    assert rc == 0 and data["briefing"] is None and data["briefing_unavailable"].startswith("cannot read ")


def test_an_unknown_unit_exits_non_zero_naming_the_known_units_ac_211_6(repo, capsys, monkeypatch):  # AC-211.6
    prepared(repo)
    monkeypatch.setenv("CPLAT_UNIT", "bogus")
    rc, out, err = run(repo, capsys, "unit")
    assert rc == 2 and f"ERROR: unknown unit 'bogus'; known units: {KNOWN}" in err and "briefing" not in out


def test_ship_start_with_an_unknown_unit_changes_nothing_ac_211_6(repo, capsys):  # AC-211.6
    before = ship.load_state(repo)
    rc, out, err = run(repo, capsys, "start", "7", "--unit", "bogus")
    assert rc == 2 and f"ERROR: unknown unit 'bogus'; known units: {KNOWN}" in err and out == ""
    assert ship.load_state(repo) == before


def test_a_unit_cannot_be_combined_with_detach_ac_211_6(repo, capsys):  # AC-211.6
    rc, out, err = run(repo, capsys, "start", "7", "--unit", "task:t1", "--detach")
    assert rc == 2 and "ERROR: --unit cannot be combined with --detach" in err


# ---------------- AC-211.9: the unit's start sets its marker ----------------

def markers(repo):
    import runs
    rid = ship.load_state(repo)["run_id"]
    return [p["name"] for p in runs.active(rid)["phases"] if p["name"].startswith("build:")]


def test_a_task_unit_start_sets_build_implement_once_ac_211_9(repo, capsys, monkeypatch, store):  # AC-211.9
    prepared(repo)
    monkeypatch.setenv("CPLAT_UNIT", "task:t1")
    assert "build:implement" not in markers(repo)
    run(repo, capsys, "unit")
    assert markers(repo) == ["build:implement"]
    run(repo, capsys, "unit")
    run(repo, capsys, "start", "7", "--unit", "task:t1")
    assert markers(repo) == ["build:implement"]


def test_a_plan_unit_start_sets_no_build_marker_ac_211_9(repo, capsys, monkeypatch, store):  # AC-211.9
    prepared(repo)
    monkeypatch.setenv("CPLAT_UNIT", "plan")
    rc, out, _ = run(repo, capsys, "unit")
    assert rc == 0 and out.splitlines()[0].startswith("shape: ") and markers(repo) == []
