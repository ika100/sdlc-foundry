"""Spec 172: `cplat spec test-diff <red>` judges only the test files the red-tests step committed (AC-172.1, AC-172.2).

Seam: `spec.test_diff(root, base, [], notes=...)` and `spec.main(["test-diff", ...])` on a small git repo with one `building`
spec (spec 160's `g` helper, spec 007's files). `notes` is the list that receives the lines `main` prints first (design, section 1).
"""
import json

import spec
from test_160_lint_suppressions import g
from test_spec import make

RED_SUBJECT = "test(price-alerts): acceptance tests for AC-007.1–AC-007.2"
ALERTS = "# AC-007.1\ndef test_alert():\n    password = 'x'\n    assert send(password)\n"


def commit(root, msg):
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, cwd=root)
    return g("rev-parse", "HEAD", cwd=root).strip()


def fallback_line(base):
    return (f"fallback: no 'acceptance tests for' commit of a building spec between {base[:7]} and HEAD; checking every changed "
            "test file that names a criterion of a building spec (as before spec 172)")


def world(tmp_path, red_subject=RED_SUBJECT):
    """main: spec 007 `building`, tests/test_other.py (names no criterion); then the red-tests commit with tests/test_alerts.py."""
    root = tmp_path / "r"
    root.mkdir()
    g("init", "-q", "-b", "main", cwd=root)
    make(root, status="building")
    (root / "tests").mkdir()
    (root / "tests" / "test_other.py").write_text("def test_o():\n    assert 1\n")
    commit(root, "chore: init")
    (root / "tests" / "test_alerts.py").write_text(ALERTS)
    return root, commit(root, red_subject)


def later_tests(root):
    """What a coder adds after the red-tests step: a new test file and a new test in a file the red step did not touch."""
    (root / "tests" / "test_new.py").write_text("# AC-007.2\ndef test_new():\n    assert 2\n")
    (root / "tests" / "test_other.py").write_text("def test_o():\n    assert 1\n\n\n# AC-007.1\ndef test_o2():\n    assert 2\n")
    return commit(root, "feat: the coder's own tests")


def run_main(root, monkeypatch, capsys, *argv):
    monkeypatch.chdir(root)
    capsys.readouterr()
    rc = spec.main(["--repo", str(root), "test-diff", *argv])
    return rc, capsys.readouterr().out


# ---------------- AC-172.1: a test the build adds is not an acceptance test ----------------

def test_a_new_test_file_and_a_new_test_in_an_untouched_file_are_not_reported_ac_172_1(tmp_path):  # AC-172.1
    root, red = world(tmp_path)
    later_tests(root)
    assert spec.test_diff(root, red, []) == {}


def test_the_cli_reports_nothing_for_them_with_and_without_task_ac_172_1(tmp_path, monkeypatch, capsys):  # AC-172.1
    root, red = world(tmp_path)
    later_tests(root)
    for extra in ([], ["--task", "t1"]):
        rc, out = run_main(root, monkeypatch, capsys, red, *extra)
        assert rc == 0 and "no acceptance test changed" in out and "fallback" not in out
        assert "test_new.py" not in out and "test_other.py" not in out


def test_a_change_to_a_red_tests_file_is_still_reported_ac_172_1(tmp_path, monkeypatch, capsys):  # AC-172.1
    root, red = world(tmp_path)
    later_tests(root)
    t = root / "tests" / "test_alerts.py"
    t.write_text(t.read_text().replace("    assert send(password)\n", "    send(password)\n"))
    rc, out = run_main(root, monkeypatch, capsys, red)
    assert rc == 1 and "tests/test_alerts.py: changed" in out
    assert "test_new.py" not in out and "test_other.py" not in out
    good, why = spec.test_diff(root, red, [])["tests/test_alerts.py"]
    assert not good and why                      # reported with its reason, as before this spec (the person approved, 2026-11-10)


def test_the_deletion_of_a_red_tests_file_is_still_reported_ac_172_1(tmp_path):  # AC-172.1
    root, red = world(tmp_path)
    later_tests(root)
    (root / "tests" / "test_alerts.py").unlink()
    assert spec.test_diff(root, red, []) == {"tests/test_alerts.py": (False, "new or deleted file")}


def test_a_file_committed_inside_the_red_tests_unit_is_frozen_too_ac_172_1(tmp_path, monkeypatch, capsys):  # AC-172.1
    root, red = world(tmp_path)
    (root / "tests" / "test_extra.py").write_text("# AC-007.2\ndef test_extra():\n    assert extra()\n")
    end = commit(root, "test(price-alerts): lint-fix acceptance tests for 007-price-alerts")      # still inside the unit
    (root / ".git" / "cplat-units.json").write_text(json.dumps({"version": 1, "command": "ship", "spec": "007", "units": [
        {"id": "plan", "status": "done", "commit": end}, {"id": "red-tests", "status": "done", "commit": end}]}))
    later_tests(root)
    rc, out = run_main(root, monkeypatch, capsys, red)
    assert rc == 0 and "no acceptance test changed" in out
    extra = root / "tests" / "test_extra.py"
    extra.write_text(extra.read_text().replace("    assert extra()\n", "    extra()\n"))
    rc, out = run_main(root, monkeypatch, capsys, red)
    assert rc == 1 and "tests/test_extra.py: changed" in out and "test_new.py" not in out


# ---------------- AC-172.2: no red-tests commit: the selection of before, and one line saying so ----------------

def test_without_a_red_tests_commit_the_old_selection_and_one_note_apply_ac_172_2(tmp_path):  # AC-172.2
    root, base = world(tmp_path, red_subject="test: add alert tests")
    later_tests(root)
    notes = []
    out = spec.test_diff(root, base, [], notes=notes)
    assert notes == [fallback_line(base)]
    assert set(out) == {"tests/test_new.py", "tests/test_other.py"}      # changed test files naming a criterion, as before
    assert out["tests/test_new.py"] == (False, "new or deleted file")


def test_the_cli_prints_the_fallback_line_before_the_files_ac_172_2(tmp_path, monkeypatch, capsys):  # AC-172.2
    root, base = world(tmp_path, red_subject="test: add alert tests")
    later_tests(root)
    rc, out = run_main(root, monkeypatch, capsys, base)
    lines = out.splitlines()
    assert rc == 1 and lines[0] == fallback_line(base)
    assert out.count("fallback:") == 1 and any(ln.startswith("tests/test_new.py: changed") for ln in lines[1:])


def test_a_red_tests_commit_before_the_given_base_means_fallback_ac_172_2(tmp_path):  # AC-172.2
    root, red = world(tmp_path)
    later = later_tests(root)                                # the red commit is behind the given base
    (root / "tests" / "test_new.py").write_text("# AC-007.2\ndef test_new():\n    assert 3\n")
    notes = []
    out = spec.test_diff(root, later, [], notes=notes)
    assert notes == [fallback_line(later)]
    assert set(out) == {"tests/test_new.py"}


def test_explicit_files_are_checked_as_given_ac_172_2(tmp_path):  # AC-172.2
    root, red = world(tmp_path)
    later_tests(root)
    out = spec.test_diff(root, red, ["tests/test_new.py"])
    assert out == {"tests/test_new.py": (False, "new or deleted file")}
