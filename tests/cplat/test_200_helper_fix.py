"""Spec 200 acceptance tests: a CI fix that only touches a test helper needs no stop (AC-200.7, J16-1).

Seams: `spec.test_diff` / `spec.main` (`cplat spec test-diff`) on a small git repo whose spec is already `done` and whose clone has an
unfinished ship run in `pr` or `land` (the state after build Phase 6, when a CI fix round of a later unit runs); a fix round is
a commit after the red-tests commit. `cplat component ship pr` is run with the spec 126 world (fake `gh`, recorded push and CI).
"""
import pytest

import runs
import ship
import spec
from test_160_lint_suppressions import g
from test_ship import repo  # noqa: F401  (fixture: `world` builds on it)
from test_ship_pr_126 import PR_URL, TITLE, world  # noqa: F401  (fixture)
from test_spec import make

SPEC = "007-price-alerts"
RED_SUBJECT = "test(price-alerts): acceptance tests for AC-007.1–AC-007.2"
TEST = "tests/test_alerts.py"
HELPER = "tests/alerts_support.py"
TEST_TEXT = "# AC-007.1\ndef test_alert():\n    password = 'x'\n    assert send(password)\n"
HELPER_TEXT = "# AC-007.1: support for the acceptance tests\n\n\ndef make_rule():\n    return {\"price\": 10}\n"
LABEL = "test helper (defines no test): "  # interface: label cplat prints for a helper file
REASON = "the fixture built a path that only exists on macOS"


def commit(root, msg):
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, cwd=root)
    return g("rev-parse", "HEAD", cwd=root).strip()


@pytest.fixture(params=["pr", "land"])
def fix_round(request, tmp_path):
    """(root, red sha): spec 007 `done`, its ship run in `pr` or `land`, the red commit holds a test and a helper."""
    root = tmp_path / "r"
    root.mkdir()
    g("init", "-q", "-b", "main", cwd=root)
    make(root, status="done")
    (root / "tests").mkdir()
    (root / TEST).write_text(TEST_TEXT)
    (root / HELPER).write_text(HELPER_TEXT)
    red = commit(root, RED_SUBJECT)
    ship.save_state(root, {"spec": SPEC, "phase": request.param, "merge": True, "branch": f"feature/{SPEC}", "fix_rounds": 1,
                           "started": "2026-11-15T10:00:00", "recorded": True, "run_id": "r1"})
    return root, red


def main(root, monkeypatch, capsys, *argv):
    monkeypatch.chdir(root)
    capsys.readouterr()
    rc = spec.main(["--repo", str(root), "test-diff", *argv])
    return rc, capsys.readouterr().out


def test_a_helper_only_fix_in_a_ci_round_is_named_a_helper_by_the_check_ac_200_7(fix_round, monkeypatch, capsys):  # AC-200.7
    root, red = fix_round
    (root / HELPER).write_text(HELPER_TEXT.replace("10", "12"))
    commit(root, "fix(ci): the helper path")
    good, why = spec.test_diff(root, red, [])[HELPER]                    # the spec is `done`, the ship run is not
    assert not good and why.startswith(LABEL), why
    rc, out = main(root, monkeypatch, capsys, red)
    assert rc == 1 and f"{HELPER}: changed — {LABEL}" in out


