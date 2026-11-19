"""Spec 208: a test run leaves the developer's disk as it found it (AC-208.1, .3 to .7).

The `runtemp` plugin is loaded by a nested pytest (`-p runtemp`, PYTHONPATH=tests/cplat) on a scratch suite. PYTEST_DEBUG_TEMPROOT and
UV_CACHE_DIR point at a sandbox; the sandbox UV_CACHE_DIR plays the developer's cache. The plugin is not imported here, so each test
fails on its own while it is missing.
"""
import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from runtemp_support import Sandbox, hold_lock, make_removing, make_run, now, snapshot, state_of
from system_fixtures import ROOT
from waiting import wait_for

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


def seed_w(sb, ident, *, size=100):
    """An entry in the test wheel cache W, as uv lays it out: an archive and the pointer that names it."""
    a = sb.W / "archive-v0" / ident
    a.mkdir(parents=True)
    (a / "lib.py").write_text("x" * size)
    ptr = sb.W / "wheels-v5" / "pypi" / f"pkg-{ident}"
    ptr.mkdir(parents=True, exist_ok=True)
    (ptr / "1.0-py3.msgpack").write_text(ident)


def w_files(sb):
    return sorted(p.relative_to(sb.W).as_posix() for p in sb.W.rglob("*") if p.is_file()) if sb.W.exists() else []


def seeded(sb):
    """What the scratch test found in its own UV_CACHE_DIR before writing anything (the first record of SEEDWRITE)."""
    return sb.records()[0]["seeded"]


def entry_files(ident):
    return [f"archive-v0/{ident}/lib.py", f"wheels-v5/pypi/pkg-{ident}/1.0-py3.msgpack"]


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
    made, known = [], set()   # each sb.run waits for its removal, so the run's leftovers are final when it returns
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
    sb.wait_removed()
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
    sb.wait_removed()
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
    seed_w(sb, "pre")   # seeding adds nothing at the run directory's top level
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


# ---------------- A10: the persistent test wheel cache W (AC-208.1, .6, .7) ----------------

SEEDWRITE = '''
import json, os, time


def listing(cache):
    out = []
    for b in sorted(os.listdir(cache)) if os.path.isdir(cache) else []:
        for root, _, files in os.walk(os.path.join(cache, b)):
            out += [os.path.relpath(os.path.join(root, f), cache) for f in files]
    return sorted(out)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def test_seed_and_write(tmp_path):
    cache = os.environ["UV_CACHE_DIR"]
    with open(os.environ["SCRATCH_OUT"], "a") as f:
        f.write(json.dumps({"seeded": listing(cache), "buckets": sorted(os.listdir(cache)) if os.path.isdir(cache) else []}) + "\\n")
    ids = [i for i in os.environ.get("SCRATCH_IDS", "").split(",") if i]
    for ident in ids:   # what uv writes for an inline script: an archive, its pointer, and a lot besides
        write(f"{cache}/archive-v0/{ident}/lib.py", "x" * 100)
        write(f"{cache}/wheels-v5/pypi/pkg-{ident}/1.0-py3.msgpack", ident)
        write(f"{cache}/environments-v2/env-{ident}/pyvenv.cfg", "home = /x")
        write(f"{cache}/simple-v18/pypi/pkg-{ident}.rkyv", "index")
        write(f"{cache}/interpreter-v4/{ident}.msgpack", "py")
        write(f"{cache}/builds-v0/{ident}/b", "b")
    barrier = os.environ.get("SCRATCH_BARRIER")
    if barrier and ids:
        write(os.path.join(barrier, ids[0] + ".written"), "")
        deadline = time.time() + 60
        while not os.path.exists(os.path.join(barrier, "go")) and time.time() < deadline:
            time.sleep(0.02)   # fake-delay: the scratch run's barrier poll, no waiting helper in a nested suite
'''


def test_a_second_run_finds_the_wheels_of_the_first_in_its_own_cache_ac_208_1(sb):  # AC-208.1 (A10)
    before = snapshot(sb.dev_cache)
    assert sb.run(SEEDWRITE, SCRATCH_IDS="aaa").returncode == 0
    assert seeded(sb) == [], "the first run starts cold"
    sb.out.unlink()
    p = sb.run(SEEDWRITE)
    assert p.returncode == 0, p.stdout + p.stderr
    assert seeded(sb) == sorted(entry_files("aaa")), "archive and wheel pointer of the first run, nothing else"
    assert snapshot(sb.dev_cache) == before, "the developer's uv cache is never read from, written to or linked into"
    assert not sb.run_dirs() and not list(sb.R.glob(".cplat-removing-*"))


def test_the_wheel_cache_holds_wheels_and_archives_only_ac_208_1(sb):  # AC-208.1 (A10)
    assert sb.run(SEEDWRITE, SCRATCH_IDS="aaa,bbb").returncode == 0
    assert w_files(sb) == sorted(entry_files("aaa") + entry_files("bbb")), "the new wheels flowed back, and only they"
    tops = {p.name for p in sb.W.iterdir()}
    assert tops == {"archive-v0", "wheels-v5"}, "no environments-v*, simple-v*, interpreter-v*, builds-v* or temp file"
    assert not [p for p in sb.W.rglob("*") if p.name.startswith(".tmp-")]


