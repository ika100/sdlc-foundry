"""Spec 208: a sandbox for running the `runtemp` plugin on scratch suites in a nested pytest.

The sandbox holds the pytest temp root (PYTEST_DEBUG_TEMPROOT) and a uv cache that plays the developer's (UV_CACHE_DIR). Nothing
here touches the developer's real uv cache or temp root.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from _pytest.tmpdir import get_user

from system_fixtures import ROOT

PLUGIN_DIR = ROOT / "tests" / "cplat"


class Sandbox:
    def __init__(self, base: Path):
        self.base = base
        self.temproot = base / "temproot"
        self.dev_cache = base / "dev-uv-cache"
        self.out = base / "scratch-out.jsonl"
        self.temproot.mkdir()
        (self.dev_cache / "environments-v2" / "abc123").mkdir(parents=True)
        (self.dev_cache / "environments-v2" / "abc123" / "pyvenv.cfg").write_text("home = /x\n")
        self.R = self.temproot / f"pytest-of-{get_user() or 'unknown'}"
        self._n = 0

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "UV_", "SCRATCH_"))}
        env.update(PYTEST_DEBUG_TEMPROOT=str(self.temproot), UV_CACHE_DIR=str(self.dev_cache), PYTHONPATH=str(PLUGIN_DIR),
                   SCRATCH_OUT=str(self.out), **extra)
        return env

    def suite(self, source: str) -> Path:
        self._n += 1
        d = self.base / f"suite{self._n}"
        d.mkdir()
        (d / "pytest.ini").write_text("[pytest]\n")
        (d / "test_scratch.py").write_text(source)
        return d

    def popen(self, suite: Path, *args: str, env: dict[str, str] | None = None, **kw) -> subprocess.Popen:
        cmd = [sys.executable, "-m", "pytest", "-p", "runtemp", "-p", "no:cacheprovider", "-q", *args]
        return subprocess.Popen(cmd, cwd=suite, env=env or self.env(), text=True, **kw)

    def run(self, source: str, *args: str, timeout: int = 100, **extra_env: str) -> subprocess.CompletedProcess:
        suite = self.suite(source)
        cmd = [sys.executable, "-m", "pytest", "-p", "runtemp", "-p", "no:cacheprovider", "-q", *args]
        return subprocess.run(cmd, cwd=suite, env=self.env(**extra_env), capture_output=True, text=True, timeout=timeout)

    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.out.read_text().splitlines()] if self.out.exists() else []

    def run_dirs(self) -> list[Path]:
        return sorted(p for p in self.R.glob("cplat-run-*")) if self.R.exists() else []


def snapshot(root: Path) -> dict[str, tuple]:
    """Every entry under `root` (itself excluded) with its kind, size and mtime, so any add, change or removal shows."""
    out: dict[str, tuple] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        mtime = 0 if p.name == ".lock" else st.st_mtime_ns   # opening a lock file without truncating is not a change
        out[p.relative_to(root).as_posix()] = (p.is_dir(), 0 if p.is_dir() else st.st_size, mtime)
    return out


def make_run(R: Path, name: str, state: str, started: float, *, failed_ids: tuple[str, ...] = ("test_old.py::test_x",),
             uv_cache: bool = False) -> Path:
    """A leftover run directory of the contract's shape (design.md, Paths), with a free lock."""
    d = R / name
    d.mkdir(parents=True)
    (d / ".lock").write_text("")
    (d / "run.json").write_text(json.dumps({"pid": 999999, "started": started, "state": state}))
    if state == "failed":
        for i, nodeid in enumerate(failed_ids):
            (d / "failed" / f"slug{i}" / "test_x0").mkdir(parents=True)
            (d / "failed" / f"slug{i}" / "NODEID").write_text(nodeid + "\n")
            (d / "failed" / f"slug{i}" / "test_x0" / "log.txt").write_text("kept\n")
    if uv_cache:
        (d / "uv-cache" / "environments-v2" / "e").mkdir(parents=True)
        (d / "uv-cache" / "environments-v2" / "e" / "pyvenv.cfg").write_text("x")
        (d / "tmp" / "shared-renders0").mkdir(parents=True)
        (d / "tmp" / "shared-renders0" / "big").write_text("x" * 100)
        (d / "temproot").mkdir()
    return d


def state_of(run_dir: Path) -> str:
    return json.loads((run_dir / "run.json").read_text())["state"]


@contextmanager
def hold_lock(run_dir: Path):
    """Play a live run: hold the flock on its `.lock` in a Python file descriptor, closed in `finally`."""
    fd = os.open(run_dir / ".lock", os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def now() -> float:
    return time.time()
