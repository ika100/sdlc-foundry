"""Spec 208: a test run leaves the developer's disk as it found it (AC-208.1, .3 to .7).

The `runtemp` plugin is loaded by a nested pytest (`-p runtemp`, PYTHONPATH=tests/cplat) on a scratch suite. PYTEST_DEBUG_TEMPROOT and
UV_CACHE_DIR point at a sandbox; the sandbox UV_CACHE_DIR plays the developer's cache. The plugin is not imported here, so each test
fails on its own while it is missing.
"""
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from runtemp_support import Sandbox, hold_lock, make_run, now, snapshot, state_of
from system_fixtures import ROOT

RECORD = '''
import json, os, subprocess, sys
import pytest


def record(tmp_path):
    cache = os.environ["UV_CACHE_DIR"]
    env_dir = os.path.join(cache, "environments-v2", "script-" + tmp_path.name)   # what uv writes for an inline script
    os.makedirs(env_dir)
    open(os.path.join(env_dir, "pyvenv.cfg"), "w").write("x")
    child = subprocess.run([sys.executable, "-c", "import os; print(os.environ['UV_CACHE_DIR'])"], capture_output=True, text=True)
    with open(os.environ["SCRATCH_OUT"], "a") as f:
        f.write(json.dumps({"cache": cache, "child": child.stdout.strip(), "temproot": os.environ.get("PYTEST_DEBUG_TEMPROOT"),
                            "env_dir": env_dir, "tmp": str(tmp_path)}) + "\\n")
    if os.environ.get("SCRATCH_FAIL"):
        assert False, "scratch failure"


@pytest.mark.parametrize("n", range(4))
def test_scratch(n, tmp_path):
    record(tmp_path)
'''

NESTED = '''
import os, subprocess, sys
from pathlib import Path


def test_a(tmp_path):
    (tmp_path / "f.txt").write_text("x")


def test_session_fixture_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("shared-renders")
    (d / "big").write_text("x" * 1000)


def test_nested_pytest_run(tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "pytest.ini").write_text("[pytest]\\n")
    (inner / "test_inner.py").write_text("def test_i(tmp_path):\\n    (tmp_path / 'x').write_text('x')\\n")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "."], cwd=inner, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout
'''

MIXED = '''
import os, signal
import pytest


@pytest.fixture(scope="session")
def shared(tmp_path_factory):
    d = tmp_path_factory.mktemp("shared-renders")
    (d / "render.txt").write_text("x" * 100)
    return d


@pytest.fixture
def bad_setup(tmp_path):
    (tmp_path / "marker.txt").write_text("setup")
    raise RuntimeError("setup broke")


@pytest.fixture
def bad_teardown(tmp_path):
    (tmp_path / "marker.txt").write_text("teardown")
    yield
    raise RuntimeError("teardown broke")


def test_passes_first(tmp_path, shared):
    (tmp_path / "marker.txt").write_text("PASSED-DIR")


def test_fails_in_call(tmp_path):
    (tmp_path / "marker.txt").write_text("call")
    assert False


def test_fails_in_setup(bad_setup):
    pass


def test_fails_in_teardown(bad_teardown):
    pass


def test_times_out(tmp_path):
    (tmp_path / "marker.txt").write_text("timeout")
    while True:
        pass


def test_passes_last(tmp_path):
    (tmp_path / "marker.txt").write_text("PASSED-DIR")
'''

INTERRUPTED = '''
import os, signal


def test_ok(tmp_path):
    (tmp_path / "marker.txt").write_text("PASSED-DIR")


def test_gets_sigterm(tmp_path):
    (tmp_path / "marker.txt").write_text("interrupted")
    os.kill(os.getpid(), signal.SIGTERM)


def test_never_runs(tmp_path):
    pass
'''

FAILS = "def test_boom(tmp_path):\n    (tmp_path / 'm').write_text('x')\n    assert False\n"
PASSES = "def test_fine(tmp_path):\n    (tmp_path / 'm').write_text('x')\n"

