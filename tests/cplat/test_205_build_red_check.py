"""Spec 205 acceptance tests: the build runs the red check before the tests freeze (AC-205.6) and fixes a broken harness without a
person (AC-205.7).

Seams: `cplat.main(["component", "build", "tests" | "reviewed", ...])` on the spec 172 `proj` repo (spec 007 `building`, shape
service-python, two acceptance test files); the build prompt and its references by structure (`structure.py`). Contract:
design.md sections 3, 4 and 5. The prompt tests pin only the `cplat` command lines the build runs, never sentences.
"""
import hashlib
import json
import re
import shlex
from pathlib import Path

import cplat
from structure import points_to, refs
from test_160_lint_suppressions import g
from test_172_build_tests import SPEC_ID, proj

ROOT = Path(__file__).resolve().parents[2]
BUILD_REL = "plugins/component/commands/build.md"
TIGHTEN_REL = "plugins/component/references/build-tighten.md"
FILES = ["tests/test_acceptance.py", "tests/test_hook.py"]
CMD = ["cplat", "quiet", "test-fast", "--red", "--"]
LINE = " ".join(CMD + FILES)
RED_CHECK = re.compile(r"cplat\s+quiet\s+test-fast\s+--red")   # the command, as a prompt names it
REFUSAL = "the red check has not passed on the current acceptance tests"
BRANCH = f"feature/{SPEC_ID}"


def pytest_repo(tmp_path, **kw):
    root = proj(tmp_path, **kw)
    (root / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "uv run pytest -q \"$@\""}}}))
    return root


def build_tests(capsys, root, *args):
    capsys.readouterr()
    try:
        rc = cplat.main(["component", "build", "tests", SPEC_ID, *args, "--repo", str(root)])
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


# ---------------- AC-205.6: `build tests --red` ----------------

def test_the_red_flag_prints_the_check_on_the_trace_files_test_fast_runs_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = pytest_repo(tmp_path)
    (root / "e2e").mkdir()
    (root / "e2e" / "journey_test.py").write_text("# AC-007.1\ndef test_j():\n    assert 1\n")      # a trace file test-fast does not run
    rc, out, err = build_tests(capsys, root, "--red")
    assert rc == 0, err
    assert out == LINE + "\n"                         # sorted; not tests/test_unit_a.py (no criterion), not e2e/


def test_the_files_are_shell_quoted_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = pytest_repo(tmp_path, files={"tests/test_a b.py": "# AC-007.1\ndef test_a():\n    assert f()\n",
                                        "tests/test_hook.py": "# AC-007.2\ndef test_h():\n    assert h()\n"})
    rc, out, err = build_tests(capsys, root, "--red")
    assert rc == 0, err
    assert out.strip() == " ".join(CMD + [shlex.join(["tests/test_a b.py", "tests/test_hook.py"])])


def test_a_repo_whose_test_fast_is_no_pytest_prints_none_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = proj(tmp_path)
    (root / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "go test ./..."}}}))
    rc, out, err = build_tests(capsys, root, "--red")
    assert rc == 0, err
    assert out == "none: test-fast does not run pytest\n"


def test_a_spec_without_files_test_fast_runs_prints_none_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = pytest_repo(tmp_path, files={"a.py": "x = 1\n"})
    rc, out, err = build_tests(capsys, root, "--red")
    assert rc == 0, err
    assert out == "none: no acceptance test files test-fast runs\n"


def test_the_json_form_adds_the_red_flag_ac_205_6(tmp_path, capsys):  # AC-205.6
    rc, out, err = build_tests(capsys, pytest_repo(tmp_path), "--red", "--json")
    assert rc == 0, err
    doc = json.loads(out)
    assert doc["red"] is True and doc["spec"] == SPEC_ID and doc["files"] == FILES and doc["command"] == LINE


def test_the_red_flag_excludes_a_task_and_load_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = pytest_repo(tmp_path)
    for extra in (["t1", "--red"], ["--load", "--red"]):
        rc, out, err = build_tests(capsys, root, *extra)
        assert rc != 0 and "use one of a task, --load, --red" in err + out


# ---------------- AC-205.6: the freeze gate of `build reviewed` ----------------

def reviewed_world(tmp_path):
    root = pytest_repo(tmp_path)
    g("checkout", "-qb", BRANCH, cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"test(007): acceptance tests for {SPEC_ID}", "--allow-empty", cwd=root)
    return root


