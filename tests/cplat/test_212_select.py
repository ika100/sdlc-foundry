"""Spec 212: local test runs run what a change can affect (AC-212.1 to AC-212.7).

Each test builds a scratch repo (`support_212.Repo`) with copies of the real selector, trace module, recording plugin and
test-fast recipe, records its small suite in a nested pytest and asks its selector.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from support_212 import ALL_TESTS, Repo, clean_env
from system_fixtures import ROOT
from waiting import with_prelude

CPLAT = ROOT / "scripts" / "cplat" / "cplat.py"


@pytest.fixture()
def repo(tmp_path):
    return Repo(tmp_path / "repo")


def deps(m: dict, test: str) -> set[str]:
    d = m["tests"][f"tests/cplat/{test}"]
    return set(d["files"]) | {f"dir:{x}" for x in d["dirs"]} | {f"tree:{x}" for x in d["trees"]}


# ---- AC-212.2: what a recorded full run counts as a test file's dependencies ----

def test_a_recorded_map_holds_imports_reads_listings_subprocess_arguments_and_cplat_children_ac_212_2(repo):
    m = repo.record(workers=0)
    assert {"scripts/cplat/mod_a.py", "scripts/cplat/mod_c.py"} <= deps(m, "test_static.py")   # imported, and what it imports
    assert "scripts/cplat/mod_lazy.py" in deps(m, "test_lazy_second.py")   # imported in the test after another test did
    reads = deps(m, "test_reads.py")
    assert {"plugins/prompt.md", "dir:plugins/listed"} <= reads
    assert "tree:templates/tree" in deps(m, "test_subprocess_arg.py")
    child = deps(m, "test_cplat_child.py")
    assert {"scripts/cplat/cmd_show.py", "scripts/cplat/cmd_helper.py", "plugins/prompt.md"} <= child   # in the cplat process
    for t in ("test_session_one.py", "test_session_two.py"):   # set up in the first test, reused by the second
        assert {"data/session.txt", "scripts/cplat/mod_fixture.py"} <= deps(m, t), t
    for t in ("test_render_one.py", "test_render_two.py"):     # built in the first test, copied by both
        assert {"templates/t/file.txt", "scripts/cplat/mod_render.py"} <= deps(m, t), t
    assert all("scripts/cplat/mod_patched.py" not in deps(m, t.split("/")[-1]) for t in ALL_TESTS)   # an autouse patch only


def test_a_map_recorded_with_workers_holds_the_same_cross_test_dependencies_ac_212_2(repo):
    m = repo.record(workers=2)
    assert set(m["tests"]) == set(ALL_TESTS)
    assert {"scripts/cplat/cmd_show.py", "plugins/prompt.md"} <= deps(m, "test_cplat_child.py")
    for t in ("test_session_one.py", "test_session_two.py"):
        assert "data/session.txt" in deps(m, t), t
    for t in ("test_render_one.py", "test_render_two.py"):
        assert "templates/t/file.txt" in deps(m, t), t


def test_the_real_cplat_records_its_command_module_when_started_from_a_recorded_run_ac_212_2(tmp_path):
    env = clean_env(SDLC_DEPS_TRACE=str(tmp_path), SDLC_DEPS_ROOT=str(ROOT))
    subprocess.run([sys.executable, str(CPLAT), "shape"], cwd=ROOT, capture_output=True, text=True, env=env, timeout=60)
    records = [json.loads(f.read_text()) for f in tmp_path.glob("*.json")]
    assert len(records) == 1
    assert {"scripts/cplat/cplat.py", "scripts/cplat/shapecmd.py", "scripts/cplat/core.py"} <= set(records[0]["files"])


# ---- AC-212.1: the selection ----

def test_a_changed_module_selects_exactly_the_test_files_that_depend_on_it_and_says_so_ac_212_1(repo):
    m = repo.record()
    repo.write("scripts/cplat/mod_c.py", "VALUE = 1  # changed\n")
    repo.write("plugins/prompt.md", "the prompt, changed\n")
    mode, tests, msg = repo.plan()
    assert mode == "select"
    assert tests == ["tests/cplat/test_cplat_child.py", "tests/cplat/test_reads.py", "tests/cplat/test_static.py"]
    assert msg == (f"test-fast: 3 of {len(ALL_TESTS)} test files (map at {m['commit'][:9]}, 2 changed file(s)); "
                   "devbox run test-fast --full runs every test")


def test_changed_new_and_previously_red_test_files_are_selected_ac_212_1(repo):
    repo.record(SCRATCH_RED="1")
    repo.write("tests/cplat/test_static.py", "import mod_a\n\ndef test_static():\n    assert mod_a.VALUE >= 2\n")
    repo.write("tests/cplat/test_brand_new.py", "def test_new():\n    assert True\n")
    repo.write("plugins/listed/two.md", "a new file in a listed folder\n")
    mode, tests, _ = repo.plan()
    assert mode == "select"
    assert tests == ["tests/cplat/test_brand_new.py", "tests/cplat/test_reads.py", "tests/cplat/test_red.py",
                     "tests/cplat/test_static.py"]


def test_a_file_below_a_subprocess_argument_selects_the_test_that_handed_it_over_ac_212_1(repo):
    repo.record()
    repo.write("templates/tree/inner/deep.txt", "deeper\n")
    assert repo.plan()[:2] == ("select", ["tests/cplat/test_subprocess_arg.py"])


# ---- AC-212.3: when the whole suite runs ----

def test_without_a_map_the_whole_suite_runs_and_records_one_ac_212_3(repo):
    mode, _, msg = repo.plan()
    assert mode.startswith("full ") and mode.split(" ", 1)[1].startswith(str(repo.store) + "/")
    assert msg == f"test-fast: all {len(ALL_TESTS)} test files: no dependency map yet; this run records a new dependency map"


@pytest.mark.parametrize("shared", ["tests/cplat/conftest.py", "tests/cplat/depsmap.py", "requirements-test.txt",
                                    "tests/cplat/pytest.ini", "scripts/testselect.py", "scripts/cplat/depstrace.py"])
def test_a_change_to_a_shared_file_runs_the_whole_suite_ac_212_3(repo, shared):
    repo.record()
    repo.write(shared, (repo.root / shared).read_text() + "\n# changed\n")
    mode, _, msg = repo.plan()
    assert mode.startswith("full ")
    assert f"{shared} is shared by every test" in msg


def test_a_module_conftest_imports_at_module_level_is_shared_ac_212_3(repo):
    repo.write("tests/cplat/suite_helpers.py", "HELP = 1\n")
    conftest = repo.root / "tests/cplat/conftest.py"
    conftest.write_text(conftest.read_text().replace("import pytest\n", "import pytest\nimport suite_helpers\n", 1))
    repo.commit("conftest imports a helper")
    repo.record()
    repo.write("tests/cplat/suite_helpers.py", "HELP = 2\n")
    assert "tests/cplat/suite_helpers.py is shared by every test" in repo.plan()[2]


def test_changed_code_no_test_reads_runs_the_whole_suite_and_an_unread_page_runs_nothing_ac_212_3(repo):
    repo.record()
    repo.write("docs/page.md", "still nobody reads this page\n")
    mode, tests, msg = repo.plan()
    assert (mode, tests) == ("none", [])
    assert msg.startswith(f"test-fast: 0 of {len(ALL_TESTS)} test files: no test file can see this change")
    repo.write("scripts/cplat/mod_unread.py", "VALUE = 'changed'\n")
    mode, _, msg = repo.plan()
    assert mode.startswith("full ")
    assert "scripts/cplat/mod_unread.py is code or configuration no test of the map reads" in msg


def test_a_selection_of_more_than_half_the_test_files_runs_the_whole_suite_ac_212_3(repo):
    repo.record()
    for t in ALL_TESTS[: len(ALL_TESTS) // 2 + 1]:
        repo.write(t, (repo.root / t).read_text() + "\n# touched\n")
    mode, _, msg = repo.plan()
    assert mode.startswith("full ")
    assert f"the change reaches {len(ALL_TESTS) // 2 + 1} of {len(ALL_TESTS)} test files" in msg


def test_an_interrupted_or_empty_run_records_no_map_ac_212_3(repo):
    repo.store.mkdir(parents=True)
    r = repo.pytest("--deps-record", str(repo.store / "x.json"), "tests/cplat", "-k", "nothing_matches_this")
    assert r.returncode == 5
    assert not list(repo.store.glob("*.json"))


# ---- AC-212.4: test-fast's arguments ----

def fake_uv(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir, log = tmp_path / "bin", tmp_path / "uv.log"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(with_prelude(f'#!/bin/sh\necho "$*" >> "{log}"\n'))
    (bin_dir / "uv").chmod(0o755)
    return clean_env(PATH=f"{bin_dir}:{os.environ['PATH']}"), log


def run_recipe(repo: Repo, env: dict[str, str], name: str, *args: str) -> subprocess.CompletedProcess:
    """The devbox recipe `name` of the scratch repo's copy of devbox.json, run as devbox runs it (sh, arguments as $@)."""
    recipe = json.loads((repo.root / "devbox.json").read_text())["shell"]["scripts"][name]
    return subprocess.run(["sh", "-c", recipe, "sh", *args], cwd=repo.root, capture_output=True, text=True, env=env, timeout=60)


