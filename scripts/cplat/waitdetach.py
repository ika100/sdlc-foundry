"""Detached waits (spec 202, AC-202.3): under `cplat headless` a `cplat` wait runs in its own process group, so it outlives
the session that started it (`claude -p` ends its shells when it exits), and records its exit code and last lines.

Files, in `<git dir>/cplat-waits/detached/`: `<id>.json` (the record, written by the calling process), `<id>.log` (the child's
stdout and stderr) and `<id>.result.json` (written by the child when it ends). `cplat waits handover` reports them to the
next session; `hold` is what `cplat headless` waits on before it starts a session.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import core

DIR = ("cplat-waits", "detached")
TAIL_LINES = 20
STREAM_POLL = 0.2

# argv after `cplat`, prefix match; `system ship next` only with `--wait` (see `wanted`)
WAIT_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("pr", "wait"), ("component", "ship", "land"), ("component", "ship", "wait"), ("system", "wait"), ("cluster", "wait"),
    ("dispatch", "wait"), ("component", "release", "wait"), ("component", "release", "gates"),
)
_NEXT = ("system", "ship", "next")


@dataclass
class Detached:
    id: str
    pid: int
    command: str
    argv: list[str] = field(default_factory=list)
    session: str | None = None
    log: str = ""
    started_at: str = ""


@dataclass
class Ended(Detached):
    result: dict | None = None
    code: int | None = None
    tail: list[str] = field(default_factory=list)
    ended_at: str = ""


@dataclass
class Hold:
    done: bool
    command: str | None = None


def folder(repo: Path, create: bool = False) -> Path | None:
    try:
        base = core.git_dir(repo)
    except (OSError, core.PlatformError):
        return None
    if base is None:
        return None
    d = base.joinpath(*DIR)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _matches(argv: list[str]) -> tuple[str, ...] | None:
    for prefix in WAIT_COMMANDS:
        if tuple(argv[:len(prefix)]) == prefix:
            return prefix
    if tuple(argv[:3]) == _NEXT and "--wait" in argv:
        return _NEXT
    return None


def command_of(argv: list[str]) -> str:
    """`cplat <prefix> <positionals>`: the words up to the first option."""
    prefix = _matches(argv)
    if prefix is None:
        return "cplat " + " ".join(argv[:1])
    words = list(prefix)
    for a in argv[len(prefix):]:
        if a.startswith("-"):
            break
        words.append(a)
    return "cplat " + " ".join(words)


def wanted(argv: list[str]) -> bool:
    """Detach only under `cplat headless`, never inside the detached child itself, and only in a git checkout."""
    if not os.environ.get("CPLAT_HEADLESS") or os.environ.get("CPLAT_WAIT_CHILD"):
        return False
    if _matches(argv) is None or any(a in ("-h", "--help") for a in argv):
        return False
    return folder(Path.cwd()) is not None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError, ValueError, OSError):
        return False
    return True


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _records(repo: Path) -> list[tuple[Detached, Path]]:
    d = folder(repo)
    found: list[tuple[Detached, Path]] = []
    if d is None or not d.is_dir():
        return found
    for f in d.glob("*.json"):
        if f.name.endswith(".result.json"):
            continue
        data = _read(f)
        try:
            rec = Detached(str(data["id"]), int(data["pid"]), str(data["command"]), list(data.get("argv") or []),
                           data.get("session"), str(data.get("log") or ""), str(data.get("started_at") or ""))
        except (KeyError, TypeError, ValueError):
            continue
        found.append((rec, d))
    return sorted(found, key=lambda x: x[0].started_at)


def _result(d: Path, ident: str) -> dict | None:
    return _read(d / f"{ident}.result.json")


def alive(repo: Path) -> list[Detached]:
    """The detached waits of the checkout still running (no result yet, process alive), oldest first."""
    return [r for r, d in _records(repo) if _result(d, r.id) is None and _alive(r.pid)]


def ended(repo: Path) -> list[Ended]:
    """The detached waits that ended, with their result or `result: None` when they were killed, oldest first."""
    out: list[Ended] = []
    for r, d in _records(repo):
        res = _result(d, r.id)
        if res is None and _alive(r.pid):
            continue
        code = res.get("code") if res else None
        out.append(Ended(**vars(r), result=res, code=code if isinstance(code, int) else None,
                         tail=[str(x) for x in (res or {}).get("tail") or []], ended_at=str((res or {}).get("ended_at") or "")))
    return out


def stop(d: Detached, grace: float = 10.0) -> None:
    """SIGTERM to the wait's process group, SIGKILL after `grace` seconds."""
    try:
        pgid = os.getpgid(d.pid)
    except OSError:
        return
    kill: Callable[[int], None] = (lambda s: os.killpg(pgid, s)) if pgid == d.pid else (lambda s: os.kill(d.pid, s))
    with contextlib.suppress(OSError):
        kill(signal.SIGTERM)
    end = time.monotonic() + grace
    while time.monotonic() < end and _alive(d.pid):
        time.sleep(0.1)
    if _alive(d.pid):
        with contextlib.suppress(OSError):
            kill(signal.SIGKILL)


