"""Spec 208: a run of the cplat tests owns one directory under the developer's pytest temp root.

The directory holds the run's pytest base temp, its uv cache (UV_CACHE_DIR) and the temp root of nested pytest runs
(PYTEST_DEBUG_TEMPROOT), so nothing a run makes reaches the developer's uv cache or lasts after a passing run. A failing run
keeps only its failed tests' directories, and only the last 3 failing runs are kept. Self-contained: it imports nothing from
scripts/cplat. The contract is in docs/specs/208-*/design.md.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import sys
import tempfile
import time
from pathlib import Path

import pytest
from _pytest.tmpdir import get_user

ENV_NAMES = ("UV_CACHE_DIR", "PYTEST_DEBUG_TEMPROOT")
OK_STATUSES = (0, 5)   # OK, no tests collected
KEEP_FAILING_RUNS = 3
SHARED = "shared-renders"   # session-scoped dirs: made inside the first test that needs them, never attributed to a test


def _is_worker(config) -> bool:
    return hasattr(config, "workerinput")


def _force_remove(path: Path) -> None:
    """rmtree that survives read-only entries (uv caches and git objects are read-only)."""
    def fix(func, p, exc_info):
        try:
            for q in (os.path.dirname(p), p):
                os.chmod(q, os.lstat(q).st_mode | stat.S_IRWXU)
            func(p)
        except OSError:
            pass

    if not os.path.lexists(path):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda func, p, exc: fix(func, p, exc))
    else:
        shutil.rmtree(path, onerror=fix)
    if os.path.lexists(path):
        for root, dirs, _files in os.walk(path):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), stat.S_IRWXU)
                except OSError:
                    pass
        shutil.rmtree(path, ignore_errors=True)


def _temp_root() -> Path:
    """The developer's pytest temp root, as pytest computes it (before this plugin overrides PYTEST_DEBUG_TEMPROOT)."""
    base = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()).resolve()
    root = base / f"pytest-of-{get_user() or 'unknown'}"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


class _Manifest:
    """Per test, one start and one end line holding the directories the test made in this process's base temp."""

    def __init__(self, run: Path, worker: str):
        self.run = run
        (run / "manifest").mkdir(exist_ok=True)
        self.out = open(run / "manifest" / f"{worker}.jsonl", "a")

    def write(self, rec: dict) -> None:
        self.out.write(json.dumps(rec) + "\n")
        self.out.flush()


_manifest: _Manifest | None = None


