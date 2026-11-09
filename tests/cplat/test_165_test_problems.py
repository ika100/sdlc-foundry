"""Spec 165: a test problem with an obvious answer does not stop an unattended run (#595, #582, #583).

Seams: `spec.tightening` on file contents and `spec.tighten_test_change` / `spec.test_diff` on a git repo with one `building`
spec (the spec 160 `built` fixture); `quiet.main` with a fake devbox that fails the full run and passes the rerun; the prompts.
"""
import json
import os
import stat
from pathlib import Path

import pytest

import flaky
import quiet
import runs_built
import spec
from failsum_support import sample
from test_160_lint_suppressions import built, g  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]

PY = """# AC-002.4
def test_unavailable_answers_503():
    started = time.monotonic()
    a, b = call(), call()
    assert time.monotonic() - started < 10
"""
PY_TIGHT = """# AC-002.4
def test_unavailable_answers_503():
    for _ in range(2):
        started = time.monotonic()
        r = call()
        assert r.status_code == 503
        assert time.monotonic() - started < 5
"""


# ---------------- AC-165.1: the check refuses the obvious weakenings ----------------

def test_a_stricter_test_is_a_tightening_ac_165_1():  # AC-165.1
    assert spec.tightening(PY, PY_TIGHT, "tests/test_api.py") == (True, "")


@pytest.mark.parametrize("new,why", [
    (PY_TIGHT.replace("AC-002.4", "AC-002.5"), "criterion ids changed"),
    (PY_TIGHT.replace("def test_unavailable_answers_503", "def check_unavailable"), "test removed or renamed: test_unavailable_answers_503"),
    ("import pytest\n" + PY.replace("def test_", "@pytest.mark.skip\ndef test_"), "adds a skip"),
    (PY.replace("    assert time.monotonic() - started < 10\n", "    time.monotonic()\n"), "fewer assertions (1 before, 0 now)"),
    (PY, "unchanged"),
])
def test_a_weakened_test_is_refused_with_the_reason_ac_165_1(new, why):  # AC-165.1
    good, reason = spec.tightening(PY, new, "tests/test_api.py")
    assert not good and reason.startswith(why)


@pytest.mark.parametrize("name,old,new", [
    ("e2e/files.spec.ts", '// AC-1.1\ntest("lists", async () => {\n  expect(n).toBeLessThan(10);\n});\n',
     '// AC-1.1\ntest.skip("lists", async () => {\n  expect(n).toBeLessThan(5);\n});\n'),
    ("server_test.go", "// AC-1.1\nfunc TestList(t *testing.T) {\n\tif n > 10 {\n\t\tt.Fatal(n)\n\t}\n}\n",
     "// AC-1.1\nfunc TestList(t *testing.T) {\n\tt.Skip(\"later\")\n\tif n > 5 {\n\t\tt.Fatal(n)\n\t}\n}\n"),
    ("ListTest.java", "// AC-1.1\n@Test\nvoid lists() {\n  assertTrue(n < 10);\n}\n",
     "// AC-1.1\n@Disabled\n@Test\nvoid lists() {\n  assertTrue(n < 5);\n}\n"),
])
def test_a_new_skip_is_refused_in_every_language_ac_165_1(name, old, new):  # AC-165.1
    assert spec.tightening(old, old.replace("10", "5"), name) == (True, "")
    assert spec.tightening(old, new, name) == (False, "adds a skip")


def test_a_removed_test_is_found_in_every_language_ac_165_1():  # AC-165.1
    ts = '// AC-1.1\ntest("a", () => { expect(1).toBe(1); });\nit("b", () => { expect(2).toBe(2); });\n'
    go = "// AC-1.1\nfunc TestA(t *testing.T) { t.Error(1) }\nfunc TestB(t *testing.T) { t.Error(2) }\n"
    java = "// AC-1.1\n@Test\nvoid a() { assertTrue(x); }\n@Test\npublic void b() { assertTrue(y); }\n"
    for name, text, gone, keep in (("x.spec.ts", ts, "b", 'it("b", () => { expect(2).toBe(2); });\n'),
                                   ("x_test.go", go, "TestB", "func TestB(t *testing.T) { t.Error(2) }\n"),
                                   ("XTest.java", java, "b", "@Test\npublic void b() { assertTrue(y); }\n")):
        good, why = spec.tightening(text, text.replace(keep, ""), name)
        assert not good and why.startswith(f"test removed or renamed: {gone}")


