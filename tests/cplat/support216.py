"""Spec 216: shared seams of the acceptance tests (not a test module).

The driver (`scripts/cplat/appship_driver.py`) and the wait (`scripts/cplat/appship_wait.py`) do not exist yet, so a test imports
them through `mod(...)` inside its body: a missing module fails that test with a message that names it.

`Sim` is the simulation of AC-216.11. It replaces the driver's three seams (design.md "Decisions"): `spawn`, `alive` and
`run_step`. The step runner calls `appship.main` in this process with captured output, as the real step would run it as a
subprocess, so the system ship world of spec 097 (real git on a local bare origin, fake `gh`; the clock of spec 143) stays the
only fake. `canned` replaces single steps (a `TIMEOUT:` of `next --wait`, a `land` that exits 2) where the world cannot make
them happen offline. No test starts a process; a fake `claude` on PATH fails when called (`claude_trap`).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import io
import json
import os
import stat
import sys
from collections import deque
from pathlib import Path

import pytest

import appship
import appship_proc
import core
import ship
from test_143_shipwait import Clock
from test_155_repo_sessions import repo_spec
from test_appship_097 import GITOPS, SPEC, World  # noqa: F401  (re-exported)
from waiting import with_prelude

LOG = "/logs/system-ship-driver.log"
CPLAT = "cplat system ship"          # kept short: a literal of 4 words that a prompt holds verbatim is a pinned sentence (spec 168)
ENTRY_PLAN = [(GITOPS, "gitops-app", [], ["AC-012.1"], False), ("shop-api", "service-python", [], ["AC-012.1"], False)]
API_LIB = [("shop-api", "service-python", [], ["AC-012.1"], False), ("shop-lib", "library-python", ["shop-api"], ["AC-012.3"], False)]
API_WORKER = [("shop-api", "service-python", [], ["AC-012.1"], False), ("shop-worker", "service-python", [], ["AC-012.3"], False)]
API_ONLY = [("shop-api", "service-python", [], ["AC-012.1"], False)]
WAIT_ACTION = {"phase": "repos", "start": [], "running": ["shop-api"], "blocked": [], "escalated": [], "held": [], "action": "wait"}


def mod(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise
        pytest.fail(f"scripts/cplat/{name}.py does not exist yet (spec 216: plan tasks t1 and t2)")


class Killed(BaseException):
    """A driver killed in the middle of a step: nothing in the loop may catch it."""


def norm(argv) -> tuple[str, ...]:
    return tuple(a for a in argv if a != "--json")


class Sim:
    """The seams of the driver. `steps` is every step the loop took, as the argv after `cplat system ship`, without `--json`."""

    def __init__(self, w, monkeypatch):
        self.d = mod("appship_driver")
        self.w = w
        self.steps: list[tuple[str, ...]] = []
        self.canned: list[tuple[tuple[str, ...], deque]] = []
        self.kill_at: int | None = None
        self.live: set[int] = set()
        self.spawned: list[tuple] = []
        monkeypatch.setattr(self.d, "run_step", self.step)
        monkeypatch.setattr(self.d, "spawn", self.spawn)
        monkeypatch.setattr(self.d, "alive", lambda pid: pid in self.live)

    # ---- the seams
    def spawn(self, gitops, run_id, starts):
        self.spawned.append((str(gitops), run_id, starts))
        pid = os.getpid()                    # the simulated driver runs in this process: its progress file carries this pid
        self.live.add(pid)
        return {"pid": pid, "log": LOG, "started": "2026-11-23T10:00:00", "run_id": run_id, "starts": starts}

    def step(self, gitops, argv):
        argv = [str(a) for a in argv]
        self.steps.append(norm(argv))
        if self.kill_at is not None and len(self.steps) >= self.kill_at:
            raise Killed()
        for key, queue in self.canned:
            if norm(argv)[:len(key)] == key and queue:
                return queue.popleft()
        return self.inproc(gitops, argv)

    def inproc(self, gitops, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = appship.main(["--repo", str(gitops), *argv])
            except core.PlatformError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                if e.hint:
                    print(f"  fix: {e.hint}", file=sys.stderr)
                code = 1
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 2
        return self.d.Step(code=code, out=out.getvalue(), err=err.getvalue())

    # ---- helpers of a scenario
    def can(self, *key, results):
        """The next steps that start with `key` answer with `results` (Step objects, or (code, out, err) tuples); then the world answers."""
        queue = deque(self.d.Step(code=r[0], out=r[1], err=r[2] if len(r) > 2 else "") if isinstance(r, tuple) else r for r in results)
        self.canned.append((tuple(key), queue))

    def run(self) -> int:
        return self.d.loop(self.w.gitops)

    def verbs(self) -> list[str]:
        return [" ".join(s[:2]) if s[0] in ("repo", "phase") else s[0] for s in self.steps]


def timeout_line(n: int) -> str:
    return f"TIMEOUT: action still wait, no repo made progress for 540s; running: shop-api (build) [{n}]"


def timeout_step(n: int):
    return (2, f"{timeout_line(n)}\nrun the same wait again\n", "")


def wait_step():
    return (0, json.dumps(WAIT_ACTION), "WAIT: repos still running, progress in the last 540s; run the same wait again\n")


def app(w, *args):
    """`appship.main` through the world, with an argparse exit turned into a result (a missing verb fails its test)."""
    from test_appship_097 import Result
    try:
        return w.app(*args)
    except SystemExit as e:
        return Result(e.code if isinstance(e.code, int) else 2, f"argparse exit {e.code}")


def finish_repo(w, rid, **over):
    """The clone's ship, as a finished repo session leaves it, for the repo spec `repo start` wrote."""
    sid = repo_spec(w, rid).id
    w.ship_state(rid, **over)
    st = ship.load_state(w.clone(rid))
    st["spec"] = sid
    ship.save_state(w.clone(rid), st)


