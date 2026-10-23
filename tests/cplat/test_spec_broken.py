"""Spec 085: a broken spec names itself (file, line, fix) and stops nothing else."""
import json

import pytest

import core
import spec
from test_spec import make

BAD = "docs/specs/090-broken/spec.md"
HINT = """values that contain ': ' must be quoted, e.g. title: "a: b\""""
FENCE_HINT = "`---`"


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def broken(root, text=None, plan=None, name="090-broken"):
    d = root / "docs" / "specs" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(text if text is not None else
                               "---\nspec_id: 090-broken\ntitle: a: b\nstatus: draft\n---\n\n# x\n")
    if plan is not None:
        (d / "plan.md").write_text(plan)
    return d


def snapshot(d):
    return {p.name: p.read_text() for p in d.iterdir()}


def run(root, capsys, *args):
    try:
        code = spec.main(["--repo", str(root), *args])
    except core.PlatformError as e:
        code, err = 1, e
    else:
        err = None
    out = capsys.readouterr()
    return code, out.out, err


def test_colon_title_names_file_line_and_hint(tmp_path):  # AC-085.1
    make(tmp_path)
    broken(tmp_path)
    with pytest.raises(core.PlatformError) as ei:
        spec.find(tmp_path, "090")
    e = ei.value
    assert BAD in str(e) and "line 3" in str(e)
    assert e.hint == HINT
    assert isinstance(e, spec.BrokenSpec) and e.line == 3 and e.rel == BAD


@pytest.mark.parametrize("text", ["# no front matter\n", "---\n- a\n- b\n---\n\n# x\n"])
def test_missing_fences_or_non_mapping(tmp_path, text):  # AC-085.2
    broken(tmp_path, text)
    with pytest.raises(core.PlatformError) as ei:
        spec.find(tmp_path, "090")
    assert BAD in str(ei.value) and "line 1" in str(ei.value)
    assert "key: value" in ei.value.hint and "---" in ei.value.hint


def test_broken_plan_names_plan_file(tmp_path):  # AC-085.3
    make(tmp_path)
    d = tmp_path / "docs" / "specs" / "007-price-alerts"
    (d / "plan.md").write_text("---\nspec_id: x\ntitle: a: b\n---\n")
    with pytest.raises(core.PlatformError) as ei:
        spec.find(tmp_path, "007")
    assert "docs/specs/007-price-alerts/plan.md" in str(ei.value) and "line 3" in str(ei.value)
    assert ei.value.hint == HINT


@pytest.mark.parametrize("cmd", [["approve", "007"], ["hash", "007"], ["trace", "007", "--json"],
                                 ["task-done", "007", "t1"], ["set-status", "007", "approved"], ["check", "007"]])
def test_valid_spec_unaffected_by_broken_neighbour(tmp_path_factory, capsys, cmd):  # AC-085.4
    clean, dirty = tmp_path_factory.mktemp("c"), tmp_path_factory.mktemp("d")
    make(clean)
    make(dirty)
    bd = broken(dirty)
    before = snapshot(bd)
    a = run(clean, capsys, *cmd)
    b = run(dirty, capsys, *cmd)
    assert a[0] == b[0] and a[1] == b[1]
    assert snapshot(bd) == before
    assert spec.find(dirty, "007").id == "007-price-alerts"


def test_ship_reaches_specs_only_through_find(tmp_path):  # AC-085.5
    make(tmp_path)
    broken(tmp_path)
    assert [s.id for s in spec.all_specs(tmp_path)] == ["007-price-alerts"]
    assert spec.find(tmp_path, "007-price-alerts").id == "007-price-alerts"
    specs, bad = spec.scan(tmp_path)
    assert [b.id for b in bad] == ["090-broken"]


@pytest.mark.parametrize("ref", ["090", "90", "090-broken", "broken"])
@pytest.mark.parametrize("cmd", ["approve", "hash", "trace", "task-done", "set-status"])
def test_addressing_broken_spec_fails_and_writes_nothing(tmp_path, capsys, cmd, ref):  # AC-085.6
    make(tmp_path)
    bd = broken(tmp_path)
    before = snapshot(bd)
    extra = {"task-done": ["t1"], "set-status": ["approved"]}.get(cmd, [])
    code, out, err = run(tmp_path, capsys, cmd, ref, *extra)
    assert code == 1
    assert isinstance(err, spec.BrokenSpec) and BAD in str(err) and err.line == 3
    assert snapshot(bd) == before


def test_check_all_reports_broken_once(tmp_path, capsys):  # AC-085.7
    make(tmp_path)
    broken(tmp_path)
    code, out, _ = run(tmp_path, capsys, "check")
    assert code == 1
    lines = [ln for ln in out.splitlines() if ln.startswith("ERROR: 090-broken:")]
    assert len(lines) == 1 and BAD in lines[0] and "line 3" in lines[0]
    assert "1 error(s)" in out


@pytest.mark.parametrize("strict", [[], ["--strict"]])
def test_ci_annotates_broken_spec(tmp_path, capsys, strict):  # AC-085.8
    make(tmp_path, status="approved")
    broken(tmp_path)
    code, out, _ = run(tmp_path, capsys, "ci", *strict)
    assert code == 1
    ann = [ln for ln in out.splitlines() if ln.startswith("::error") and BAD in ln]
    assert len(ann) == 1 and "line=3" in ann[0]


@pytest.mark.parametrize("extra", [[], ["--all"]])
def test_list_json_shows_broken(tmp_path, capsys, extra):  # AC-085.9
    make(tmp_path)
    broken(tmp_path)
    code, out, _ = run(tmp_path, capsys, "list", *extra, "--json")
    assert code == 0
    rows = {r["id"]: r for r in json.loads(out)}
    assert "007-price-alerts" in rows
    r = rows["090-broken"]
    assert r["status"] == "broken" and r["title"] == ""
    assert BAD in r["next"] and "line 3" in r["next"] and r["next"].startswith("fix ")


def test_list_text_shows_broken(tmp_path, capsys):  # AC-085.9
    make(tmp_path)
    broken(tmp_path)
    code, out, _ = run(tmp_path, capsys, "list")
    assert code == 0 and "090-broken" in out and "broken" in out


def test_index_keeps_row_for_broken(tmp_path):  # AC-085.10
    make(tmp_path)
    broken(tmp_path)
    table = spec.index_table(tmp_path)
    assert "| [090-broken](specs/090-broken/spec.md) —  |  | broken | 0 |  |" in table
    assert "007-price-alerts" in table


def test_next_number_counts_broken(tmp_path):  # AC-085.11
    make(tmp_path)
    broken(tmp_path)
    assert spec.next_number(tmp_path) == 91


@pytest.mark.parametrize("title", ["a: b", "#7 retry", "- list", "[draft]", "yes", "null", "123", '"quoted" start',
                                   "'single", "true", "~"])
def test_new_titles_round_trip(tmp_path, capsys, title):  # AC-085.12
    s = spec.new(tmp_path, title, shape=None, priority="P1", tracks=[], parent=None)
    back = spec.read(s.dir)
    assert back.meta["title"] == title and isinstance(back.meta["title"], str)
    code, out, _ = run(tmp_path, capsys, "check")
    assert "ERROR" not in out