def test_tighten_records_only_the_accepted_files_ac_165_1(built):  # AC-165.1
    root, t = built
    other = root / "tests" / "test_more.py"
    other.write_text("# AC-007.1\ndef test_more():\n    assert more()\n")
    g("add", "-A", cwd=root)
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "more", cwd=root)
    t.write_text(t.read_text() + "    assert sent_once()\n")
    other.write_text("# AC-007.1\ndef test_more():\n    more()\n")
    out = spec.tighten_test_change(root, "HEAD", ["tests/test_alerts.py", "tests/test_more.py"], "AC-007.1: looser")
    assert out["tests/test_alerts.py"] == (True, "")
    assert out["tests/test_more.py"] == (False, "fewer assertions (1 before, 0 now)")
    diff = spec.test_diff(root, "HEAD", [])
    assert diff["tests/test_alerts.py"] == (True, "tightened by an agent: AC-007.1: looser")
    assert not diff["tests/test_more.py"][0]


# ---------------- AC-165.2: a recorded tightening passes while unchanged ----------------

def test_a_later_change_to_a_tightened_test_is_checked_again_ac_165_2(built):  # AC-165.2
    root, t = built
    t.write_text(t.read_text() + "    assert sent_once()\n")
    spec.tighten_test_change(root, "HEAD", ["tests/test_alerts.py"], "AC-007.1: looser")
    assert spec.test_diff(root, "HEAD", [])["tests/test_alerts.py"][0]
    t.write_text(t.read_text() + "    assert also()\n")
    good, why = spec.test_diff(root, "HEAD", [])["tests/test_alerts.py"]
    assert not good and "tightened" not in why


def test_the_cli_needs_a_reason_and_exits_1_on_a_refusal_ac_165_2(built, monkeypatch, capsys):  # AC-165.2
    root, t = built
    monkeypatch.chdir(root)
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", "--tighten", "tests/test_alerts.py"]) == 2
    t.write_text(t.read_text().replace("    assert send(password)\n", "    send(password)\n"))
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", "--tighten", "tests/test_alerts.py", "--reason", "r"]) == 1
    assert "tests/test_alerts.py: refused — fewer assertions" in capsys.readouterr().out


# ---------------- AC-165.3: the PR lists a tightening apart from the user's approvals ----------------

def test_the_pr_block_names_a_tightened_test_apart_from_an_approval_ac_165_3():  # AC-165.3
    import inspect
    src = inspect.getsource(runs_built)
    assert '"test tightened by an agent" if item.get("kind") == "tightened" else "test change approved"' in src


