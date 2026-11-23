"""Spec 202 test support: detached waits of a checkout, as design.md "Detached waits" describes them.

A detached wait is a real process in its own session (it ends when `Detached.release()` is called) with its three files in
`<git dir>/cplat-waits/detached/`: `<id>.json` (written by the caller), `<id>.log`, `<id>.result.json` (written when it ends).
"""
import datetime as dt
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import core
from waiting import budget, wait_for

SLEEPER = (
    "import os, sys, time\n"
    "while not os.path.exists(sys.argv[1]):\n"
    "    time.sleep(0.05)  # fake-delay: a wait that runs until the test releases it\n"
)


def detached_dir(repo: Path) -> Path:
    return core.git_dir(repo) / "cplat-waits" / "detached"


class Detached:
    def __init__(self, repo: Path, command: str = "cplat pr wait 7", ident: str = "w1", session: str | None = None):
        self.repo, self.command, self.ident = repo, command, ident
        d = detached_dir(repo)
        d.mkdir(parents=True, exist_ok=True)
        self.hold = d / f"{ident}.release"
        self.proc = subprocess.Popen([sys.executable, "-c", SLEEPER, str(self.hold)], start_new_session=True)
        threading.Thread(target=self.proc.wait, daemon=True).start()   # reaps it at once: a stopped wait is no zombie that looks alive
        self.log =d / f"{ident}.log"
        self.log.write_text("")
        (d / f"{ident}.json").write_text(json.dumps({
            "id": ident, "pid": self.proc.pid, "command": command, "argv": command.split()[1:], "session": session,
            "log": str(self.log), "started_at": dt.datetime(2026, 11, 15, 10, 0, 0).isoformat()}))

    def result_file(self) -> Path:
        return detached_dir(self.repo) / f"{self.ident}.result.json"

    def end(self, code: int | None = 0, tail: list[str] | None = None) -> None:
        """The wait ends: its process is gone; with `code` its result is recorded, without it it was killed."""
        self.hold.write_text("")
        self.proc.wait(timeout=budget())
        if code is not None:
            self.result_file().write_text(json.dumps({
                "id": self.ident, "command": self.command, "code": code, "tail": tail or [],
                "ended_at": dt.datetime(2026, 11, 15, 10, 30, 0).isoformat()}))

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        self.hold.write_text("")
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=budget())


class FakeTime:
    """Seams `clock` (a datetime) and `sleep`; a sleep moves the clock and calls `on_sleep(n, now)`."""

    def __init__(self, on_sleep=None, guard_polls=True):
        self.now = dt.datetime(2026, 11, 15, 10, 0, 0)
        self.sleeps = []
        self.on_sleep = on_sleep
        self.guard_polls = guard_polls   # False: the guard's look at a still running session is no sleep of the run (as #939)

    def clock(self):
        return self.now

    def sleep(self, seconds):
        import headless
        if not self.guard_polls and seconds == headless.GUARD_POLL:
            return
        self.sleeps.append(seconds)
        self.now += dt.timedelta(seconds=seconds)
        if self.on_sleep:
            self.on_sleep(len(self.sleeps), self.now)


def pid_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def wait_gone(pid: int) -> None:
    wait_for(lambda: pid_gone(pid), what=f"process {pid} to end")