def test_a_wheel_cache_over_two_gib_is_emptied_and_nothing_is_seeded_ac_208_1(sb):  # AC-208.1 (A10)
    seed_w(sb, "old")
    big = sb.W / "archive-v0" / "big" / "blob"
    big.parent.mkdir()
    with open(big, "wb") as f:
        f.truncate(2 * 1024**3 + 1)   # sparse: the bound counts st_size, not blocks
    p = sb.run(SEEDWRITE, SCRATCH_IDS="new")
    assert p.returncode == 0, p.stdout + p.stderr
    assert seeded(sb) == [], "over the bound nothing is seeded"
    sb.wait_gone(sb.W.parent, "test-wheels.old-*")
    assert w_files(sb) == sorted(entry_files("new")), "the old cache is gone; the run filled a fresh one"


def test_a_missing_wheel_cache_changes_nothing_but_the_speed_ac_208_6(sb):  # AC-208.6 (A10)
    assert not sb.xdg.exists()
    before = snapshot(sb.dev_cache)
    p = sb.run(SEEDWRITE, SCRATCH_IDS="aaa")
    assert p.returncode == 0, p.stdout + p.stderr
    assert seeded(sb) == []
    assert snapshot(sb.dev_cache) == before
    assert w_files(sb) == sorted(entry_files("aaa")), "the run creates W for the next one"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_wheel_cache_changes_nothing_but_the_speed_ac_208_6(sb):  # AC-208.6 (A10)
    seed_w(sb, "pre")
    dirs = [sb.xdg, sb.xdg / "sdlc-foundry", sb.W, *sb.W.iterdir(), *(d for b in sb.W.iterdir() for d in b.rglob("*") if d.is_dir())]
    try:
        for d in dirs:
            d.chmod(0o555)
        before = snapshot(sb.W)
        p = sb.run(SEEDWRITE, SCRATCH_IDS="aaa")
        assert p.returncode == 0, p.stdout + p.stderr
        assert seeded(sb) == sorted(entry_files("pre")), "readable, so seeded; only the flow-back is skipped"
        assert snapshot(sb.W) == before
    finally:
        for d in dirs:
            d.chmod(0o750)   # owner-writable again so the temp dir can be cleaned up
    assert not sb.run_dirs()


@pytest.mark.skipif(not Path("/dev/shm").is_dir(), reason="needs a second file system under a writable path")
def test_a_wheel_cache_on_another_file_system_changes_nothing_but_the_speed_ac_208_6(sb, tmp_path):  # AC-208.6 (A10)
    import shutil
    if Path("/dev/shm").stat().st_dev == tmp_path.stat().st_dev:
        pytest.skip("/dev/shm is on the same file system as the temp path")
    other = Path("/dev/shm") / f"sdlc-208-{tmp_path.name}"
    sb.xdg = other
    sb.W = other / "sdlc-foundry" / "test-wheels"
    try:
        seed_w(sb, "pre")
        before = snapshot(sb.W)
        p = sb.run(SEEDWRITE, SCRATCH_IDS="aaa")
        assert p.returncode == 0, p.stdout + p.stderr
        assert seeded(sb) == [], "hard links cannot cross file systems: seeding is skipped"
        assert snapshot(sb.W) == before, "so is the flow-back"
    finally:
        shutil.rmtree(other, ignore_errors=True)


def test_overlapping_runs_that_both_write_wheels_both_pass_and_w_has_both_ac_208_6(sb, tmp_path):  # AC-208.6 (A10)
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    runs = [("aaa,common", "aaa"), ("bbb,common", "bbb")]
    procs = [sb.popen(sb.suite(SEEDWRITE), env=sb.env(SCRATCH_IDS=ids, SCRATCH_BARRIER=str(barrier)), stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT) for ids, _ in runs]
    try:
        # both are live and have written before either ends
        wait_for(lambda: all((barrier / f"{first}.written").exists() for _, first in runs), 60, what="both runs to write")
        (barrier / "go").write_text("")
        outs = [p.communicate(timeout=100)[0] for p in procs]
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()
    assert [p.returncode for p in procs] == [0, 0], outs
    sb.wait_removed()
    assert w_files(sb) == sorted(entry_files("aaa") + entry_files("bbb") + entry_files("common"))
    assert not [p for p in sb.W.rglob("*") if p.name.startswith(".tmp-")]


# ---------------- A11: the removal runs in the background (AC-208.3 to .6) ----------------