def record(root, **over):
    files = {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in FILES}
    rec = {"head": g("rev-parse", "HEAD", cwd=root).strip(), "exit": 0, "files": files, "at": "2026-11-18T10:00:00Z"} | over
    (root / ".git" / "cplat-red-check.json").write_text(json.dumps(rec))


def reviewed(capsys, root):
    capsys.readouterr()
    try:
        rc = cplat.main(["component", "build", "reviewed", SPEC_ID, "--repo", str(root)])
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def subjects(root):
    return g("log", "--format=%s", cwd=root).splitlines()


def test_the_tests_do_not_freeze_without_a_passing_red_check_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = reviewed_world(tmp_path)
    before = subjects(root)
    rc, out, err = reviewed(capsys, root)                          # no record at all
    assert rc != 0 and REFUSAL in err and "cplat component build tests" in err + out and "--red" in err + out  # interface: the command the refusal names
    assert subjects(root) == before                                # no reviewed commit
    record(root, exit=1)                                           # the check failed
    assert reviewed(capsys, root)[0] != 0 and subjects(root) == before
    record(root, files={FILES[0]: hashlib.sha256((root / FILES[0]).read_bytes()).hexdigest()})   # a file of the command is missing
    assert reviewed(capsys, root)[0] != 0 and subjects(root) == before
    record(root)
    (root / FILES[1]).write_text((root / FILES[1]).read_text() + "\n# edited after the check\n")   # content changed since
    rc, out, err = reviewed(capsys, root)
    assert rc != 0 and REFUSAL in err and subjects(root) == before
    g("checkout", "--", FILES[1], cwd=root)
    record(root)                                                   # the check passed on the current content
    rc, out, err = reviewed(capsys, root)
    assert rc == 0, err
    assert subjects(root)[0] == f"test(007): reviewed acceptance tests for {SPEC_ID}"


def test_already_reviewed_stays_first_and_other_repos_are_not_gated_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = reviewed_world(tmp_path)
    assert reviewed(capsys, root)[0] != 0                          # gated
    (root / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "go test ./..."}}}))
    rc, out, err = reviewed(capsys, root)                          # not a pytest repo: as today
    assert rc == 0, err
    (root / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "uv run pytest"}}}))
    rc, out, err = reviewed(capsys, root)                          # reviewed already: first, whatever the record says
    assert rc == 0 and out.startswith("already reviewed at ")


def test_a_pytest_repo_without_test_files_is_not_gated_ac_205_6(tmp_path, capsys):  # AC-205.6
    root = pytest_repo(tmp_path, files={"a.py": "x = 1\n"})
    g("checkout", "-qb", BRANCH, cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"test(007): acceptance tests for {SPEC_ID}", "--allow-empty", cwd=root)
    assert build_tests(capsys, root, "--red")[1] == "none: no acceptance test files test-fast runs\n"
    assert reviewed(capsys, root)[0] == 0


# ---------------- AC-205.6, AC-205.7: the build prompts, by structure ----------------

def build_text():
    """The build prompt and every reference it points to."""
    text = (ROOT / BUILD_REL).read_text()
    for key in sorted(refs(BUILD_REL)):
        if key.startswith("references/") or "/references/" in key:
            path = ROOT / "plugins" / "component" / key[key.index("references/"):]
            if path.is_file():
                text += "\n" + path.read_text()
    return text


def test_phase_1_runs_the_red_check_and_records_wrong_failures_ac_205_6():  # AC-205.6
    text = build_text()
    assert points_to(BUILD_REL, "cplat component build")
    assert re.search(r"cplat component build tests[^\n`]*--red", text)
    assert "--wrong-failure" in text and RED_CHECK.search(text)     # interface: the flags the build runs
    assert "cplat component build reviewed" in text


def test_the_harness_fix_uses_the_red_check_and_the_tightening_record_ac_205_7():  # AC-205.7
    assert points_to(BUILD_REL, "references/build-tighten.md")
    tighten = (ROOT / TIGHTEN_REL).read_text()
    assert RED_CHECK.search(tighten)                                             # interface: the check that finds a test error
    assert "cplat spec test-diff --tighten" in tighten and "--reason" in tighten   # interface: the existing record command
    assert "tester" in tighten and "2.5" in build_text()


def test_the_tester_agents_run_their_own_red_check_ac_205_7():  # AC-205.7
    text = (ROOT / "plugins" / "svc" / "agents" / "tester.md").read_text()
    assert RED_CHECK.search(text)
