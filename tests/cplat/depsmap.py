"""Spec 212: a full run with `--deps-record PATH` records which repo files each test file depends on (the dependency map).

Without the option the plugin does nothing (AC-212.7). With it, every process of the run records into buckets (`depstrace`):
one per test file, one per fixture of a wider scope than a function, one per shared render. At the end the controller merges
the buckets, the records of the cplat processes the tests started and the module-level imports of each test file into the
map at PATH. `scripts/testselect.py` reads it. The contract is in docs/specs/212-*/design.md.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFTEST = Path(__file__).resolve().with_name("conftest.py")
VERSION = 1
KEEP_MAPS = 5
RECORDED_STATUSES = (0, 1)   # all passed, some failed; an interrupted run records nothing


def pytest_addoption(parser):
    parser.addoption("--deps-record", default=None, metavar="PATH",
                     help="spec 212: record the dependency map of this full run at PATH (devbox run test-fast --full)")
    parser.addoption("--deps-select", default=None, metavar="FILES",
                     help="spec 212: collect only these test files (comma-separated, repo-relative; empty: none)")


def _selection(config) -> set[str] | None:
    value = config.getoption("--deps-select")
    return None if value is None else {f for f in value.split(",") if f}


def pytest_ignore_collect(collection_path, config):
    """Under --deps-select, a test file outside the selection is not collected (other files are left to pytest)."""
    selected = _selection(config)
    if selected is None or not (collection_path.name.startswith("test_") and collection_path.suffix == ".py"):
        return None
    return True if _rel(collection_path) not in selected else None


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """An empty selection is a run with nothing to check, not a failure (the selector said why)."""
    if _selection(session.config) == set() and int(exitstatus) == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK


def _rel(path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def dirty_files() -> set[str]:
    """Files that differ from HEAD in the working tree or index, untracked ones included (both sides of a rename)."""
    out = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    return {entry[3:] for entry in out.split("\0") if len(entry) > 3}


def pytest_configure(config):
    path = config.getoption("--deps-record")
    if not path:
        return
    import depstrace
    trace = Path(path + ".trace")
    worker = hasattr(config, "workerinput")
    state: dict = {}
    if not worker:
        shutil.rmtree(trace, ignore_errors=True)
        trace.mkdir(parents=True)
        state = {"commit": _git("rev-parse", "HEAD").strip(), "dirty": dirty_files()}
    rec = depstrace.start(ROOT, trace, quiet=depstrace.autouse_fixtures(CONFTEST))
    config.pluginmanager.register(Recording(Path(path), trace, rec, worker, state, config.rootpath), "depsmap-recording")


class Recording:
    def __init__(self, path: Path, trace: Path, rec, worker: bool, state: dict, rootpath: Path):
        self.path, self.trace, self.rec, self.worker, self.state = path, trace, rec, worker, state
        self.rootpath = rootpath   # a report's fspath is relative to pytest's rootdir (tests/cplat, where pytest.ini is)
        self.failed: set[str] = set()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        import depstrace
        name = _rel(item.path)
        with depstrace.bucket(name):
            yield
        uses = self.rec.ensure(name)["uses"]
        uses.update("fixture:" + f for f in item.fixturenames)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        if fixturedef.scope == "function":
            yield
            return
        import depstrace
        with depstrace.bucket("fixture:" + fixturedef.argname):   # set up once, used by every test that names it
            yield

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.failed.add(_rel(self.rootpath / report.fspath))

    def pytest_collectreport(self, report):
        if report.failed and report.fspath:
            self.failed.add(_rel(self.rootpath / report.fspath))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        config = session.config
        own = self.trace / f"inproc-{config.workerinput['workerid'] if self.worker else 'main'}.json"
        own.write_text(json.dumps({"buckets": self.rec.dump(), "failed": sorted(self.failed)}))
        if self.worker:
            return
        if int(exitstatus) in RECORDED_STATUSES:
            self.state["dirty"] |= dirty_files()
            write_map(self.path, build_map(self.trace, self.state))
            prune(self.path.parent)
        shutil.rmtree(self.trace, ignore_errors=True)


def _merge(into: dict, bucket: dict) -> None:
    for kind, values in bucket.items():
        into.setdefault(kind, set()).update(values)


def build_map(trace: Path, state: dict) -> dict:
    import depstrace
    buckets: dict[str, dict[str, set[str]]] = {}
    failed: set[str] = set()
    for f in sorted(trace.glob("inproc-*.json")):
        data = json.loads(f.read_text())
        failed.update(data["failed"])
        for name, b in data["buckets"].items():
            _merge(buckets.setdefault(name, {}), b)
    for d in sorted(trace.glob("b-*")):   # the records of cplat processes, one file per process
        name = (d / "name").read_text()
        for f in d.glob("*.json"):
            try:
                _merge(buckets.setdefault(name, {}), json.loads(f.read_text()))
            except ValueError:
                continue   # a process killed while writing; its tmp file never became a .json
    imports = depstrace.Imports(ROOT)
    tests: dict[str, dict[str, list[str]]] = {}
    for name in sorted(n for n in buckets if n.startswith("tests/")):
        merged: dict[str, set[str]] = {k: set() for k in depstrace.KINDS}
        seen, todo = set(), [name]
        while todo:                       # the test file's own bucket and every fixture or render it used, transitively
            b = buckets.get(todo.pop(), {})
            for kind in depstrace.KINDS:
                merged[kind] |= set(b.get(kind, ()))
            for used in b.get("uses", ()):
                if used not in seen:
                    seen.add(used)
                    todo.append(used)
        merged["files"] |= imports.closure([name, *merged["files"]])
        merged["files"].discard(name)
        tests[name] = {k: sorted(v) for k, v in merged.items()}
    return {"version": VERSION, "commit": state["commit"], "dirty": sorted(state["dirty"]),
            "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"), "failed": sorted(failed), "tests": tests}


def write_map(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, path)


def prune(store: Path, keep: int = KEEP_MAPS) -> None:
    maps = sorted(store.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in maps[keep:]:
        old.unlink(missing_ok=True)
