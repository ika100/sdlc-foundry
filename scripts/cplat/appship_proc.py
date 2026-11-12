"""Spec 155: a component repo of a system ship runs as its own `cplat headless "/component:ship <repo spec>"` process.

A subagent cannot start subagents, so a repo shipped by a subagent of the gitops session got no unit mode and no subagents of its
own (#560). Here every component repo gets the same headless run as a standalone `/component:ship`, started detached in
its clone and linked to the system ship by two variables: CPLAT_SYSTEM_DIR (the gitops clone; `component ship start` reads it
as `--system-dir`) and CPLAT_RUN_PARENT (the system ship's run: the repo's run is its child, so one budget covers both and
every token is counted once). The system ship state keeps {pid, log, started, starts} per repo; `spawn` and `alive` are the
seams tests replace.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

CPLAT = Path(__file__).resolve().with_name("cplat.py")
MAX_STARTS = 2          # AC-155.5: a session that ends before its ship once more is started again, a second end escalates


def command(spec_id: str) -> list[str]:
    """The repo's headless ship, with the plugin folders the system ship's own headless run was given (benchmarks)."""
    dirs = [d for d in os.environ.get("CPLAT_PLUGIN_DIRS", "").split(os.pathsep) if d]
    return [sys.executable, str(CPLAT), "headless", *[a for d in dirs for a in ("--plugin-dir", d)], f"/component:ship {spec_id}"]


def spawn(clone: Path, spec_id: str, gitops: Path, parent_run: str | None, starts: int = 1,
          answer: str | None = None) -> dict:
    """Start the repo's headless ship detached from this process; returns its state entry. Raises OSError."""
    import headless
    log = headless.log_dir(clone) / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}-system-ship.log"
    env = {**os.environ, "CPLAT_SYSTEM_DIR": str(gitops)}
    if parent_run:
        env["CPLAT_RUN_PARENT"] = parent_run
    env.pop("CPLAT_SHIP_ANSWER", None)
    if answer is not None:
        env["CPLAT_SHIP_ANSWER"] = answer
    with open(log, "ab") as out:
        p = subprocess.Popen(command(spec_id), cwd=clone, env=env, stdin=subprocess.DEVNULL, stdout=out,
                             stderr=subprocess.STDOUT, start_new_session=True)
    return {"pid": p.pid, "log": str(log), "started": dt.datetime.now().isoformat(timespec="seconds"), "starts": starts}


def alive(pid: int | None) -> bool:
    """True while the process runs (a finished child of this process is reaped, so it does not count as running)."""
    if not pid:
        return False
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    out = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, check=False)
    return out.returncode != 0 or "headless" in out.stdout      # a reused pid runs something else