FAILED_IDS = {"test_scratch.py::test_fails_in_call", "test_scratch.py::test_fails_in_setup",
              "test_scratch.py::test_fails_in_teardown", "test_scratch.py::test_times_out"}


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


def files_named(root, pattern):
    return [p for p in root.rglob("*") if re.fullmatch(pattern, p.name)]


def run_dir_of(sb, cache):
    """The run directory a cache path lies in (the plugin resolves symlinks in the temp root, so compare resolved paths)."""
    run = Path(cache).resolve().parent
    assert run.parent == sb.R.resolve(), (cache, sb.R)
    return run


def slug(nodeid):
    return re.sub(r"[^A-Za-z0-9._-]", "_", nodeid)[:100] + "-" + hashlib.sha1(nodeid.encode()).hexdigest()[:8]


# ---------------- AC-208.1: the developer's uv cache stays as it was ----------------

@pytest.mark.parametrize("workers", [[], ["-n", "2"]], ids=["serial", "xdist"])
@pytest.mark.parametrize("fail", [False, True], ids=["passing", "failing"])
def test_inline_script_envs_lie_in_the_runs_own_cache_ac_208_1(sb, workers, fail):  # AC-208.1
    before = snapshot(sb.dev_cache)
    p = sb.run(RECORD, *workers, **({"SCRATCH_FAIL": "1"} if fail else {}))
    assert p.returncode == (1 if fail else 0), p.stdout + p.stderr
    assert snapshot(sb.dev_cache) == before
    got = sb.records()
    assert len(got) == 4
    caches = {r["cache"] for r in got}
    assert len(caches) == 1, "every worker uses the one cache of the run"
    cache = caches.pop()
    assert not Path(cache).resolve().is_relative_to(sb.dev_cache.resolve())
    assert {r["child"] for r in got} == {cache}, "a subprocess of a test inherits the run's cache"
    run_dir = run_dir_of(sb, cache)
    assert run_dir.name.startswith("cplat-run-") and Path(cache).name == "uv-cache"
    assert {r["temproot"] for r in got} == {str(run_dir / "temproot")}, "nested pytest runs stay inside the run"


def test_the_developers_cache_location_of_any_kind_is_protected_ac_208_1(sb):  # AC-208.1
    # A6: a developer's own UV_CACHE_DIR (here the sandbox one, outside every default location) is untouched, too
    before = snapshot(sb.dev_cache)
    p = sb.run(RECORD)
    assert p.returncode == 0, p.stdout + p.stderr
    assert snapshot(sb.dev_cache) == before
    assert all(not Path(r["cache"]).resolve().is_relative_to(sb.dev_cache.resolve()) for r in sb.records())


# ---------------- AC-208.3: a passing run leaves nothing ----------------

def test_a_passing_run_leaves_nothing_under_the_temp_root_ac_208_3(sb):  # AC-208.3
    p = sb.run(NESTED)
    assert p.returncode == 0, p.stdout + p.stderr
    assert not sb.R.exists() or snapshot(sb.R) == {}, sorted(snapshot(sb.R))


def test_a_passing_run_leaves_earlier_runs_untouched_ac_208_3(sb):  # AC-208.3
    (sb.R / "pytest-7").mkdir(parents=True)
    (sb.R / "pytest-7" / "kept.txt").write_text("x")
    make_run(sb.R, "cplat-run-11-aaaaaa", "failed", now() - 300)
    make_run(sb.R, "cplat-run-12-bbbbbb", "failed", now() - 200)
    before = snapshot(sb.R)
    p = sb.run(PASSES)
    assert p.returncode == 0, p.stdout + p.stderr
    assert snapshot(sb.R) == before


def test_a_run_without_tests_passes_and_leaves_nothing_ac_208_3(sb):  # AC-208.3
    p = sb.run("def helper():\n    pass\n")
    assert p.returncode == 5, p.stdout + p.stderr
    assert not sb.R.exists() or snapshot(sb.R) == {}


# ---------------- AC-208.4: a failing run keeps exactly the failed tests' directories ----------------

