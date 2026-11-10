"""Spec 171 acceptance tests: a change to a test helper of the acceptance tests that changes no assertion is tightened without
asking the person (AC-171.7).

Seams: `spec.test_diff` and `spec.main` (`cplat spec test-diff`) on the spec 160 `built` repo with one extra support file that
defines no test; the PR block of `cplat platform runs report --pr`; the build prompt and its tighten reference.
"""
import re
from pathlib import Path

import pytest

import runs
import spec
from test_160_lint_suppressions import built, g  # noqa: F401  (fixtures, helpers)
from test_runs_built_133 import make_run, part, report, repo  # noqa: F401  (fixtures, helpers)

ROOT = Path(__file__).resolve().parents[2]
HELPER = "tests/alerts_support.py"
HELPER_TEXT = "# AC-007.1: support for the acceptance tests\n\n\ndef make_rule():\n    return {\"price\": 10}\n"
ASSERTING = "# AC-007.1: support for the acceptance tests\n\n\ndef check_sent(res):\n    assert res.ok\n    assert res.sent\n"
LABEL = "test helper (defines no test): "


@pytest.fixture()
def with_helper(built):  # noqa: F811
    """The `built` repo whose red commit also holds a support file; returns (root, test file, helper file)."""
    root, t = built
    h = root / HELPER
    h.write_text(HELPER_TEXT)
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "test: support for 007", cwd=root)
    return root, t, h


def test_a_changed_helper_is_named_a_test_helper_by_the_check(with_helper):  # AC-171.7
    root, t, h = with_helper
    h.write_text(HELPER_TEXT.replace("10", "12"))
    for files in ([HELPER], []):                       # named, and found by the default listing (it names the criterion)
        good, why = spec.test_diff(root, "HEAD", files)[HELPER]
        assert not good and why.startswith(LABEL), why


def test_a_changed_helper_is_a_test_helper_line_in_the_cli_output_and_exits_1(with_helper, capsys):  # AC-171.7
    root, t, h = with_helper
    h.write_text(HELPER_TEXT.replace("10", "12"))
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", HELPER]) == 1
    assert f"{HELPER}: changed — {LABEL}" in capsys.readouterr().out


def test_a_changed_test_is_not_called_a_helper(with_helper):  # AC-171.7
    root, t, h = with_helper
    t.write_text(t.read_text().replace("    assert send(password)\n", "    send(password)\n"))
    good, why = spec.test_diff(root, "HEAD", ["tests/test_alerts.py"])["tests/test_alerts.py"]
    assert not good and "test helper" not in why


def test_a_helper_fix_is_recorded_without_asking_and_listed_in_the_pr(with_helper, monkeypatch, capsys, repo):  # AC-171.7
    root, t, h = with_helper
    added = []
    monkeypatch.setattr(runs, "current_run", lambda r: "run-1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **k: added.append((rid, name, item)))
    h.write_text(HELPER_TEXT.replace("10", "12"))
    assert not spec.test_diff(root, "HEAD", [])[HELPER][0]                          # the check names it a helper ...
    assert spec.test_diff(root, "HEAD", [])[HELPER][1].startswith(LABEL)
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", "--tighten", HELPER, "--task", "t2",
                      "--reason", "the fixture built the wrong rule"]) == 0         # ... the session records it ...
    good, why = spec.test_diff(root, "HEAD", [])[HELPER]
    assert good and why == "tightened by an agent: the fixture built the wrong rule"   # ... and the check accepts it
    (rid, name, item), = added
    assert name == "approved_test_diffs"
    assert item == {"file": HELPER, "task": "t2", "reason": "the fixture built the wrong rule", "kind": "tightened"}
    capsys.readouterr()
    run = make_run(approved_test_diffs=[item])
    block = part(report(run, repo, capsys)[1], "User decisions")
    assert f"`{HELPER}` (task t2): the fixture built the wrong rule" in block
    assert "test tightened by an agent" in block


@pytest.mark.parametrize("old, new, why", [
    (ASSERTING, ASSERTING.replace("    assert res.sent\n", ""), "fewer assertions (2 before, 1 now)"),
    (ASSERTING, ASSERTING.replace("AC-007.1", "AC-007.2"), "criterion ids changed"),
])
def test_a_helper_change_that_loses_an_assertion_or_a_criterion_id_is_refused(with_helper, old, new, why, capsys):  # AC-171.7
    root, t, h = with_helper
    h.write_text(old)
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "test: an asserting helper", cwd=root)
    h.write_text(new)
    code = spec.main(["--repo", str(root), "test-diff", "HEAD", "--tighten", HELPER, "--task", "t2", "--reason", "r"])
    assert code == 1
    assert f"{HELPER}: refused — {why}" in capsys.readouterr().out
    assert not spec.test_diff(root, "HEAD", [HELPER])[HELPER][0]                  # still not accepted: the person decides


def test_a_helper_that_gains_an_assertion_is_a_tightening(with_helper):  # AC-171.7
    root, t, h = with_helper
    h.write_text(HELPER_TEXT + "\n\ndef check_rule(rule):\n    assert rule[\"price\"] == 10\n")
    out = spec.tighten_test_change(root, "HEAD", [HELPER], "AC-007.1: the helper checks its rule")
    assert out[HELPER] == (True, "")


# ---------------- AC-171.7: the build prompt acts on the `test helper` line ----------------

def test_the_build_tightens_a_test_helper_line_without_asking_the_person():  # AC-171.7
    texts = {p: (ROOT / p).read_text() for p in ("plugins/component/commands/build.md",
                                                  "plugins/component/references/build-tighten.md")}
    lines = [ln for t in texts.values() for ln in t.splitlines()]
    hit = [ln for ln in lines if "test helper" in ln and "--tighten" in ln]
    assert hit, "a line says what the build does with a `test helper` line: cplat spec test-diff $RED --tighten <file>"
    assert any(re.search(r"without asking|does not ask|never ask", ln) for ln in hit)
    # the other half stays: a changed test is still the person's decision
    assert "Hard rule" in texts["plugins/component/commands/build.md"]
    assert "Never loosen, delete or skip" in texts["plugins/component/references/build-tighten.md"]