SUITE = "run --with-requirements requirements-test.txt pytest tests/cplat -q -n auto"
GIVEN = "run --with-requirements requirements-test.txt pytest -q -n auto"


def test_test_fast_selects_without_arguments_records_with_full_and_runs_given_tests_as_before_ac_212_4(repo, tmp_path):
    env, log = fake_uv(tmp_path)
    r = run_recipe(repo, env, "test-fast")
    assert r.returncode == 0, r.stderr
    assert "no dependency map yet" in r.stderr
    assert log.read_text().startswith(f"{SUITE} --deps-record {repo.store}/")
    repo.record()
    repo.write("scripts/cplat/mod_lazy.py", "VALUE = 'lazy!'\n")
    for args, expected in [((), f"{SUITE} --deps-select=tests/cplat/test_lazy_first.py,tests/cplat/test_lazy_second.py"),
                           (("tests/cplat/test_static.py",), f"{GIVEN} tests/cplat/test_static.py"),
                           (("-k", "static"), f"{GIVEN} tests/cplat -k static"),
                           (("tests/cplat/test_static.py::test_static", "-x"), f"{GIVEN} tests/cplat/test_static.py::test_static -x")]:
        log.unlink()
        r = run_recipe(repo, env, "test-fast", *args)
        assert r.returncode == 0, r.stderr
        assert log.read_text().strip() == expected, args
    log.unlink()
    r = run_recipe(repo, env, "test-fast", "--full")
    assert "--full given" in r.stderr
    assert log.read_text().startswith(f"{SUITE} --deps-record {repo.store}/")
    assert json.loads((ROOT / "devbox.json").read_text())["shell"]["scripts"]["test"] == "devbox run test-fast --full"