def escalate_repo_ship(w, rid, reason, cause, questions=None):
    sid = repo_spec(w, rid).id
    extra = {"questions": questions} if questions is not None else {}
    ship.save_state(w.clone(rid), {"spec": sid, "phase": "build", "recorded": True, "run_id": f"r-{rid}", "escalated": reason,
                                   "cause": cause, **extra})


def running_repo(w, rid, phase="build"):
    ship.save_state(w.clone(rid), {"spec": repo_spec(w, rid).id, "phase": phase, "recorded": True, "run_id": f"r-{rid}"})


def progress(w) -> dict | None:
    f = w.common / "cplat-app-ship-driver.json"
    return json.loads(f.read_text()) if f.is_file() else None


def claude_trap(tmp_path, monkeypatch) -> Path:
    """A `claude` first on PATH that records its call and fails: the driver must never run a model."""
    bin_dir = tmp_path / "claude-trap"
    bin_dir.mkdir()
    marker = tmp_path / "claude-was-called"
    f = bin_dir / "claude"
    f.write_text(with_prelude(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).write_text('called')\nraise SystemExit(7)\n"))
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return marker


# ---------------- fixtures (imported by the test modules) ----------------

@pytest.fixture()
def dw(tmp_path, monkeypatch, capsys):
    """The world of spec 097 with the repo preflight and Argo CD health passing (as spec 155's `w`)."""
    monkeypatch.delenv("CPLAT_SYSTEM_DRIVER", raising=False)       # the driver is on unless a test says otherwise
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(importlib.import_module("preflight"), "check_repo", lambda *a, **k: None)
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
    return world


@pytest.fixture()
def tick(monkeypatch):
    return Clock(monkeypatch)


@pytest.fixture()
def sessions(monkeypatch):
    """Every start of a repo session, with the answer it was given (`appship_proc.spawn` takes the `answer` keyword of spec 186)."""
    seen: list[dict] = []

    def fake(clone, spec_id, gitops, parent_run, starts=1, answer=None):
        seen.append({"clone": Path(clone).name, "spec": spec_id, "starts": starts, "answer": answer})
        # a session resumed with an answer has not saved the clone's ship again yet: the escalation in it is the run before's
        # (`updated` has second resolution, so such a session starts a moment later); a first start is never later than its ship
        later = dt.timedelta(seconds=2) if answer is not None else dt.timedelta(0)
        started = (dt.datetime.now() + later).isoformat(timespec="seconds")
        return {"pid": 5000 + len(seen), "log": f"{clone}/session.log", "started": started, "starts": starts}
    monkeypatch.setattr(appship_proc, "spawn", fake)
    return seen
