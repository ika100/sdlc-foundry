"""Spec 130 acceptance tests for `scripts/gate.sh` itself (AC-130.1, .2, .3, .4, .5, .6, .10, .12, .13).

Contract: design.md "scripts/gate.sh": `nothing`, `files` and `tests <gate> <runner> -- <command>` with the per-runner counting. The
runners are the stub tools of gates130_support.py (JUnit XML, `--- PASS:` lines, a Vitest JSON report), so the counting rules are checked
without a real toolchain. The source is templates/gitops-app/scripts/gate.sh; the other six templates carry a byte-identical copy."""
import os
import shutil
import subprocess

import pytest

from gates130_support import (FIX_TESTS, GATE_SOURCE, TEMPLATES, clean_env, line, make_stubs, secrets_line,
                              no_tests_line)

BASHES = ["bash"] + (["/bin/bash"] if os.path.exists("/bin/bash") and os.path.realpath("/bin/bash") != shutil.which("bash") else [])


@pytest.fixture(scope="session")
def stubs(tmp_path_factory):
    return make_stubs(tmp_path_factory.mktemp("stubs130-gate"))


@pytest.fixture()
def sandbox(tmp_path, stubs):
    """A git repo with scripts/gate.sh copied from the source, its own TMPDIR (to see leftovers) and the stub tools on PATH."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(GATE_SOURCE, repo / "scripts" / "gate.sh") if GATE_SOURCE.exists() else None
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    log = tmp_path / "stub.log"

    class Box:
        pass

    box = Box()
    box.repo, box.tmpdir, box.log = repo, tmpdir, log

    def gate(*args, bash="bash", cwd=None, **env):
        e = clean_env(stubs, STUB_LOG=str(log), TMPDIR=str(tmpdir), GIT_CEILING_DIRECTORIES=str(tmp_path), **env)
        return subprocess.run([bash, "scripts/gate.sh" if cwd is None else str(repo / "scripts" / "gate.sh"), *args],
                              cwd=cwd or repo, env=e, capture_output=True, text=True, timeout=60)

    box.gate = gate
    box.logtext = lambda: log.read_text() if log.exists() else ""
    return box


def runner_cmd(runner: str) -> list[str]:
    return {"pytest": ["uv", "run", "python", "-m", "pytest", "tests/"], "maven": ["mvn", "-B", "test"],
            "go": ["go", "test", "-v", "./..."], "vitest": ["pnpm", "test"]}[runner]


# ---------------- the source and its copies ----------------

def test_the_source_has_no_jinja_syntax_so_the_rendered_copy_is_byte_identical_ac_130_1():  # AC-130.1
    text = GATE_SOURCE.read_text()
    assert text.startswith("#!"), "gate.sh is a bash script"
    for token in ("{{", "{%", "{#"):
        assert token not in text, f"gate.sh must not contain {token!r} (the Python templates render every file with Jinja)"


@pytest.mark.parametrize("template", ["service-python", "library-python", "service-go", "service-java", "web-nextjs", "cluster-gitops"])
def test_every_template_carries_a_byte_identical_copy_ac_130_1(template):  # AC-130.1
    copy = TEMPLATES / template / "scripts" / "gate.sh"
    assert copy.is_file(), f"{template} has no scripts/gate.sh"
    assert copy.read_bytes() == GATE_SOURCE.read_bytes()


def test_the_sync_script_checks_the_gate_copies_ac_130_1():  # AC-130.1
    from gates130_support import ROOT
    assert "gate.sh" in (ROOT / "scripts" / "sync-template-copies.py").read_text()


# ---------------- gate.sh nothing ----------------

@pytest.mark.parametrize("bash", BASHES)
def test_nothing_prints_the_line_to_stderr_and_exits_1_ac_130_1(sandbox, bash):  # AC-130.1
    p = sandbox.gate("nothing", "test", "0 tests ran", FIX_TESTS, bash=bash)
    assert p.returncode == 1
    assert p.stderr == no_tests_line("test") + "\n"
    assert p.stdout == ""


@pytest.mark.parametrize("what", ["0 tests ran", "0 resources", "0 files compared", "0 files to scan"])
def test_nothing_formats_each_phrase_of_the_contract_ac_130_1(sandbox, what):  # AC-130.1
    p = sandbox.gate("nothing", "validate", what, "do the fix")
    assert p.returncode == 1 and p.stderr == line("validate", what, "do the fix") + "\n"


@pytest.mark.parametrize("args", [[], ["nothing"], ["nothing", "test"], ["nothing", "test", "0 tests ran"], ["bogus"],
                                  ["files"], ["tests"], ["tests", "test"], ["tests", "test", "pytest"],
                                  ["tests", "test", "pytest", "uv", "run", "pytest"],      # no `--`
                                  ["tests", "test", "rspec", "--", "echo", "x"],            # unknown runner
                                  ["tests", "test", "pytest", "--"]])                       # no command
def test_any_other_usage_prints_a_usage_line_and_exits_2_ac_130_1(sandbox, args):  # AC-130.1
    p = sandbox.gate(*args)
    assert p.returncode == 2, p.stderr
    assert p.stderr.strip() and "checked nothing" not in p.stderr
    assert "usage" in p.stderr.lower()


# ---------------- gate.sh files ----------------

def test_files_passes_silently_when_git_lists_a_file_ac_130_10(sandbox):  # AC-130.10
    (sandbox.repo / "a.txt").write_text("x")
    subprocess.run(["git", "add", "a.txt"], cwd=sandbox.repo, check=True)
    p = sandbox.gate("files", "secrets-scan", ".")
    assert p.returncode == 0 and p.stderr == "" and p.stdout == ""


def test_files_fails_with_the_line_on_an_empty_index_ac_130_10(sandbox):  # AC-130.10
    p = sandbox.gate("files", "secrets-scan", ".")
    assert p.returncode == 1
    assert p.stderr == secrets_line() + "\n"


def test_files_counts_what_the_pathspec_leaves_ac_130_10(sandbox):  # AC-130.10
    (sandbox.repo / "uv.lock").write_text("x")
    subprocess.run(["git", "add", "uv.lock"], cwd=sandbox.repo, check=True)
    only_lock = sandbox.gate("files", "secrets-scan", ":!*.lock")
    assert only_lock.returncode == 1 and only_lock.stderr == secrets_line() + "\n"
    (sandbox.repo / "main.py").write_text("x")
    subprocess.run(["git", "add", "main.py"], cwd=sandbox.repo, check=True)
    assert sandbox.gate("files", "secrets-scan", ":!*.lock").returncode == 0


def test_files_accepts_several_pathspecs_ac_130_10(sandbox):  # AC-130.10
    (sandbox.repo / "go.sum").write_text("x")
    (sandbox.repo / "x.lock").write_text("x")
    subprocess.run(["git", "add", "go.sum", "x.lock"], cwd=sandbox.repo, check=True)
    assert sandbox.gate("files", "secrets-scan", ":!go.sum", ":!*.lock").returncode == 1
    assert sandbox.gate("files", "secrets-scan", ":!go.sum").returncode == 0


def test_files_outside_a_git_repo_shows_gits_message_and_its_exit_without_the_line_ac_130_10(tmp_path, stubs):  # AC-130.10
    plain = tmp_path / "plain"
    (plain / "scripts").mkdir(parents=True)
    shutil.copy(GATE_SOURCE, plain / "scripts" / "gate.sh")
    env = clean_env(stubs, GIT_CEILING_DIRECTORIES=str(tmp_path))
    p = subprocess.run(["bash", "scripts/gate.sh", "files", "secrets-scan", "."], cwd=plain, env=env, capture_output=True, text=True)
    assert p.returncode == 128
    assert "not a git repository" in p.stderr
    assert "checked nothing" not in p.stderr


# ---------------- gate.sh tests: the counting per runner ----------------

# (runner, stub env) -> (exit, line expected)
CASES = [
    ("pytest", {"STUB_PYTEST": "empty", "STUB_PYTEST_EXIT": "5"}, 5, True),     # 5 is passed through
    ("pytest", {"STUB_PYTEST": "empty", "STUB_PYTEST_EXIT": "0"}, 1, True),
    ("pytest", {"STUB_PYTEST": "skipped"}, 1, True),
    ("pytest", {"STUB_PYTEST": "pass"}, 0, False),
    ("pytest", {"STUB_PYTEST": "mixed"}, 0, False),                              # 5 collected, 2 skipped: 3 ran
    ("pytest", {"STUB_PYTEST": "fail"}, 1, False),
    ("pytest", {"STUB_PYTEST": "broken", "STUB_BROKEN_EXIT": "4"}, 4, False),
    ("maven", {"STUB_MVN": "empty"}, 1, True),
    ("maven", {"STUB_MVN": "skipped"}, 1, True),
    ("maven", {"STUB_MVN": "pass"}, 0, False),
    ("maven", {"STUB_MVN": "fail"}, 1, False),
    ("maven", {"STUB_MVN": "broken", "STUB_BROKEN_EXIT": "4"}, 4, False),
    ("go", {"STUB_GO": "empty"}, 1, True),
    ("go", {"STUB_GO": "skipped"}, 1, True),
    ("go", {"STUB_GO": "pass"}, 0, False),
    ("go", {"STUB_GO": "fail"}, 1, False),
    ("go", {"STUB_GO": "broken", "STUB_BROKEN_EXIT": "4"}, 4, False),
    ("vitest", {"STUB_VITEST": "nofiles"}, 1, True),                             # "No test files found", exit 1
    ("vitest", {"STUB_VITEST": "zero"}, 1, True),
    ("vitest", {"STUB_VITEST": "skipped"}, 1, True),
    ("vitest", {"STUB_VITEST": "pass"}, 0, False),
    ("vitest", {"STUB_VITEST": "pass", "STUB_VITEST_FORMAT": "compact"}, 0, False),
    ("vitest", {"STUB_VITEST": "fail"}, 1, False),
    ("vitest", {"STUB_VITEST": "broken", "STUB_BROKEN_EXIT": "4"}, 4, False),
]
CASE_IDS = [f"{r}-{'-'.join(v for k, v in e.items() if k != 'STUB_BROKEN_EXIT')}" for r, e, _, _ in CASES]


@pytest.mark.parametrize("runner,env,code,has_line", CASES, ids=CASE_IDS)
def test_tests_counts_what_ran_and_decides_exit_and_line_ac_130_6(sandbox, runner, env, code, has_line):  # AC-130.2, AC-130.3, AC-130.4, AC-130.5, AC-130.6
    p = sandbox.gate("tests", "test", runner, "--", *runner_cmd(runner), **env)
    assert p.returncode == code, p.stdout + p.stderr
    if has_line:
        assert no_tests_line("test") in p.stderr.splitlines(), p.stderr
        assert p.stderr.count("checked nothing") == 1
    else:
        assert "checked nothing" not in p.stderr, "a broken build or a failing test is not 'add at least one test'"


def test_the_runners_output_is_shown_as_it_is_produced_ac_130_12(sandbox):  # AC-130.12
    p = sandbox.gate("tests", "test", "go", "--", *runner_cmd("go"), STUB_GO="pass")
    assert "--- PASS: TestA" in p.stdout
    q = sandbox.gate("tests", "test", "pytest", "--", *runner_cmd("pytest"), STUB_PYTEST="broken")
    assert "ImportError" in q.stderr


def test_extra_arguments_pass_through_to_the_runner_ac_130_12(sandbox):  # AC-130.12
    p = sandbox.gate("tests", "test-fast", "pytest", "--", *runner_cmd("pytest"), "-q", "--tb=line", "tests/test_x.py", STUB_PYTEST="pass")
    assert p.returncode == 0, p.stderr
    logged = sandbox.logtext()
    assert "tests/ -q --tb=line tests/test_x.py --junitxml=" in logged, logged


def test_the_gate_name_in_the_line_is_the_one_it_was_given_ac_130_1(sandbox):  # AC-130.1
    p = sandbox.gate("tests", "test-fast", "go", "--", *runner_cmd("go"), STUB_GO="empty")
    assert no_tests_line("test-fast") in p.stderr.splitlines()


def test_maven_removes_stale_reports_before_it_runs_ac_130_4(sandbox):  # AC-130.4
    stale = sandbox.repo / "target" / "surefire-reports"
    stale.mkdir(parents=True)
    (stale / "TEST-old.xml").write_text('<testsuite name="old" tests="4" errors="0" skipped="0" failures="0"></testsuite>')
    p = sandbox.gate("tests", "test", "maven", "--", *runner_cmd("maven"), STUB_MVN="empty")
    assert p.returncode == 1 and no_tests_line("test") in p.stderr.splitlines()


def test_failsafe_reports_count_for_maven_ac_130_4(sandbox):  # AC-130.4
    d = sandbox.repo / "target"
    stub_dir = d / "failsafe-reports"
    # a runner that only writes a failsafe report
    script = sandbox.repo / "writes-failsafe.sh"
    script.write_text(f'#!/bin/sh\nmkdir -p "{stub_dir}"\nprintf \'<testsuite name="it" tests="1" errors="0" skipped="0" failures="0"></testsuite>\' > "{stub_dir}/TEST-it.xml"\n')
    p = sandbox.gate("tests", "test", "maven", "--", "sh", str(script))
    assert p.returncode == 0, p.stderr


def test_a_cached_or_missing_vitest_report_counts_zero_ac_130_5(sandbox):  # AC-130.5
    script = sandbox.repo / "quiet.sh"
    script.write_text("#!/bin/sh\nexit 0\n")      # exit 0 and no report at all
    p = sandbox.gate("tests", "test", "vitest", "--", "sh", str(script))
    assert p.returncode == 1 and no_tests_line("test") in p.stderr.splitlines()


def test_vitest_gets_a_fresh_report_path_in_its_environment_ac_130_5(sandbox):  # AC-130.5
    script = sandbox.repo / "env.sh"
    script.write_text('#!/bin/sh\necho "REPORT=$VITEST_GATE_REPORT"\nexit 0\n')
    p = sandbox.gate("tests", "test", "vitest", "--", "sh", str(script))
    assert "REPORT=/" in p.stdout and p.stdout.strip().endswith("vitest.json"), p.stdout


@pytest.mark.parametrize("runner,env", [("pytest", {"STUB_PYTEST": "pass"}), ("pytest", {"STUB_PYTEST": "empty"}),
                                        ("vitest", {"STUB_VITEST": "pass"}), ("maven", {"STUB_MVN": "pass"}), ("go", {"STUB_GO": "pass"})])
def test_temporary_files_are_removed_on_exit_ac_130_12(sandbox, runner, env):  # AC-130.12
    sandbox.gate("tests", "test", runner, "--", *runner_cmd(runner), **env)
    assert list(sandbox.tmpdir.iterdir()) == []


@pytest.mark.parametrize("bash", BASHES)
def test_the_helper_runs_under_every_bash_the_platform_targets_ac_130_12(sandbox, bash):  # AC-130.12
    ok = sandbox.gate("tests", "test", "pytest", "--", *runner_cmd("pytest"), bash=bash, STUB_PYTEST="pass")
    assert ok.returncode == 0, ok.stderr
    bad = sandbox.gate("tests", "test", "vitest", "--", *runner_cmd("vitest"), bash=bash, STUB_VITEST="pass", STUB_VITEST_FORMAT="pretty")
    assert bad.returncode == 0, bad.stderr


# ---------------- AC-130.13: no opt-out ----------------

@pytest.mark.parametrize("name", ["SKIP", "SKIP_GATE", "ALLOW_EMPTY", "GATE_ALLOW_EMPTY", "PASS_WITH_NO_TESTS", "FORCE", "CHECKED_NOTHING_OK",
                                  "GATE_NAME", "VITEST_GATE_REPORT"])
def test_no_environment_variable_changes_the_outcome_of_nothing_ac_130_13(sandbox, name):  # AC-130.13
    p = sandbox.gate("nothing", "test", "0 tests ran", FIX_TESTS, **{name: "1"})
    assert p.returncode == 1 and p.stderr == no_tests_line("test") + "\n"


@pytest.mark.parametrize("name", ["SKIP", "ALLOW_EMPTY", "PASS_WITH_NO_TESTS", "GATE_ALLOW_EMPTY", "FORCE"])
def test_no_environment_variable_makes_an_empty_run_pass_ac_130_13(sandbox, name):  # AC-130.13
    p = sandbox.gate("tests", "test", "pytest", "--", *runner_cmd("pytest"), STUB_PYTEST="empty", STUB_PYTEST_EXIT="0", **{name: "1"})
    assert p.returncode == 1 and no_tests_line("test") in p.stderr.splitlines()
    q = sandbox.gate("files", "secrets-scan", ".", **{name: "1"})
    assert q.returncode == 1 and secrets_line() in q.stderr.splitlines()


@pytest.mark.parametrize("flag", ["--allow-empty", "--passWithNoTests", "--force", "-f", "--no-fail"])
def test_no_argument_before_the_separator_is_an_opt_out_ac_130_13(sandbox, flag):  # AC-130.13
    p = sandbox.gate("tests", "test", "pytest", flag, "--", *runner_cmd("pytest"), STUB_PYTEST="empty", STUB_PYTEST_EXIT="0")
    assert p.returncode != 0, "an unknown option must not turn the check off"
    assert p.returncode in (1, 2)