def hold(repo: Path, *, limit_min: int = 120, poll: int = 5, clock: Callable[[], dt.datetime] = dt.datetime.now,
         sleep: Callable[[float], None] = time.sleep) -> Hold:
    """Return as soon as no detached wait of the checkout is alive; after `limit_min` minutes stop the wait instead."""
    start = clock()
    while True:
        running = alive(repo)
        if not running:
            return Hold(True)
        if (clock() - start) >= dt.timedelta(minutes=limit_min):
            for w in running:
                stop(w)
            return Hold(False, running[0].command)
        sleep(poll)


def _tail(log: Path) -> list[str]:
    try:
        lines = [ln.rstrip() for ln in log.read_text(errors="replace").splitlines()]
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][-TAIL_LINES:]


def finish_child(ident: str, code: int, argv: list[str] | None = None) -> None:
    """Called by the detached child at its end: write `<id>.result.json` from the exit code and the log's tail."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError, ValueError, AttributeError):
            stream.flush()
    d = folder(Path.cwd())
    if d is None:
        return
    record = _read(d / f"{ident}.json") or {}
    body = {"id": ident, "command": record.get("command") or command_of(argv or []), "code": code,
            "tail": _tail(d / f"{ident}.log"), "ended_at": dt.datetime.now().isoformat(timespec="seconds")}
    tmp = d / f"{ident}.result.tmp"
    with contextlib.suppress(OSError):
        tmp.write_text(json.dumps(body))
        tmp.replace(d / f"{ident}.result.json")


def _stream(d: Path, ident: str, gone: Callable[[], bool], command: str) -> int:
    log = d / f"{ident}.log"
    offset = 0
    while True:
        dead = gone()                      # looked at before the drain: a result is written before the process ends
        with contextlib.suppress(OSError):
            with log.open("rb") as fh:
                fh.seek(offset)
                data = fh.read()
            offset += len(data)
            if data:
                sys.stdout.write(data.decode(errors="replace"))
                sys.stdout.flush()
        res = _result(d, ident)
        if res is not None:
            return int(res.get("code") if isinstance(res.get("code"), int) else 1)
        if dead:
            print(f"wait {command} ended without a result")
            return 1
        time.sleep(STREAM_POLL)


def front(argv: list[str]) -> int:
    """The calling process of a wait under `cplat headless`: start (or join) the detached child, stream its log, exit with its code."""
    cwd = Path.cwd()
    d = folder(cwd, create=True)
    assert d is not None
    for w in alive(cwd):
        if w.argv == argv:
            return _stream(d, w.id, lambda w=w: not _alive(w.pid), w.command)
    ident = uuid.uuid4().hex[:8]
    command = command_of(argv)
    log = d / f"{ident}.log"
    with log.open("wb") as out:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("cplat.py")), *argv], cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                env={**os.environ, "CPLAT_WAIT_CHILD": ident})
    session = next((v for n in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID") if (v := (os.environ.get(n) or "").strip())), None)
    tmp = d / f"{ident}.tmp"
    tmp.write_text(json.dumps({"id": ident, "pid": proc.pid, "command": command, "argv": argv, "session": session,
                               "log": str(log), "started_at": dt.datetime.now().isoformat(timespec="seconds")}))
    tmp.replace(d / f"{ident}.json")
    return _stream(d, ident, lambda: proc.poll() is not None, command)


def handover_lines(repo: Path) -> list[str]:
    """What the next session of the checkout is told; each ended wait is reported once and its files removed."""
    lines: list[str] = []
    d = folder(repo)
    for e in ended(repo):
        if e.result is None:
            lines.append(f"wait {e.command} ended without a result")
        else:
            try:
                at = dt.datetime.fromisoformat(e.ended_at).strftime("%H:%M:%S")
            except ValueError:
                at = e.ended_at or "?"
            lines.append(f"wait {e.command} ended: exit {e.code} at {at}; its last lines:")
            lines.extend(f"  {ln}" for ln in e.tail)
        if d is not None:
            for f in d.glob(f"{e.id}.*"):
                f.unlink(missing_ok=True)
    lines.extend(f"wait {w.command} is still running (pid {w.pid})" for w in alive(repo))
    return lines


def main(argv: list[str]) -> int:
    """`cplat waits handover [--repo-dir DIR]`: always exit 0."""
    p = argparse.ArgumentParser(prog="cplat waits")
    p.add_argument("verb", choices=["handover"])
    p.add_argument("--repo-dir", default=".")
    args = p.parse_args(argv)
    for line in handover_lines(Path(args.repo_dir)):
        print(line)
    return 0
