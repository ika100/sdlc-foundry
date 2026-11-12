"""Spec 179 acceptance tests: the acceptance tests are reviewed once before they freeze (AC-179.5, AC-179.6).

Seams: `cplat component build reviewed` (`cplat.main`) and the `testreview` module on a git repo with a feature branch and its
acceptance-tests commit; `units` (the `red-tests` rule); `spec.test_diff` against a `red-tests` unit that ended at the reviewed
commit; the PR block of `cplat platform runs report --pr`; the build, reviewer and unit-mode prompts. Contract: design.md section 4.
The `testreview` module does not exist yet, so it is imported inside the tests.
"""
import importlib
import json
import re
import subprocess
from pathlib import Path

import pytest

import cplat
import spec
import units
from test_runs_built_133 import make_run, part, report, SPEC as BUILT_SPEC, SPEC_DIR as BUILT_SPEC_DIR  # noqa: F401
from test_spec import make
from units131_support import BRANCH, SPEC_ID, git, head, make_repo

ROOT = Path(__file__).resolve().parents[2]
TEST_FILE = "tests/test_alerts.py"
TESTS = "# AC-007.1 AC-007.2\n\n\ndef test_alert():\n    assert send()\n"
SUBJECT = f"test(007): reviewed acceptance tests for {SPEC_ID}"
FINDING = f"{TEST_FILE}::test_alert | AC-007.1 | the fixture sends nothing but the test asserts a sent mail"
FINDING_2 = f"{TEST_FILE}::test_other | AC-007.2 | the asserted text 'Dear user' is not defined by the contract"


def testreview():
    return importlib.import_module("testreview")


def write_tests(repo, text=TESTS):
    (repo / TEST_FILE).parent.mkdir(exist_ok=True)
    (repo / TEST_FILE).write_text(text)


@pytest.fixture()
def world(tmp_path):
    """Spec 007 with its feature branch and the commit of the acceptance tests (the red-tests step's end)."""
    repo = make_repo(tmp_path)
    git(repo, "checkout", "-qb", BRANCH)
    write_tests(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"test(007): acceptance tests for {SPEC_ID}")
    return repo


def reviewed(capsys, repo, *args):
    capsys.readouterr()
    try:
        rc = cplat.main(["component", "build", "reviewed", SPEC_ID, *args, "--repo", str(repo)])
    except SystemExit as e:                                     # an argument parser refusing the form
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def body_of(repo, ref="HEAD"):
    return git(repo, "log", "-1", "--format=%b", ref)


# ---------------- AC-179.5: the reviewed commit is the freeze point ----------------

def test_the_command_writes_an_empty_signed_commit_with_findings_and_unresolved_lines_ac_179_5(world, capsys):  # AC-179.5
    before = head(world)
    rc, out, err = reviewed(capsys, world, "--findings", "2", "--unresolved", FINDING, "--unresolved", FINDING_2)
    assert rc == 0, err
    assert git(world, "log", "-1", "--format=%s") == SUBJECT
    assert git(world, "rev-parse", "HEAD~1") == before
    assert git(world, "diff", "--name-only", "HEAD~1", "HEAD") == ""                     # --allow-empty: no file
    lines = body_of(world).splitlines()
    assert lines[0] == "findings: 2"
    assert [ln for ln in lines if ln.startswith("unresolved:")] == [f"unresolved: {FINDING}", f"unresolved: {FINDING_2}"]
    assert any(ln.startswith("Signed-off-by: ") for ln in lines)
    assert out.strip() == f"REVIEWED {head(world)[:7]}: 2 findings, 2 unresolved"


def test_a_review_without_findings_freezes_at_once_with_findings_zero_ac_179_5(world, capsys):  # AC-179.5
    before = head(world)
    rc, out, err = reviewed(capsys, world)
    assert rc == 0, err
    assert body_of(world).splitlines()[0] == "findings: 0" and "unresolved:" not in body_of(world)
    assert git(world, "rev-parse", "HEAD~1") == before                                   # one commit, no tester round in between
    assert out.strip() == f"REVIEWED {head(world)[:7]}: 0 findings, 0 unresolved"


def test_a_second_call_writes_nothing_ac_179_5(world, capsys):  # AC-179.5
    reviewed(capsys, world)
    tip = head(world)
    rc, out, err = reviewed(capsys, world, "--findings", "3")
    assert rc == 0, err
    assert out.strip() == f"already reviewed at {tip[:7]}"
    assert head(world) == tip


def test_the_module_reads_the_reviewed_commit_and_its_unresolved_lines_back_ac_179_5(world, capsys):  # AC-179.5
    tr = testreview()
    assert tr.REVIEWED_MSG == "reviewed acceptance tests for"  # interface: commit subject the build greps for
    assert tr.reviewed_commit(world, SPEC_ID) is None and tr.unresolved(world, SPEC_ID) == []
    sha = tr.commit(world, SPEC_ID, 2, [FINDING, FINDING_2])
    assert sha == head(world)
    assert tr.reviewed_commit(world, SPEC_ID) == sha
    assert tr.unresolved(world, SPEC_ID) == [
        {"test": f"{TEST_FILE}::test_alert", "criterion": "AC-007.1", "what": "the fixture sends nothing but the test asserts a sent mail"},
        {"test": f"{TEST_FILE}::test_other", "criterion": "AC-007.2", "what": "the asserted text 'Dear user' is not defined by the contract"}]
    git(world, "commit", "-q", "--allow-empty", "-m", "feat: later work")
    assert tr.reviewed_commit(world, SPEC_ID) == sha                                     # newest such commit in the range
    assert tr.reviewed_commit(world, SPEC_ID, head=sha + "~1") is None                   # a head before it does not see it