def test_a_selection_runs_only_its_test_files_and_an_empty_one_passes_with_nothing_run_ac_212_4(repo):
    r = repo.pytest("tests/cplat", "--deps-select=tests/cplat/test_static.py,tests/cplat/test_reads.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 passed" in r.stdout
    for workers in (0, 2):
        r = repo.pytest("tests/cplat", "--deps-select=", workers=workers)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "passed" not in r.stdout and "failed" not in r.stdout
    r = repo.pytest("tests/cplat", "-k", "nothing_matches_this", workers=0)
    assert r.returncode == 5   # without a selection, a run that collects nothing still fails as before


def test_test_fast_says_why_it_runs_nothing_when_no_test_file_can_see_the_change_ac_212_4(repo, tmp_path):
    env, log = fake_uv(tmp_path)
    repo.record()
    repo.write("docs/page.md", "changed page\n")
    r = run_recipe(repo, env, "test-fast")
    assert r.returncode == 0
    assert log.read_text().strip() == f"{SUITE} --deps-select="
    assert "test-fast: 0 of" in r.stderr and "devbox run test-fast --full runs every test" in r.stderr


# ---- AC-212.5: ci-local.sh ----

def ci_local_world(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """A copy of ci-local.sh among fakes: every step passes; the selector, the suite run and the site and render steps log."""
    w, log = tmp_path / "ci", tmp_path / "calls.log"
    (w / "scripts").mkdir(parents=True)
    (w / "site" / "node_modules").mkdir(parents=True)
    (w / "scripts" / "ci-local.sh").write_text((ROOT / "scripts" / "ci-local.sh").read_text())
    (w / "scripts" / "uv-script.sh").write_text("exit 0\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {"jq": 'case "$1" in -e) exit 0 ;; *) echo 1 ;; esac',
             "python3": f'if [ "$1" = scripts/testselect.py ]; then echo "select $*" >> "{log}"; echo "--deps-select=x"; fi',
             "uv": f'case "$*" in *"pytest tests/cplat"*) echo "suite $*" >> "{log}" ;; esac', "uvx": "exit 0",
             "npm": f'echo "npm $*" >> "{log}"', "copier": f'echo "copier $3" >> "{log}"'}
    for name, body in fakes.items():
        (bin_dir / name).write_text(with_prelude(f"#!/bin/sh\n{body}\n"))
        (bin_dir / name).chmod(0o755)
    return w, clean_env(PATH=f"{bin_dir}:{os.environ['PATH']}"), log


@pytest.mark.parametrize("args, select_call, site, render", [
    ((), "select scripts/testselect.py args", False, False),
    (("--full",), "select scripts/testselect.py args --full", False, False),
    (("--site", "--full"), "select scripts/testselect.py args --full", True, False),
    (("--full", "--render"), "select scripts/testselect.py args --full", False, True),
    (("--render", "--site"), "select scripts/testselect.py args", True, True),
])
def test_ci_local_selects_unless_full_and_keeps_its_other_steps_ac_212_5(tmp_path, args, select_call, site, render):
    w, env, log = ci_local_world(tmp_path)
    r = subprocess.run(["bash", "scripts/ci-local.sh", *args], cwd=w, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = [c.strip() for c in log.read_text().splitlines()]
    assert [c for c in calls if c.startswith("select")] == [select_call]
    assert [c for c in calls if c.startswith("suite")] == [f"suite {SUITE} --deps-select=x"]
    assert any(c.startswith("npm") for c in calls) == site
    assert any(c.startswith("copier") for c in calls) == render
    assert ("cplat tests the change can affect" in r.stdout) == ("--full" not in args)
    assert "OK: local CI checks passed" in r.stdout
    for step in ("manifest JSON and plugin versions", "relative Markdown links", "license and copyright metadata"):
        assert step in r.stdout


def test_ci_local_refuses_an_unknown_flag_ac_212_5(tmp_path):
    w, env, _ = ci_local_world(tmp_path)
    r = subprocess.run(["bash", "scripts/ci-local.sh", "--fast"], cwd=w, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2
    assert "usage: scripts/ci-local.sh [--full] [--site] [--render]" in r.stderr


# ---- AC-212.6: the maps of a clone ----

def test_the_change_set_holds_committed_staged_unstaged_untracked_and_recorded_dirty_files_ac_212_6(repo):
    repo.write("scripts/cplat/mod_fixture.py", "VALUE = 'fixture, uncommitted while recording'\n")
    repo.record()
    repo.git("checkout", "--", "scripts/cplat/mod_fixture.py")   # back to the commit: the map still saw another tree
    repo.write("scripts/cplat/mod_c.py", "VALUE = 1  # committed\n")
    repo.commit("a commit after the map")
    repo.write("plugins/prompt.md", "staged\n")
    repo.git("add", "plugins/prompt.md")
    repo.write("templates/tree/inner/deep.txt", "unstaged\n")
    repo.write("tests/cplat/test_untracked.py", "def test_u():\n    assert True\n")
    mode, tests, msg = repo.plan()
    assert mode == "select", msg
    assert tests == ["tests/cplat/test_cplat_child.py", "tests/cplat/test_reads.py", "tests/cplat/test_session_one.py",
                     "tests/cplat/test_session_two.py", "tests/cplat/test_static.py", "tests/cplat/test_subprocess_arg.py",
                     "tests/cplat/test_untracked.py"]
    assert "5 changed file(s)" in msg


def test_the_map_with_the_fewest_changes_is_used_and_bad_or_foreign_maps_are_ignored_ac_212_6(repo):
    old = repo.record("old.json")
    repo.write("scripts/cplat/mod_c.py", "VALUE = 1  # newer\n")
    new_commit = repo.commit("newer")
    repo.record("new.json")
    (repo.store / "broken.json").write_text("{not json")
    foreign = dict(old, commit="0" * 40)
    (repo.store / "foreign.json").write_text(json.dumps(foreign))
    repo.write("scripts/cplat/mod_lazy.py", "VALUE = 'lazy, now'\n")
    mode, _, msg = repo.plan()
    assert mode == "select"
    assert f"map at {new_commit[:9]}, 1 changed file(s)" in msg


def test_a_map_recorded_in_one_worktree_serves_another_ac_212_6(repo, tmp_path):
    m = repo.record()
    other = tmp_path / "other"
    repo.git("worktree", "add", "-q", str(other), "-b", "other")
    (other / "scripts/cplat/mod_c.py").write_text("VALUE = 1  # in the other worktree\n")
    mode, tests, msg = repo.plan(cwd=other)
    assert (mode, tests) == ("select", ["tests/cplat/test_static.py"])
    assert f"map at {m['commit'][:9]}" in msg


def test_at_most_five_maps_are_kept_and_two_recordings_at_once_leave_readable_maps_ac_212_6(repo):
    for i in range(5):
        repo.record(f"m{i}.json", workers=0)
    results: list[dict] = []
    threads = [threading.Thread(target=lambda n=n: results.append(repo.record(f"same{n}.json"))) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    maps = sorted(repo.store.glob("*.json"))
    assert len(maps) == 5
    assert {"same0.json", "same1.json"} <= {p.name for p in maps}
    for p in maps:
        assert set(json.loads(p.read_text())["tests"]) == set(ALL_TESTS)
    assert not [p for p in repo.store.iterdir() if p.name.endswith((".tmp", ".trace"))]


# ---- AC-212.7: a plain run records nothing ----

def test_a_plain_run_writes_no_map_or_trace_and_adds_no_variable_ac_212_7(repo, tmp_path):
    for workers in (0, 2):
        out = tmp_path / f"env{workers}.json"
        r = repo.pytest("tests/cplat", workers=workers, SCRATCH_ENV_OUT=str(out))
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(out.read_text()) == []
    assert not repo.store.exists()
    assert not [p for p in repo.root.rglob("*") if ".trace" in p.name or p.name.startswith("b-")]


def test_ci_runs_the_whole_suite_without_recording_ac_212_7():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    pytest_lines = [line for line in ci.splitlines() if "pytest tests/cplat" in line]
    assert pytest_lines
    assert all("--deps-record" not in line and "test-fast" not in line for line in pytest_lines)