PROBE_CONFTEST = '''
import atexit, json, os


def _probe():
    R = os.environ["SCRATCH_R"]
    names = sorted(os.listdir(R)) if os.path.isdir(R) else []
    shape = {n: sorted(os.listdir(os.path.join(R, n))) for n in names if n.startswith("cplat-run-")}
    with open(os.environ["SCRATCH_ATEXIT"], "w") as f:
        f.write(json.dumps({"names": names, "shape": shape}))


atexit.register(_probe)   # runs when the interpreter exits, after pytest's unconfigure
'''

MANY_FILES = '''
def test_many(tmp_path):
    for d in range(200):   # 40000 files: deleting them takes far longer than the interpreter needs to exit
        (tmp_path / f"d{d}").mkdir()
        for i in range(200):
            (tmp_path / f"d{d}" / f"f{i}").write_text("x")
{tail}
'''


@pytest.mark.parametrize("fail", [False, True], ids=["passing", "failing"])
def test_the_run_ends_with_renames_and_the_removal_goes_on_behind_it_ac_208_3(sb, tmp_path, fail):  # AC-208.3, AC-208.4 (A11)
    probe = tmp_path / "atexit.json"
    source = MANY_FILES.replace("{tail}", "    assert False\n" if fail else "")
    p = sb.run(source, conftest=PROBE_CONFTEST, wait=False, SCRATCH_R=str(sb.R), SCRATCH_ATEXIT=str(probe))
    assert p.returncode == (1 if fail else 0), p.stdout + p.stderr
    got = json.loads(probe.read_text())
    removing = [n for n in got["names"] if n.startswith(".cplat-removing-")]
    assert len(removing) == 1, f"at exit the bulk of the run is moved aside and still being deleted: {got}"
    if fail:
        assert list(got["shape"].values()) == [[".lock", "failed", "run.json"]], "the run directory has its final shape"
    else:
        assert got["shape"] == {}, "a passing run's directory is already gone from its name"
    sb.wait_removed()
    assert not sb.R.exists() or [p.name for p in sb.R.iterdir() if not p.name.startswith("cplat-run-")] == []


def test_the_nested_run_returns_at_once_and_r_is_clean_after_the_wait_ac_208_3(sb):  # AC-208.3 (A11)
    # capture_output waits for EOF on the pipes: a remover that inherited stdout or stderr would hold the call up
    p = sb.run(NESTED, wait=False, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    sb.wait_removed()
    assert not sb.R.exists() or snapshot(sb.R) == {}, sorted(snapshot(sb.R))


def test_a_removal_touches_nothing_but_its_own_path_ac_208_6(sb):  # AC-208.6, AC-208.4, AC-208.5 (A11)
    live = make_run(sb.R, "cplat-run-1-aaaaa1", "running", now() - 9000, uv_cache=True)
    failing = [make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 4000 + i * 1000) for i in (2, 3)]
    pytest_dir = sb.R / "pytest-7"
    pytest_dir.mkdir()
    (pytest_dir / "kept.txt").write_text("x")
    before = {d.name: snapshot(d) for d in (live, *failing, pytest_dir)}
    with hold_lock(live):
        for source in (FAILS, PASSES):   # the failing one makes the third failing run: none is removed
            p = sb.run(SEEDWRITE + "\n" + source.replace("def test_", "def test_z_"), SCRATCH_IDS="zzz")
            assert p.returncode == (1 if source is FAILS else 0), p.stdout + p.stderr
            assert {d.name: snapshot(d) for d in (live, *failing, pytest_dir)} == before, "byte for byte, removal finished"
            assert not [d for d in sb.R.glob(".cplat-removing-*")]
    assert "archive-v0/zzz/lib.py" in w_files(sb), "the removal's flow-back ran, and only for its own cache"


def test_a_removal_in_progress_is_not_counted_and_not_touched_ac_208_5(sb):  # AC-208.5 (A11)
    old = [make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 4000 + i * 1000) for i in (2, 3)]
    busy = make_removing(sb.R, ".cplat-removing-9-cccccc", "failed", now() - 9000)   # looks like the oldest failing run
    before = snapshot(busy)
    with hold_lock(busy):
        assert sb.run(FAILS, ignore=(busy.name,)).returncode == 1
        assert all(d.exists() for d in old), "two old failing runs and the new one are three: the removal is no fourth run"
        assert len(sb.run_dirs()) == 3
        assert sb.run(PASSES, ignore=(busy.name,)).returncode == 0
        assert snapshot(busy) == before, "a live removal is not touched"


def test_a_removal_whose_remover_was_killed_is_removed_by_the_next_run_ac_208_5(sb):  # AC-208.5 (A11)
    stale = make_removing(sb.R, ".cplat-removing-9-cccccc", "passed", now() - 9000)   # its lock is free
    failing = [make_run(sb.R, f"cplat-run-{i}-aaaaa{i}", "failed", now() - 4000 + i * 1000) for i in (2, 3)]
    kept_before = {d.name: snapshot(d) for d in failing}
    assert sb.run(PASSES).returncode == 0
    assert not stale.exists()
    assert {d.name: snapshot(d) for d in failing} == kept_before