def test_the_commit_of_another_spec_is_not_this_specs_review_ac_179_5(world):  # AC-179.5
    tr = testreview()
    git(world, "commit", "-q", "--allow-empty", "-m", "test(008): reviewed acceptance tests for 008-other\n\nfindings: 1\n"
        "unresolved: tests/x.py::t | AC-008.1 | something")
    assert tr.reviewed_commit(world, SPEC_ID) is None and tr.unresolved(world, SPEC_ID) == []


# ---------------- refusals ----------------

def test_uncommitted_test_changes_are_refused_with_the_fix_ac_179_5(world, capsys):  # AC-179.5
    write_tests(world, TESTS + "# edited\n")
    before = head(world)
    rc, out, err = reviewed(capsys, world)
    assert rc == 1 and "ERROR:" in err and "commit the tests first" in err
    assert head(world) == before


def test_a_branch_without_an_acceptance_tests_commit_is_refused_ac_179_5(tmp_path, capsys):  # AC-179.5
    repo = make_repo(tmp_path)
    git(repo, "checkout", "-qb", BRANCH)
    before = head(repo)
    rc, out, err = reviewed(capsys, repo)
    assert rc == 1 and "ERROR:" in err and "acceptance tests for" in err
    assert head(repo) == before


@pytest.mark.parametrize("bad", ["only one part", "tests/a.py::t | AC-007.1", "tests/a.py::t |  | what", " | AC-007.1 | what",
                                 "tests/a.py::t | AC-007.1 | ", "tests/a.py::t | AC-007.9 | what", "tests/a.py::t | AC-007.3 | withdrawn"])
def test_an_unresolved_value_needs_three_parts_and_an_active_criterion_ac_179_5(world, capsys, bad):  # AC-179.5
    before = head(world)
    rc, out, err = reviewed(capsys, world, "--findings", "1", "--unresolved", bad)
    assert rc == 1 and "ERROR:" in err
    assert head(world) == before


# ---------------- the red-tests unit needs the review ----------------

def test_the_red_tests_unit_is_open_until_the_review_commit_exists_ac_179_5(world, capsys):  # AC-179.5
    assert units.detect(world, "ship", SPEC_ID, "red-tests") is None                     # traced and committed, but not reviewed
    why = units.missing(world, "ship", SPEC_ID, "red-tests")
    assert why == (f"no commit 'reviewed acceptance tests for {SPEC_ID}' on feature/{SPEC_ID} "
                   "(the test review of build Phase 1)")
    rc, _, err = reviewed(capsys, world)
    assert rc == 0, err
    assert units.detect(world, "ship", SPEC_ID, "red-tests") == head(world)              # the checkpoint is the reviewed commit
    assert units.missing(world, "ship", SPEC_ID, "red-tests") == "nothing"


def test_an_untraced_test_still_keeps_the_unit_open_after_the_review_ac_179_5(world, capsys):  # AC-179.5
    write_tests(world, "# AC-007.1\n")
    git(world, "add", "-A")
    git(world, "commit", "-qm", "test(007): more tests")
    rc, _, err = reviewed(capsys, world)
    assert rc == 0, err
    assert units.detect(world, "ship", SPEC_ID, "red-tests") is None
    assert "cplat spec trace" in units.missing(world, "ship", SPEC_ID, "red-tests")


def test_the_next_step_of_the_red_tests_unit_names_the_review_and_its_command_ac_179_5():  # AC-179.5
    step = units.next_step("red-tests", SPEC_ID)
    assert "review" in step and "cplat component build reviewed" in step  # interface: next step prints the command
    assert f"cplat spec trace {SPEC_ID}" in step


# ---------------- AC-179.6: one round, the freeze after it, the rest listed ----------------

@pytest.fixture()
def building(tmp_path):
    """Spec 007 `building`, the acceptance tests commit `red`, a tester round commit, and the repo as (root, test file, red)."""
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    make(root, status="building")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    git(root, "checkout", "-qb", BRANCH)
    t = root / TEST_FILE
    t.parent.mkdir()
    t.write_text("# AC-007.1\ndef test_alert():\n    password = 'x'\n    assert send(password)\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", f"test(007): acceptance tests for {SPEC_ID}")
    return root, t, head(root)