@pytest.fixture(scope="module", params=[[], ["-n", "2"]], ids=["serial", "xdist"])
def failed_run(request, tmp_path_factory):
    sb = Sandbox(tmp_path_factory.mktemp("failed-run"))
    before = snapshot(sb.dev_cache)
    p = sb.run(MIXED, "--timeout=5", "--timeout-method=signal", *request.param, timeout=110)
    return sb, p, before


def kept(sb):
    dirs = sb.run_dirs()
    assert len(dirs) == 1, sorted(snapshot(sb.R))
    return dirs[0]


def test_a_failing_run_leaves_only_failed_and_its_bookkeeping_ac_208_4(failed_run):  # AC-208.4
    sb, p, before = failed_run
    assert p.returncode == 1, p.stdout + p.stderr
    run = kept(sb)
    assert {c.name for c in run.iterdir()} == {".lock", "run.json", "failed"}
    assert state_of(run) == "failed"
    assert not files_named(sb.R, r"uv-cache|temproot|manifest|tmp|shared-renders\d*")
    assert snapshot(sb.dev_cache) == before


def test_the_failed_tests_of_every_phase_keep_their_directories_ac_208_4(failed_run):  # AC-208.4
    sb, p, _ = failed_run
    run = kept(sb)
    ids = {}
    for d in (run / "failed").iterdir():
        ids[(d / "NODEID").read_text().strip()] = d
    assert set(ids) == FAILED_IDS, "setup, call, teardown and timeout failures; no passed test"
    for nodeid, d in ids.items():
        assert d.name == slug(nodeid), "named so that the test id can be recognised"
        assert nodeid.split("::")[1] in d.name
    markers = {nodeid.split("::")[1]: sorted(f.read_text() for f in ids[nodeid].rglob("marker.txt")) for nodeid in ids}
    assert markers == {"test_fails_in_call": ["call"], "test_fails_in_setup": ["setup"],
                       "test_fails_in_teardown": ["teardown"], "test_times_out": ["timeout"]}


def test_the_directories_of_passed_tests_are_gone_ac_208_4(failed_run):  # AC-208.4
    sb, _, _ = failed_run
    kept(sb)
    assert not [f for f in sb.R.rglob("marker.txt") if f.read_text() == "PASSED-DIR"]


def test_a_failing_run_says_where_it_kept_the_files_ac_208_4(failed_run):  # AC-208.4
    sb, p, _ = failed_run
    assert f"runtemp: kept the files of 4 failed test(s) in {kept(sb).resolve() / 'failed'}" in p.stderr


def test_an_interrupted_run_counts_as_failing_and_leaves_the_developers_cache_ac_208_4(sb):  # AC-208.4 (A5)
    before = snapshot(sb.dev_cache)
    p = sb.run(INTERRUPTED)
    assert p.returncode == 2, p.stdout + p.stderr
    run = sb.run_dirs()
    assert len(run) == 1 and {c.name for c in run[0].iterdir()} == {".lock", "run.json", "failed"}
    ids = {(d / "NODEID").read_text().strip() for d in (run[0] / "failed").iterdir()}
    assert ids == {"test_scratch.py::test_gets_sigterm"}
    assert not [f for f in sb.R.rglob("marker.txt") if f.read_text() == "PASSED-DIR"]
    assert snapshot(sb.dev_cache) == before


def test_a_collection_error_leaves_an_empty_failed_directory_ac_208_4(sb):  # AC-208.4
    p = sb.run("import not_there_208\n\ndef test_x():\n    pass\n")
    assert p.returncode in (2, 1), p.stdout + p.stderr
    run = sb.run_dirs()
    assert len(run) == 1 and {c.name for c in run[0].iterdir()} == {".lock", "run.json", "failed"}
    assert list((run[0] / "failed").iterdir()) == []


# ---------------- AC-208.5: at most 3 failing runs leave something ----------------

