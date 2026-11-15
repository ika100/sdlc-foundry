"""Spec 200: shared seams of the acceptance tests (not a test module).

The hand-off starts `cplat headless "/component:ship <spec>"` as a detached process (design.md, "Contract"). No test starts one:
`Procs` replaces `subprocess.Popen` for a command line that carries `headless` and a `/component:ship` prompt (every other command,
git included, still runs for real) and `ship_handoff.alive` (the module's liveness seam). A test builds it inside its body, so a
missing `scripts/cplat/ship_handoff.py` fails that test with a message that names it.
"""
import json
import os
import subprocess
import types
from pathlib import Path

import pytest

import cplat
import ship

SPEC = "007-price-alerts"
BRANCH = f"feature/{SPEC}"
WAIT_COMMAND = "cplat component ship wait"  # interface: the command the hand-off tells the session to run
SESSION_VARS = ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_UNIT", "CPLAT_HEADLESS", "CPLAT_SYSTEM_DIR",
                "CPLAT_SHIP_ANSWER", "CPLAT_SHIP_ANSWER_FROM")


def handoff_module():
    try:
        import ship_handoff
    except ModuleNotFoundError:
        pytest.fail("scripts/cplat/ship_handoff.py does not exist yet (plan task t1: the module with the spawn/alive seams)")
    return ship_handoff


class Procs:
    """Fake headless processes: `spawned` (argv, cwd, env, kwargs, pid), `live` (pids that count as running), `fail` (OSError text)."""

    def __init__(self, monkeypatch, tmp_path):
        self.mod = handoff_module()
        self.spawned: list[dict] = []
        self.live: set[int] = set()
        self.fail: str | None = None
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        real = subprocess.Popen
        me = self

        def popen(argv, *a, **kw):
            words = [str(x) for x in argv] if isinstance(argv, (list, tuple)) else []
            if "headless" in words and words[-1].startswith("/component:ship"):
                if me.fail:
                    raise OSError(me.fail)
                pid = 4242 + len(me.spawned)
                me.spawned.append({"argv": words, "cwd": kw.get("cwd"), "env": dict(kw["env"] if kw.get("env") is not None else os.environ),
                                   "kw": kw, "pid": pid})
                me.live.add(pid)
                return types.SimpleNamespace(pid=pid)
            return real(argv, *a, **kw)
        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(self.mod, "alive", lambda pid: pid in me.live)

    @property
    def last(self) -> dict:
        return self.spawned[-1]


@pytest.fixture()
def procs(monkeypatch, tmp_path):
    return lambda: Procs(monkeypatch, tmp_path)


def cli(capsys, repo, *args):
    """`cplat component ship --repo REPO <args>` -> (exit code, stdout, stderr); an argparse exit is its code."""
    capsys.readouterr()
    try:
        rc = cplat.main(["component", "ship", "--repo", str(repo), *args])
    except SystemExit as e:
        rc = e.code
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def wait_cli(capsys, repo, *args):
    capsys.readouterr()
    rc = cplat.main(["component", "ship", "wait", "--repo", str(repo), *args])
    cap = capsys.readouterr()
    return rc, cap.out.splitlines(), cap.err


def interactive(monkeypatch, session="S1"):
    """An interactive session: its own session id, no headless/unit/answer variables."""
    for name in SESSION_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)


def handoff_file(repo) -> Path:
    return ship.state_path(Path(repo)).parent / "cplat-ship-handoff.json"


def headless_line(out: str) -> str | None:
    return next((ln for ln in out.splitlines() if ln.startswith("headless: pid ")), None)


def detach(capsys, repo, *args):
    return cli(capsys, repo, "start", "7", "--detach", *args)