def test_the_tests_freeze_at_the_reviewed_commit_after_the_tester_round_ac_179_6(building, monkeypatch, capsys):  # AC-179.6
    root, t, red = building
    t.write_text(t.read_text().replace("password = 'x'", "password = 'y'"))              # the tester's one round: a fixture fix
    git(root, "commit", "-qam", f"test(007): resolve test-review findings for {SPEC_ID}")
    testreview().commit(root, SPEC_ID, 1, [f"{TEST_FILE}::test_alert | AC-007.1 | the fixture contradicts the assertion"])
    end = head(root)
    (root / ".git" / "cplat-units.json").write_text(json.dumps({"version": 1, "command": "ship", "spec": "007", "units": [
        {"id": "plan", "status": "done", "commit": end}, {"id": "red-tests", "status": "done", "commit": end}]}))
    monkeypatch.chdir(root)
    assert spec.main(["test-diff", red]) == 0                                            # the round is part of the frozen tests
    assert f"base: {end[:7]}, where the red-tests unit ended" in capsys.readouterr().out
    t.write_text(t.read_text().replace("password = 'y'", "password = 'z'"))              # a later change is still a change
    assert spec.main(["test-diff", red]) == 1


def test_the_unresolved_findings_are_in_the_pr_block_ac_179_6(tmp_path, capsys, monkeypatch):  # AC-179.6
    monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
    repo = tmp_path / "app"
    (repo / BUILT_SPEC_DIR).mkdir(parents=True)
    (repo / BUILT_SPEC_DIR / "spec.md").write_text(BUILT_SPEC)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "checkout", "-qb", "feature/133-built-thing")
    git(repo, "commit", "-q", "--allow-empty", "-m", "test(133): acceptance tests for 133-built-thing")
    git(repo, "commit", "-q", "--allow-empty", "-m", "test(133): reviewed acceptance tests for 133-built-thing", "-m",
        "findings: 2\nunresolved: tests/test_a.py::test_a | AC-133.1 | the fixture contradicts the assertion")
    block = part(report(make_run(), repo, capsys)[1], "Hand-backs and fix rounds")
    assert "test review left open: tests/test_a.py::test_a (AC-133.1): the fixture contradicts the assertion" in block


def test_a_repo_without_a_review_commit_adds_no_line_to_the_pr_block_ac_179_6(tmp_path, capsys, monkeypatch):  # AC-179.6
    monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
    repo = tmp_path / "app"
    (repo / BUILT_SPEC_DIR).mkdir(parents=True)
    (repo / BUILT_SPEC_DIR / "spec.md").write_text(BUILT_SPEC)
    git(repo, "init", "-q", "-b", "main")
    block = part(report(make_run(), repo, capsys)[1], "Hand-backs and fix rounds")
    assert "test review left open" not in block


# ---------------- the prompts ----------------

def read(rel):
    return (ROOT / rel).read_text()


def phase(n):
    return read("plugins/component/commands/build.md").split(f"## Phase {n}")[1].split("\n## Phase ")[0]


def test_phase_1_reviews_the_tests_once_then_freezes_at_the_reviewed_commit_ac_179_5():  # AC-179.5
    p1 = phase(1)
    low = p1.lower()
    order = ["cplat spec trace", "test-review mode", "build reviewed",
             "red=$(git log -1 --format=%h --grep 'acceptance tests for')"]
    at = [low.index(x) for x in order]
    assert at == sorted(at), dict(zip(order, at))
    assert low.index("cplat quiet lint-fix") < low.index("build reviewed")
    assert "Test-review mode" in p1 and "TEST FINDINGS" in p1 and "reviewer" in p1


def test_the_tester_gets_the_findings_once_and_only_changes_the_tests_named_ac_179_6():  # AC-179.6
    p1 = phase(1)
    assert "resolve test-review findings for" in p1 and "UNRESOLVED:" in p1  # interface: commit subject the build greps for
    assert re.search(r"\bonce\b|at most one", p1)
    assert "--unresolved" in p1 and "git revert" in p1


def test_phase_1_is_skipped_when_the_reviewed_commit_exists_ac_179_5():  # AC-179.5
    p1 = phase(1)
    assert "reviewed acceptance tests for" in p1  # interface: commit subject the build greps for
    assert re.search(r"skip", p1, re.I)


def test_the_reviewer_has_a_test_review_mode_with_the_three_checks_ac_179_5():  # AC-179.5
    text = read("plugins/svc/agents/reviewer.md")
    assert "**Test-review mode.**" in text and "TEST FINDINGS: " in text
    for check in ("fixture", "does not define", "cannot produce"):
        assert check in text, check
    assert re.search(r"writes? nothing|never (?:edit|change|write)", text)


def test_verification_lists_the_unresolved_findings_ac_179_6():  # AC-179.6
    reviewer, p4 = read("plugins/svc/agents/reviewer.md"), phase(4)
    assert "TEST REVIEW" in reviewer and "Unresolved test-review" in reviewer and "Criterion | Finding" in reviewer
    assert "TEST REVIEW" in p4 and "reviewed acceptance tests" in p4


def test_unit_mode_describes_the_review_as_part_of_the_red_tests_unit_ac_179_5():  # AC-179.5
    text = read("plugins/component/references/unit-mode.md")
    row = next(ln for ln in text.splitlines() if ln.startswith("| `red-tests`"))
    assert "review" in row
