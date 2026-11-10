"""Spec 169: the acceptance tests freeze when the red-tests unit ends (journey 8).

Seam: `spec.main(["test-diff", ...])` on the spec 160 `built` fixture, with a second test commit inside the red-tests unit
and `<git dir>/cplat-units.json` written as the unit runner leaves it.
"""
import json

import spec
from test_160_lint_suppressions import built, g  # noqa: F401  (fixture)


def _second_test_commit(root, t):
    red = g("rev-parse", "HEAD", cwd=root).strip()
    t.write_text(t.read_text().replace("assert send(password)", "send_ = load('send')\n    assert send_(password)"))
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "test: load modules dynamically", cwd=root)
    return red, g("rev-parse", "HEAD", cwd=root).strip()


def _units(root, commit, status="done"):
    (root / ".git" / "cplat-units.json").write_text(json.dumps({"version": 1, "command": "ship", "spec": "007", "units": [
        {"id": "plan", "status": "done", "commit": commit}, {"id": "red-tests", "status": status, "commit": commit}]}))


def test_a_test_commit_inside_the_red_tests_unit_is_frozen_ac_169_1(built, monkeypatch, capsys):  # AC-169.1
    root, t = built
    red, end = _second_test_commit(root, t)
    _units(root, end)
    monkeypatch.chdir(root)
    assert spec.main(["test-diff", red]) == 0
    out = capsys.readouterr().out
    assert f"base: {end[:7]}, where the red-tests unit ended" in out and "no acceptance test changed" in out


def test_a_later_change_is_still_flagged_against_the_unit_end_ac_169_1(built, monkeypatch, capsys):  # AC-169.1
    root, t = built
    red, end = _second_test_commit(root, t)
    _units(root, end)
    t.write_text(t.read_text().replace("    assert send_(password)\n", "    send_(password)\n"))
    monkeypatch.chdir(root)
    assert spec.main(["test-diff", red]) == 1
    assert "tests/test_alerts.py: changed" in capsys.readouterr().out


def test_without_a_finished_red_tests_unit_the_given_base_holds_ac_169_2(built, monkeypatch, capsys):  # AC-169.2
    root, t = built
    red, end = _second_test_commit(root, t)
    monkeypatch.chdir(root)
    assert spec.main(["test-diff", red]) == 1             # no units file: an interactive build
    _units(root, end, status="open")
    assert spec.main(["test-diff", red]) == 1
    _units(root, red)
    assert spec.frozen_base(root, red) == red
    assert "base:" not in capsys.readouterr().out


def test_a_unit_commit_off_the_branch_is_ignored_ac_169_2(built):  # AC-169.2
    root, t = built
    red, end = _second_test_commit(root, t)
    g("checkout", "-q", "-b", "other", red, cwd=root)
    _units(root, end)
    assert spec.frozen_base(root, red) == red


def test_a_new_test_naming_its_criterion_is_a_tightening_ac_169_3():  # AC-169.3
    old = '// AC-001.5\nit("lists", async () => {\n  expect(await list()).toEqual([]);\n});\n'
    new = old + 'it("AC-001.5 limits GET /tasks to 5 seconds", async () => {\n  expect(spy).toHaveBeenCalledWith(5000);\n});\n'
    assert spec.tightening(old, new, "tests/ac-001-task-api.test.ts") == (True, "")
    good, why = spec.tightening(old, new.replace('it("AC-001.5 limits', 'it("AC-001.6 limits'), "tests/ac-001-task-api.test.ts")
    assert not good and why == "criterion ids changed: ['AC-001.6']"


def test_an_escalation_saved_before_the_session_started_is_the_run_before_ac_169_4(monkeypatch):  # AC-169.4
    import appship_sched
    import shipwait
    monkeypatch.setattr(appship_sched, "_session_runs", lambda entry: True)
    entry = {"proc": {"pid": 1, "started": "2026-11-10T00:38:40"}}
    assert shipwait._before_start({"escalated": "old", "updated": "2026-11-10T00:23:02"}, entry)
    assert not shipwait._before_start({"escalated": "new", "updated": "2026-11-10T00:39:00"}, entry)
    monkeypatch.setattr(appship_sched, "_session_runs", lambda entry: False)       # the session ended: the escalation holds
    assert not shipwait._before_start({"escalated": "old", "updated": "2026-11-10T00:23:02"}, entry)