def _retain(root: Path) -> None:
    """Keep the newest KEEP_FAILING_RUNS failing runs under the temp root; never touch a live run."""
    failing: list[tuple[float, Path]] = []
    for run in sorted(root.glob("cplat-run-*")):
        try:
            fd = os.open(run / ".lock", os.O_RDWR)
        except OSError:
            continue
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                continue   # live
            try:
                info = json.loads((run / "run.json").read_text())
                state, started = info.get("state"), float(info.get("started"))
            except (OSError, ValueError, TypeError):
                info, state, started = {}, "failed", run.stat().st_mtime
            if state == "passed":
                _force_remove(run)
                continue
            if state == "running":   # an orphan: killed before its own cleanup
                for name in ("uv-cache", "temproot"):
                    _force_remove(run / name)
                for path in (run / "tmp").glob("**/" + SHARED + "*"):
                    _force_remove(path)
                (run / "run.json").write_text(json.dumps({"pid": info.get("pid"), "started": started, "state": "failed"}))
            failing.append((started, run))
        finally:
            os.close(fd)
    failing.sort(reverse=True)
    for _started, run in failing[KEEP_FAILING_RUNS:]:
        try:
            fd = os.open(run / ".lock", os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            continue   # live or already gone
        _force_remove(run)
        os.close(fd)


class RunTemp:
    def __init__(self, config):
        self.config = config
        self.run: Path | None = None
        self.lock_fd: int | None = None
        self.explicit: Path | None = None   # --basetemp given by the developer
        self.earlier: dict[str, str | None] = {}
        self.earlier_sigterm = None
        self.started = time.time()
        self.exitstatus: int | None = None
        self.failed: list[str] = []
        self.values: dict[str, str] = {}

    # ---- controller setup ----

    def start(self) -> None:
        config = self.config
        given = config.option.basetemp
        if given is not None:
            self.explicit = Path(given).resolve()
            base = self.explicit
            values = {"UV_CACHE_DIR": str(base / "uv-cache"), "PYTEST_DEBUG_TEMPROOT": str(base / "temproot")}
        else:
            self.run = self._create_run(_temp_root())
            config.option.basetemp = self.run / "tmp"
            values = {"UV_CACHE_DIR": str(self.run / "uv-cache"), "PYTEST_DEBUG_TEMPROOT": str(self.run / "temproot")}
        self.earlier = {name: os.environ.get(name) for name in ENV_NAMES}
        os.environ.update(values)
        self.values = values
        if signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
            self.earlier_sigterm = signal.SIG_DFL
            signal.signal(signal.SIGTERM, self._on_sigterm)

    @staticmethod
    def _on_sigterm(signum, frame):
        raise KeyboardInterrupt

    def _create_run(self, root: Path) -> Path:
        tag = f"{os.getpid()}-{secrets.token_hex(3)}"
        staging = root / f".cplat-starting-{tag}"
        staging.mkdir()
        (staging / ".lock").write_text("")
        (staging / "uv-cache").mkdir()
        (staging / "temproot").mkdir()   # pytest creates `pytest-of-<user>` below it without parents
        self.lock_fd = os.open(staging / ".lock", os.O_RDWR)
        fcntl.flock(self.lock_fd, fcntl.LOCK_EX)
        self._write_state(staging, "running")
        run = root / f"cplat-run-{tag}"
        staging.rename(run)
        return run

    def _write_state(self, run: Path, state: str) -> None:
        (run / "run.json").write_text(json.dumps({"pid": os.getpid(), "started": self.started, "state": state}))

    # ---- controller end ----

    def passed(self) -> bool:
        return not self.failed and self.exitstatus in (None, *OK_STATUSES)

    def finish(self) -> None:
        for name, value in self.earlier.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if self.earlier_sigterm is not None:
            signal.signal(signal.SIGTERM, self.earlier_sigterm)
        if self.explicit is not None:
            for name in ("uv-cache", "temproot"):
                _force_remove(self.explicit / name)
        elif self.run is not None:
            if self.passed():
                self._write_state(self.run, "passed")
                self._release()
                _force_remove(self.run)
            else:
                self._keep_failed()
                self._write_state(self.run, "failed")
                self._release()
            _retain(self.run.parent)

    def _keep_failed(self) -> None:
        """Move the failed tests' directories to failed/<slug>/ and drop everything else of the run."""
        run = self.run
        ended: dict[str, list[str]] = {}
        started: list[str] = []
        for path in sorted((run / "manifest").glob("*.jsonl")):
            for line in path.read_text().splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue   # a line cut short by a kill
                if "start" in rec:
                    started.append(rec["start"])
                elif "end" in rec:
                    ended[rec["end"]] = rec.get("dirs", [])
        failed = list(self.failed) + [n for n in started if n not in ended and n not in self.failed]
        keep = run / "failed"
        keep.mkdir(exist_ok=True)
        for nodeid in failed:
            slug = re.sub(r"[^A-Za-z0-9._-]", "_", nodeid)[:100] + "-" + hashlib.sha1(nodeid.encode()).hexdigest()[:8]
            dest = keep / slug
            dest.mkdir(exist_ok=True)
            (dest / "NODEID").write_text(nodeid + "\n")
            for rel in ended.get(nodeid, []):
                src = run / rel
                if not src.name.startswith(SHARED) and src.exists():
                    shutil.move(str(src), str(dest / src.name))
        for name in ("tmp", "uv-cache", "temproot", "manifest"):
            _force_remove(run / name)
        print(f"runtemp: kept the files of {len(failed)} failed test(s) in {keep}", file=sys.stderr)

    def _release(self) -> None:
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None


@pytest.hookimpl(tryfirst=True)   # before pytest's tmpdir plugin reads --basetemp
def pytest_configure(config):
    global _manifest
    if _is_worker(config):
        for name, value in config.workerinput.get("runtemp", {}).items():
            os.environ[name] = value
        if config.workerinput.get("runtemp_run"):
            _manifest = _Manifest(Path(config.workerinput["runtemp_run"]), config.workerinput["workerid"])
        return
    state = RunTemp(config)
    state.start()
    if state.run is not None:
        _manifest = _Manifest(state.run, "main")
    config.pluginmanager.register(_Controller(state), "runtemp-controller")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if _manifest is None:
        return (yield)
    base = item.config._tmp_path_factory.getbasetemp()
    before = set(os.listdir(base))
    _manifest.write({"start": item.nodeid})
    result = yield   # an interrupt raises here: no end line, so the test counts as failed
    dirs = sorted(os.path.relpath(base / n, _manifest.run) for n in set(os.listdir(base)) - before
                  if not (base / n).is_symlink())   # pytest's `<name>current` links
    _manifest.write({"end": item.nodeid, "dirs": dirs})
    return result


class _Controller:
    """The controller-side hooks, registered only when the plugin runs as the serial process or the xdist controller."""

    def __init__(self, state: RunTemp):
        self.state = state

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node):
        node.workerinput["runtemp"] = dict(self.state.values)
        node.workerinput["runtemp_run"] = str(self.state.run) if self.state.run else ""

    @pytest.hookimpl(wrapper=True)
    def pytest_sessionfinish(self, session, exitstatus):
        try:
            return (yield)
        finally:
            self.state.exitstatus = int(session.exitstatus)

    def pytest_sessionstart(self, session):
        if self.state.explicit is not None:   # pytest empties the given basetemp when it creates it, so make it first
            session.config._tmp_path_factory.getbasetemp()
            (self.state.explicit / "temproot").mkdir(exist_ok=True)

    def pytest_runtest_logreport(self, report):
        if report.failed and report.nodeid not in self.state.failed:
            self.state.failed.append(report.nodeid)

    def pytest_unconfigure(self, config):
        self.state.finish()