def test_the_oldest_of_four_failing_runs_is_removed_ac_208_5(sb):  # AC-208.5
    old = [make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 4000 + i * 1000) for i in range(3)]
    kept_before = {d.name: snapshot(d) for d in old[1:]}
    p = sb.run(FAILS)
    assert p.returncode == 1, p.stdout + p.stderr
    names = {d.name for d in sb.run_dirs()}
    assert old[0].name not in names
    assert {d.name for d in old[1:]} <= names and len(names) == 3
    assert {d.name: snapshot(d) for d in old[1:]} == kept_before
    new = next(d for d in sb.run_dirs() if d.name not in {o.name for o in old})
    assert state_of(new) == "failed" and (new / "failed").is_dir()


def test_there_are_never_leftovers_of_more_than_three_runs_ac_208_5(sb):  # AC-208.5
    made, known = [], set()
    for _ in range(4):
        assert sb.run(FAILS).returncode == 1
        now_dirs = {d.name for d in sb.run_dirs()}
        assert len(now_dirs) <= 3
        made.append((now_dirs - known).pop())
        known = now_dirs
    assert known == set(made[1:]), "the first of four failing runs went, the three most recent remain"


def test_passing_runs_do_not_push_failing_leftovers_out_ac_208_5(sb):  # AC-208.5 (A4)
    old = [make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 4000 + i * 1000) for i in range(3)]
    before = snapshot(sb.R)
    for _ in range(2):
        assert sb.run(PASSES).returncode == 0
    assert snapshot(sb.R) == before and len(old) == 3


def test_an_orphan_is_settled_and_counts_as_a_failing_run_ac_208_5(sb):  # AC-208.5 (A5)
    oldest = make_run(sb.R, "cplat-run-1-aaaaa1", "failed", now() - 5000)
    others = [make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 4000 + i * 1000) for i in (2, 3)]
    orphan = make_run(sb.R, "cplat-run-4-aaaaa4", "running", now() - 500, uv_cache=True)   # killed before its cleanup; lock is free
    assert sb.run(PASSES).returncode == 0
    assert not oldest.exists(), "4 failing runs counting the orphan: the oldest goes"
    assert all(d.exists() for d in others) and orphan.exists()
    assert state_of(orphan) == "failed"
    assert not (orphan / "uv-cache").exists() and not (orphan / "temproot").exists()
    assert not (orphan / "tmp" / "shared-renders0").exists()


# ---------------- AC-208.6: overlapping runs stay out of each other's way ----------------

LIVE_OTHER = '''
import os, sys


def test_slow(tmp_path):
    (tmp_path / "mine.txt").write_text("x")
    cache = os.environ["UV_CACHE_DIR"]
    os.makedirs(cache + "/environments-v2/mine")
    print("STARTED " + os.environ["UV_CACHE_DIR"], flush=True)
    sys.stdin.readline()   # the test below ends other runs meanwhile
    assert (tmp_path / "mine.txt").read_text() == "x"
    assert os.path.isdir(cache + "/environments-v2/mine")
    assert os.path.isdir(os.environ["PYTEST_DEBUG_TEMPROOT"])
'''


def test_a_run_that_ends_leaves_an_overlapping_run_alone_ac_208_6(sb):  # AC-208.6
    slow = sb.popen(sb.suite(LIVE_OTHER), "-s", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    live = None
    try:
        for _ in range(20):
            line = slow.stdout.readline()
            if "STARTED " in line:
                live = run_dir_of(sb, line.split("STARTED ", 1)[1].strip())
                break
            if not line:
                break
        assert live is not None, "the overlapping run started"
        before = snapshot(live)
        assert sb.run(PASSES).returncode == 0
        assert sb.run(FAILS).returncode == 1
        assert sb.run(FAILS).returncode == 1
        assert snapshot(live) == before, "nothing of the live run is added, changed or removed by the others' cleanup"
        slow.stdin.write("go\n")
        slow.stdin.flush()
        out, _ = slow.communicate(timeout=60)
        assert slow.returncode == 0, out
    finally:
        if slow.poll() is None:
            slow.kill()
            slow.wait()
    assert not live.exists(), "the run removes itself when it passes"
    assert len(sb.run_dirs()) == 2, "the two failing runs' leftovers"


def test_a_live_run_is_never_touched_by_cleanup_or_retention_ac_208_6(sb):  # AC-208.6
    live = make_run(sb.R, "cplat-run-1-aaaaa1", "running", now() - 9000, uv_cache=True)
    newer = [make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 3000 + i * 100) for i in (2, 3, 4)]
    before = snapshot(live)
    with hold_lock(live):
        assert sb.run(FAILS).returncode == 1
        assert sb.run(PASSES).returncode == 0
        assert snapshot(live) == before, "uv cache, renders and run.json of a run that holds its lock stay"
    assert state_of(live) == "running"
    assert len([d for d in sb.run_dirs() if state_of(d) == "failed"]) <= 3 and len(newer) == 3