def test_the_cli_records_the_tightening_in_the_run_record_ac_165_3(built, monkeypatch, capsys):  # AC-165.3
    import runs
    root, t = built
    added = []
    monkeypatch.setattr(runs, "current_run", lambda r: "run-1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **k: added.append((rid, name, item)))
    t.write_text(t.read_text() + "    assert sent_once()\n")
    assert spec.main(["--repo", str(root), "test-diff", "HEAD", "--tighten", "tests/test_alerts.py", "--task", "t3",
                      "--reason", "AC-007.1: looser"]) == 0
    assert added == [("run-1", "approved_test_diffs",
                      {"file": "tests/test_alerts.py", "task": "t3", "reason": "AC-007.1: looser", "kind": "tightened"})]


# ---------------- AC-165.4 – AC-165.6: the prompts ----------------

def read(rel):
    return (ROOT / rel).read_text()


def test_the_build_tightens_a_looser_test_and_the_reviewer_marks_and_lists_it_ac_165_4():  # AC-165.4
    build, ref, reviewer = (read("plugins/component/commands/build.md"), read("plugins/component/references/build-tighten.md"),
                            read("plugins/svc/agents/reviewer.md"))
    assert "`TEST LOOSER`" in build and "references/build-tighten.md" in build and "`TIGHTENED`" in build
    assert "cplat spec test-diff $RED --tighten" in ref and "Acceptance mode" in ref
    assert "fix-round verification" in ref and "Never loosen, delete or skip" in ref
    assert "TEST LOOSER" in reviewer and "## Tightened acceptance tests" in reviewer


def test_phase_1_runs_the_e2e_acceptance_tests_once_before_freezing_them_ac_165_5():  # AC-165.5
    phase1 = read("plugins/component/commands/build.md").split("## Phase 1")[1].split("## Phase 2")[0]
    assert "`cplat quiet e2e` once" in phase1 and "wrong failure" in phase1


def test_the_web_tester_never_starts_the_app_inside_a_test_ac_165_6():  # AC-165.6
    text = read("plugins/web/agents/tester.md")
    assert "Never start the app inside a test" in text and "`webServer.env`" in text


# ---------------- AC-165.7: a flaky test-fast failure is rerun once ----------------

@pytest.fixture()
def flaky_repo(tmp_path, monkeypatch):
    """A fake devbox: the full run prints $FAKE_OUT and exits 1; a rerun (`-- <tests>`) logs its arguments and exits $RERUN_RC."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "devbox"
    fake.write_text('#!/bin/sh\nif [ "$3" = "--" ]; then echo "$@" > "$ARGS_OUT"; echo "1 passed"; exit ${RERUN_RC:-0}; fi\n'
                    'cat "$FAKE_OUT"\nexit 1\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "myrepo"
    work.mkdir()
    (work / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"test-fast": "x", "quality": "y"}}}))
    monkeypatch.chdir(work)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    out, args = tmp_path / "out.txt", tmp_path / "args.txt"
    monkeypatch.setenv("FAKE_OUT", str(out))
    monkeypatch.setenv("ARGS_OUT", str(args))
    return out, args


PYTEST_ONE = """tests/test_todos_api.py F.                                                [100%]
=================================== FAILURES ===================================
______________________ test_unreachable_database_hanging _______________________
tests/test_todos_api.py:40: in test_unreachable_database_hanging
    assert elapsed < 3
E   assert 3.2 < 3
=========================== short test summary info ============================
FAILED tests/test_todos_api.py::test_unreachable_database_hanging - assert 3.2 < 3
========================= 1 failed, 1 passed in 4.10s ==========================
"""


def test_a_test_that_passes_alone_is_flaky_and_the_run_goes_on_ac_165_7(flaky_repo, capsys, monkeypatch):  # AC-165.7
    import runs
    out, args = flaky_repo
    out.write_text(PYTEST_ONE)
    added = []
    monkeypatch.setattr(runs, "current_run", lambda r: "run-1")
    monkeypatch.setattr(runs, "add_to", lambda rid, name, item, **k: added.append((name, item)))
    assert quiet.main(["test-fast"]) == 0
    printed = capsys.readouterr().out
    assert "flaky: 1 test(s) failed, then passed when run again alone" in printed
    assert "flaky: tests/test_todos_api.py::test_unreachable_database_hanging" in printed
    assert args.read_text().split() == ["run", "test-fast", "--", "tests/test_todos_api.py::test_unreachable_database_hanging"]
    assert added == [("flaky_tests", {"test": "tests/test_todos_api.py::test_unreachable_database_hanging", "script": "test-fast"})]


def test_a_failing_rerun_keeps_the_first_result_ac_165_7(flaky_repo, capsys, monkeypatch):  # AC-165.7
    out, _ = flaky_repo
    out.write_text(PYTEST_ONE)
    monkeypatch.setenv("RERUN_RC", "1")
    assert quiet.main(["test-fast"]) == 1
    printed = capsys.readouterr().out
    assert printed.startswith("FAILED (exit 1): devbox run test-fast") and "flaky" not in printed


def test_other_scripts_and_other_failures_are_never_rerun_ac_165_7(flaky_repo, capsys):  # AC-165.7
    out, args = flaky_repo
    out.write_text(PYTEST_ONE)
    assert quiet.main(["quality"]) == 1
    out.write_text(sample("mypy.log"))
    assert quiet.main(["test-fast"]) == 1
    assert not args.exists()


def summary_of(text):
    import failsum
    return failsum.summarize(text, title="t", check="test-fast", command="devbox run test-fast", exit_code=1,
                             log=Path("x.log"), root=None)


def test_more_than_five_failing_tests_is_not_a_flake_ac_165_7():  # AC-165.7
    lines = [f"FAILED tests/test_a.py::test_{i} - assert 0" for i in range(6)]
    text = "=== short test summary info ===\n" + "\n".join(lines) + "\n===== 6 failed, 1 passed in 1.00s =====\n"
    assert flaky.failed_tests(summary_of(text)) is None
    five = "=== short test summary info ===\n" + "\n".join(lines[:5]) + "\n===== 5 failed, 1 passed in 1.00s =====\n"
    assert flaky.failed_tests(summary_of(five)) == ("pytest", [f"tests/test_a.py::test_{i}" for i in range(5)])


def test_each_test_tool_gets_its_own_rerun_arguments_ac_165_7():  # AC-165.7
    assert flaky.rerun_args("go-test", ["example.com/api/internal.TestList/empty", "TestHealth"]) == \
        ["-run", "^(TestList|TestHealth)$"]
    assert flaky.rerun_args("surefire", ["com.acme.api.TodoControllerTest.lists"]) == \
        ["-Dtest=TodoControllerTest#lists", "-Dsurefire.failIfNoSpecifiedTests=false"]
    assert flaky.rerun_args("vitest", ["tests/page.test.tsx > Page > renders", "tests/page.test.tsx > Page > links"]) == \
        ["tests/page.test.tsx"]
