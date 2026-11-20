"""#869: unit sessions spent a third of their model calls on bookkeeping. `ship start` prints the shape and the unit's rules
and state, a `cplat quiet ci` in a run records its gate and stage, and `spec test-diff red` finds the red commit itself."""
import subprocess

import pytest

import core
import quiet
import runs
import ship
import shapecmd
import spec


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *args],
                          check=True, capture_output=True, text=True).stdout


def test_the_shape_line_names_shape_and_agents(tmp_path, monkeypatch):
    monkeypatch.setattr(shapecmd, "route", lambda repo: {"shape": "service-python", "plugin": "svc", "deployable": True,
                                                         "library": False, "agents": {"coder": "svc:coder"}})
    assert ship.shape_line(tmp_path) == "shape: service-python (plugin svc, deployable); agents: coder=svc:coder"


def test_a_shape_error_is_one_line_with_its_hint(tmp_path, monkeypatch):
    def broken(repo):
        raise core.PlatformError("bad .platform-settings.yml", hint="fix shape:")
    monkeypatch.setattr(shapecmd, "route", broken)
    assert ship.shape_line(tmp_path) == "shape: error: bad .platform-settings.yml (fix shape:)"


@pytest.mark.parametrize("unit,key", [("plan", "plan"), ("task:t2", "task:<id>"), ("batch:t1,t3", "batch:<id>,<id>…"),
                                      ("verification", "verification")])
def test_unit_rules_are_the_unit_s_row_and_the_rules_for_every_unit(unit, key):
    text = ship.UNIT_RULES.read_text()
    row = next(ln for ln in text.splitlines() if ln.startswith(f"| `{key}` |"))
    lines = ship.unit_rules(unit)
    assert lines[0] == f"unit {unit}: {row.split('|')[2].strip()}"
    every = text.split("## Rules for every unit", 1)[1].strip().splitlines()   # interface: the heading unit_rules reads
    assert lines[-len(every):] == every


def test_a_green_quiet_ci_in_a_run_records_the_security_gate_and_the_ci_stage(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(runs, "record_gate", lambda repo, gate, result: seen.append((gate, result)) or True)
    import budget
    monkeypatch.setattr(budget, "record_stage", lambda repo, name, result: seen.append((name, result)))
    quiet._record_ci(tmp_path, "passed")
    assert seen == [("security", "passed"), ("ci", "passed")]
    assert "recorded: gate security passed, stage ci passed" in capsys.readouterr().out


def test_without_a_current_run_quiet_ci_records_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runs, "record_gate", lambda repo, gate, result: False)
    import budget
    monkeypatch.setattr(budget, "record_stage", lambda *a: pytest.fail("no stage without a run"))
    quiet._record_ci(tmp_path, "failed")
    assert capsys.readouterr().out == ""


def test_test_diff_red_finds_the_red_commit(tmp_path, monkeypatch, capsys):
    git(tmp_path, "init", "-q")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "test(x): acceptance tests for 001-x")
    red = git(tmp_path, "rev-parse", "HEAD").strip()
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: t1")
    monkeypatch.chdir(tmp_path)
    spec.main(["test-diff", "red"])
    assert f"red: {red[:7]}" in capsys.readouterr().out


def test_test_diff_red_without_a_red_commit_is_refused(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "i")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(core.PlatformError) as e:
        spec.main(["test-diff", "red"])
    assert "no commit with the red acceptance tests" in str(e.value)