def test_a_live_failed_looking_run_does_not_count_toward_removal_ac_208_6(sb):  # AC-208.6
    live_old = make_run(sb.R, "cplat-run-1-aaaaa1", "failed", now() - 9000)
    for i in (2, 3, 4):
        make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 3000 + i * 100)
    with hold_lock(live_old):
        assert sb.run(PASSES).returncode == 0
    assert live_old.exists() and (live_old / "failed" / "slug0" / "NODEID").exists()


def test_concurrent_runs_get_their_own_directory_and_cache_ac_208_6(sb):  # AC-208.6
    procs = [sb.popen(sb.suite(RECORD), stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for _ in range(2)]
    outs = [p.communicate(timeout=100)[0] for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    caches = {r["cache"] for r in sb.records()}
    assert len(caches) == 2 and not sb.run_dirs()


# ---------------- AC-208.7: no measurable per-test work ----------------

PER_TEST = '''
import json, os
from pathlib import Path


def test_a_1(tmp_path):
    (tmp_path / "f").write_text("x")


def test_a_2(tmp_path):
    (tmp_path / "f").write_text("x")


def test_a_3(tmp_path):
    (tmp_path / "f").write_text("x")


def test_a_4(tmp_path):
    (tmp_path / "f").write_text("x")


def test_z_reads_the_manifest(tmp_path):
    run = Path(os.environ["UV_CACHE_DIR"]).parent
    lines = [json.loads(ln) for ln in (run / "manifest" / "main.jsonl").read_text().splitlines()]
    out = {"entries": sorted(p.name for p in run.iterdir()), "lines": lines}
    Path(os.environ["SCRATCH_OUT"]).write_text(json.dumps(out))
'''


def test_the_plugin_adds_no_per_test_work_beyond_listing_a_directory_ac_208_7(sb):  # AC-208.7
    """The wall-time comparison (before and after, on the same machine) is recorded in the pull request and cannot be a test.
    What a test can hold, without timing: per test the plugin appends one start and one end line holding the directories the test
    made, and creates no other file or directory in the run."""
    p = sb.run(PER_TEST)
    assert p.returncode == 0, p.stdout + p.stderr
    got = json.loads(sb.out.read_text())
    assert got["entries"] == sorted([".lock", "run.json", "tmp", "uv-cache", "temproot", "manifest"])
    lines = got["lines"]
    assert len(lines) == 4 * 2 + 1, "a start and an end line per finished test, the start of the running one"
    for i in range(4):
        start, end = lines[2 * i], lines[2 * i + 1]
        assert start == {"start": f"test_scratch.py::test_a_{i + 1}"}
        assert set(end) == {"end", "dirs"} and end["end"] == start["start"]
        assert len(end["dirs"]) == 1 and end["dirs"][0].startswith("tmp/") and f"test_a_{i + 1}" in end["dirs"][0]
    assert lines[-1] == {"start": "test_scratch.py::test_z_reads_the_manifest"}


def test_the_conftest_loads_the_plugin_so_every_entry_point_is_protected_ac_208_1():  # AC-208.1
    tree = ast.parse((ROOT / "tests" / "cplat" / "conftest.py").read_text())
    plugins = [n.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "pytest_plugins" for t in n.targets)]
    assert plugins, "conftest.py declares pytest_plugins"
    assert "runtemp" in {e.value for v in plugins for e in v.elts if isinstance(e, ast.Constant)}
    assert (ROOT / "tests" / "cplat" / "runtemp.py").is_file()
