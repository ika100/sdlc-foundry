"""Spec 172: `cplat component build tests` prints a task's and the load run's test command (AC-172.4, AC-172.6).

Seam: `cplat.main(["component", "build", "tests", ...])` on a small git repo with spec 007 `building` and a plan; the shape comes
from `.copier-answers.yml`. The prompt tests pin the phrases of design.md, section 7.
"""
import json
import shlex
from pathlib import Path

import pytest

import cplat
import spec
from test_160_lint_suppressions import g
from test_spec import make

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "plugins" / "component" / "commands" / "build.md"
SPEC_ID = "007-price-alerts"

PLAN = """---
spec_id: 007-price-alerts
shape: service-python
spec_hash: {hash}
tasks:
{tasks}
---

## t1 — model
"""
TASKS = """  - {id: t1, title: model, files: [a.py, tests/test_unit_a.py], covers: [AC-007.1], parallel_safe: true, depends_on: []}
  - {id: t2, title: hook, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: []}"""


def commit(root, msg):
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, cwd=root)
    return g("rev-parse", "HEAD", cwd=root).strip()


def proj(tmp_path, tasks=TASKS, shape="service-python", files=None):
    root = tmp_path / "app"
    root.mkdir()
    g("init", "-q", "-b", "main", cwd=root)
    (root / ".copier-answers.yml").write_text(f"_src_path: gh:ika100/sdlc-foundry/templates/{shape}\nproject_name: app\n")
    make(root, status="building", plan=False)
    d = root / "docs" / "specs" / SPEC_ID
    (d / "plan.md").write_text(PLAN.format(hash=spec.read(d).ac_hash(), tasks=tasks))
    for rel, text in (files if files is not None else {
            "tests/test_acceptance.py": "# AC-007.1\ndef test_a():\n    assert f()\n",
            "tests/test_hook.py": "# AC-007.2\ndef test_h():\n    assert h()\n",
            "tests/test_unit_a.py": "def test_u():\n    assert 1\n", "tests/test_other.py": "def test_o():\n    assert 1\n",
            "a.py": "x = 1\n"}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    commit(root, "base")
    return root


def run(capsys, root, *args):
    capsys.readouterr()
    try:
        rc = cplat.main(["component", "build", "tests", SPEC_ID, *args, "--repo", str(root)])
    except SystemExit as e:                                   # an argument parser refusing the form
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


# ---------------- AC-172.4: a coder's test command ----------------

def test_a_task_gets_its_criteria_tests_and_its_own_test_files_ac_172_4(tmp_path, capsys):  # AC-172.4
    root = proj(tmp_path)
    rc, out, err = run(capsys, root, "t1")
    assert rc == 0, err
    assert out == "cplat quiet test-fast -- tests/test_acceptance.py tests/test_unit_a.py\n"       # not tests/test_hook.py, not a.py
    rc, out, err = run(capsys, root, "t2")
    assert rc == 0 and out == "cplat quiet test-fast -- tests/test_hook.py\n"


def test_the_json_form_names_files_args_and_command_ac_172_4(tmp_path, capsys):  # AC-172.4
    rc, out, err = run(capsys, proj(tmp_path), "t1", "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["spec"] == SPEC_ID and doc["task"] == "t1" and doc["load"] is False
    assert doc["files"] == ["tests/test_acceptance.py", "tests/test_unit_a.py"]
    assert doc["args"] == doc["files"] and doc["command"] == "cplat quiet test-fast -- tests/test_acceptance.py tests/test_unit_a.py"


def test_a_task_without_test_files_falls_back_to_the_whole_suite_ac_172_4(tmp_path, capsys):  # AC-172.4
    tasks = "  - {id: t1, title: model, files: [a.py], covers: [AC-007.2], parallel_safe: true, depends_on: []}"
    root = proj(tmp_path, tasks, files={"a.py": "x = 1\n"})
    rc, out, err = run(capsys, root, "t1")
    assert rc == 0 and out == "cplat quiet test-fast\n"


def test_a_go_task_selects_its_tests_with_run_ac_172_4(tmp_path, capsys):  # AC-172.4
    tasks = "  - {id: t1, title: model, files: [server.go, server_test.go], covers: [AC-007.1], parallel_safe: true, depends_on: []}"
    root = proj(tmp_path, tasks, "service-go", {"server.go": "package s\n", "server_test.go":
                                              "package s\n\nfunc TestA(t *testing.T) {}\nfunc TestB(t *testing.T) {}\n"})
    rc, out, err = run(capsys, root, "t1")
    assert rc == 0, err
    assert out == "cplat quiet test-fast -- " + shlex.join(["-run", "^(TestA|TestB)$"]) + "\n"


def test_a_java_task_selects_its_classes_with_dtest_ac_172_4(tmp_path, capsys):  # AC-172.4
    tasks = ("  - {id: t1, title: model, files: [src/test/java/FooTest.java], covers: [AC-007.1], parallel_safe: true, "
             "depends_on: []}")
    root = proj(tmp_path, tasks, "service-java", {"src/test/java/FooTest.java": "class FooTest {}\n"})
    rc, out, err = run(capsys, root, "t1")
    assert rc == 0, err
    assert out == "cplat quiet test-fast -- " + shlex.join(["-Dtest=FooTest", "-Dsurefire.failIfNoSpecifiedTests=false"]) + "\n"


@pytest.mark.parametrize("args", [["nosuch"], ["t1", "--load"]])
def test_an_unknown_task_or_a_task_with_load_is_an_error_ac_172_4(tmp_path, capsys, args):  # AC-172.4
    rc, out, err = run(capsys, proj(tmp_path), *args)
    assert rc == 1 and out == "" and err.startswith("ERROR:")


# ---------------- AC-172.6: the load run's command ----------------

def test_the_load_run_names_the_acceptance_files_and_the_files_the_build_changed_ac_172_6(tmp_path, capsys):  # AC-172.6
    root = proj(tmp_path)
    base = g("rev-parse", "HEAD", cwd=root).strip()
    (root / "tests" / "test_added.py").write_text("def test_added():\n    assert 1\n")
    (root / "tests" / "test_other.py").write_text("def test_o():\n    assert 2\n")
    (root / "tests" / "test_unit_a.py").unlink()
    (root / "a.py").write_text("x = 2\n")
    commit(root, "feat: the build")
    rc, out, err = run(capsys, root, "--load", "--base", base)
    assert rc == 0, err
    assert out == ("cplat quiet test-fast --repeat 3 -- "
                   "tests/test_acceptance.py tests/test_added.py tests/test_hook.py tests/test_other.py\n")


def test_the_load_run_json_form_ac_172_6(tmp_path, capsys):  # AC-172.6
    root = proj(tmp_path)
    rc, out, err = run(capsys, root, "--load", "--base", "HEAD", "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["load"] is True and doc["task"] is None
    assert doc["files"] == ["tests/test_acceptance.py", "tests/test_hook.py"]
    assert doc["command"] == "cplat quiet test-fast --repeat 3 -- tests/test_acceptance.py tests/test_hook.py"


def test_the_load_run_is_skipped_with_a_reason_when_there_is_nothing_to_repeat_ac_172_6(tmp_path, capsys):  # AC-172.6
    root = proj(tmp_path, files={"a.py": "x = 1\n"})
    rc, out, err = run(capsys, root, "--load", "--base", "HEAD")
    assert rc == 0 and out == "none: no test files to repeat\n"


def test_a_java_build_never_runs_under_load_ac_172_6(tmp_path, capsys):  # AC-172.6
    root = proj(tmp_path, shape="service-java", files={"src/test/java/FooTest.java": "// AC-007.1\nclass FooTest {}\n"})
    rc, out, err = run(capsys, root, "--load", "--base", "HEAD")
    assert rc == 0 and out == "none: service-java runs share target/, so they cannot run at once (ADR-094)\n"


# ---------------- the build prompt (AC-172.4, AC-172.6) ----------------

def _section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_the_coder_runs_its_own_tests_not_the_whole_suite_ac_172_4():  # AC-172.4
    build = BUILD.read_text()
    coder = _section(build, "### 2.3", "### 2.4")
    assert "cplat quiet test-fast -- <the task's test files>" in coder
    assert "cplat component build tests" in coder and "cplat quiet quality" in coder
    done = next(ln for ln in coder.splitlines() if "**Done when:**" in ln)
    assert "cplat quiet test-fast -- " in done and "`cplat quiet test-fast`" not in done


def test_the_whole_suite_still_runs_once_in_2_5_and_ci_in_phase_3_ac_172_4():  # AC-172.4
    build = BUILD.read_text()
    assert "cplat quiet test-fast`" in _section(build, "### 2.5", "## Phase 3")
    assert "cplat quiet ci" in _section(build, "## Phase 3", "## Phase 4")
    assert "cplat quiet test-fast -- " in _section(build, "### 2.3", "### 2.4")          # and the coder's line differs from it


def test_the_load_run_is_step_2_6_between_2_5_and_phase_3_ac_172_6():  # AC-172.6
    build = BUILD.read_text()
    assert build.index("### 2.5") < build.index("### 2.6 Under load") < build.index("## Phase 3")
    step = _section(build, "### 2.6 Under load", "## Phase 3")
    assert "cplat component build tests" in step and "--load" in step
    assert "cplat quiet test-fast --repeat 3 --" in step and "references/build-load-run.md" in step
    assert "none:" in step and "tester" in step and "2 rounds" in step


def test_step_2_6_sends_failing_tests_to_a_coder_and_repeats_after_the_tester_fix_ac_172_6():  # AC-172.6
    build = BUILD.read_text()
    step = _section(build, "### 2.6 Under load", "## Phase 3")
    assert "Exit 1 → failing tests to a coder as in 2.5" in step
    assert "coder of a task covering that criterion" in _section(build, "### 2.5", "### 2.6")
    assert "Exit 3 → `${CLAUDE_PLUGIN_ROOT}/references/build-load-run.md` (the tester fixes the harness; 2 rounds, then escalate)" in step
    ref = (ROOT / "plugins" / "component" / "references" / "build-load-run.md").read_text()
    assert "Read from `/component:build` 2.6 on exit 3." in ref
    assert "Run the repeated run again; after 2 rounds" in ref
    assert ref.index("**tester**") < ref.index("cplat spec test-diff $RED") < ref.index("Run the repeated run again")


def test_the_load_run_reference_tells_the_tester_to_fix_the_harness_only_ac_172_6():  # AC-172.6
    text = (ROOT / "plugins" / "component" / "references" / "build-load-run.md").read_text()
    assert "Harness mode" in text and "fixtures" in text and "helpers" in text and "fakes" in text and "process clean-up" in text
    assert "assertion" in text and "cplat spec test-diff $RED" in text and "build-test-approval.md" in text
    assert "cplat platform runs end --outcome escalated" in text and "flaky under load" in text