def test_the_helper_fix_is_recorded_without_escalating_and_then_accepted_ac_200_7(fix_round, monkeypatch, capsys):  # AC-200.7
    root, red = fix_round
    added = []
    monkeypatch.setattr(runs, "current_run", lambda r: "run-1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **k: added.append((rid, name, item)))
    (root / HELPER).write_text(HELPER_TEXT.replace("10", "12"))
    commit(root, "fix(ci): the helper path")
    rc, out = main(root, monkeypatch, capsys, red, "--tighten", HELPER, "--task", "t2", "--reason", REASON)
    assert rc == 0 and f"{HELPER}: tightened by an agent, recorded" in out
    (rid, name, item), = added
    assert name == "approved_test_diffs"
    assert item == {"file": HELPER, "task": "t2", "reason": REASON, "kind": "tightened"}
    assert spec.test_diff(root, red, [])[HELPER] == (True, f"tightened by an agent: {REASON}")   # the check goes green
    assert main(root, monkeypatch, capsys, red, "--task", "t2")[0] == 0                          # the run goes on: push, land
    assert not ship.load_state(root).get("escalated")


def test_a_changed_assertion_is_refused_and_escalates_as_a_changed_test_ac_200_7(fix_round, monkeypatch, capsys):  # AC-200.7
    root, red = fix_round
    (root / TEST).write_text(TEST_TEXT.replace("    assert send(password)\n", "    send(password)\n"))
    commit(root, "fix(ci): loosen the test")
    good, why = spec.test_diff(root, red, [])[TEST]
    assert not good and "test helper" not in why
    rc, out = main(root, monkeypatch, capsys, red, "--task", "t2")
    assert rc == 1 and TEST in out
    rc, out = main(root, monkeypatch, capsys, red, "--tighten", TEST, "--task", "t2", "--reason", "r")
    assert rc == 1 and f"{TEST}: refused" in out


@pytest.mark.parametrize("old, new", [
    (TEST_TEXT, TEST_TEXT.replace("def test_alert", "def test_alert_renamed")),       # a test definition removed or renamed
    (TEST_TEXT, TEST_TEXT.replace("AC-007.1", "AC-007.2")),                            # a criterion id changed
    (TEST_TEXT, TEST_TEXT.replace("def test_alert", "import pytest\n\n\n@pytest.mark.skip\ndef test_alert")),   # a skip added
], ids=["renamed-test", "changed-criterion-id", "added-skip"])
def test_a_changed_definition_or_criterion_id_is_not_a_tightening_ac_200_7(fix_round, monkeypatch, capsys, old, new):  # AC-200.7
    root, red = fix_round
    (root / TEST).write_text(new)
    commit(root, "fix(ci): change the test")
    good, _ = spec.test_diff(root, red, [])[TEST]
    assert not good
    assert main(root, monkeypatch, capsys, red, "--tighten", TEST, "--task", "t2", "--reason", "r")[0] == 1


def test_a_helper_that_lost_an_assertion_or_criterion_id_is_refused_by_the_default_check_ac_200_7(fix_round, monkeypatch, capsys):  # AC-200.7
    root, red = fix_round
    (root / HELPER).write_text(HELPER_TEXT.replace("AC-007.1", "AC-007.2"))
    commit(root, "fix(ci): the helper")
    rc, out = main(root, monkeypatch, capsys, red, "--tighten", HELPER, "--task", "t2", "--reason", "r")
    assert rc == 1 and f"{HELPER}: refused" in out
    assert not spec.test_diff(root, red, [])[HELPER][0]


NEW_HELPER = "tests/alerts_clock.py"


@pytest.mark.parametrize("text, ok", [
    ("import os\n\n\ndef tmp_dir():\n    return os.environ.get('TMPDIR', '/tmp')\n", True),
    ("def test_new():\n    assert 1\n", False),                                       # defines a test
    ("# AC-007.1\ndef make():\n    return 1\n", False),                                # names a criterion id
], ids=["helper", "defines-a-test", "names-a-criterion"])
def test_a_new_helper_file_is_accepted_only_when_it_defines_no_test_and_no_criterion_ac_200_7(fix_round, monkeypatch, capsys, text, ok):  # AC-200.7
    root, red = fix_round
    (root / NEW_HELPER).write_text(text)
    commit(root, "fix(ci): a clock helper")
    rc, out = main(root, monkeypatch, capsys, red, "--tighten", NEW_HELPER, "--task", "t2", "--reason", REASON)
    if ok:
        assert rc == 0 and f"{NEW_HELPER}: tightened by an agent, recorded" in out
    else:
        assert rc == 1 and f"{NEW_HELPER}: refused — new or deleted file" in out


# ---------------- the PR lists the tightening ----------------

def test_ship_pr_writes_the_how_this_was_built_block_with_the_tightening_ac_200_7(world, monkeypatch):  # AC-200.7
    rid = ship.load_state(world.repo)["run_id"]
    assert rid
    monkeypatch.setattr(runs, "current_run", lambda r: rid)
    item = {"file": HELPER, "task": "t2", "reason": REASON, "kind": "tightened"}
    runs.add_to(rid, "approved_test_diffs", item)
    assert world.pr() == 0
    (create,) = world.gh.has("pr", "create")
    body = open(create[create.index("--body-file") + 1]).read()
    assert "this was built" in body
    assert f"`{HELPER}` (task t2): {REASON}" in body


def test_ship_pr_updates_the_body_of_a_reused_pr_with_the_block_ac_200_7(world, monkeypatch):  # AC-200.7
    rid = ship.load_state(world.repo)["run_id"]
    monkeypatch.setattr(runs, "current_run", lambda r: rid)
    runs.add_to(rid, "approved_test_diffs", {"file": HELPER, "task": "t2", "reason": REASON, "kind": "tightened"})
    world.gh.open = [{"number": 7, "url": PR_URL, "title": TITLE, "labels": [], "isDraft": False}]
    assert world.pr() == 0
    (edit,) = [c for c in world.gh.has("pr", "edit") if "--body-file" in c]
    assert edit[2] == PR_URL
    body = open(edit[edit.index("--body-file") + 1]).read()
    assert "this was built" in body and HELPER in body and REASON in body
