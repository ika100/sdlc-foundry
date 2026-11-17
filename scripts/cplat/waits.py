"""What every cplat wait shares (spec 143): the clock, the exit codes, the time format and the run record.

Exit codes: 0 the wanted state was reached, 1 red (or the awaited run escalated), 2 timeout ("run it again"). A wait inside an
unfinished run (the repo's ship run, a `runs begin` pointer, $CPLAT_RUN_PARENT, or the system ship run of a gitops-app repo)
adds its seconds to that run's `waiting_s` and one entry to its `waits`; outside a run it records its own run of kind `wait`
with a `wait` section {command, result, seconds} (AC-143.10).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import core
import runs

REACHED, RED, TIMEOUT = 0, 1, 2
RESULTS = {REACHED: "reached", RED: "red", TIMEOUT: "timeout"}
DEFAULT_TIMEOUT = 540.0
WAITS_DIR = "cplat-waits"


def now() -> float:                   # tests replace this
    return time.time()


def sleep(seconds: float) -> None:    # tests replace this
    time.sleep(seconds)


def clock(at: float | None = None) -> str:
    """Local wall time `HH:MM:SS` of `at` (default now)."""
    return time.strftime("%H:%M:%S", time.localtime(now() if at is None else at))


def duration(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s}s" if s < 120 else f"{s // 60} min"


def short(text: str | None, n: int = 7) -> str:
    return (text or "?")[:n]


def tag_short(tag: str | None) -> str:
    """`sha-4f2a91c…` for a long tag; a short one unchanged."""
    t = tag or ""
    return t if len(t) <= 14 else t[:11] + "…"


def attach(repo: Path) -> str | None:
    """The run a wait in `repo` runs inside: `runs.current`, else the unfinished system ship run of a gitops-app repo."""
    rid = runs.current(repo)
    if rid:
        return rid
    try:
        import appship_state
        st = appship_state.load_state(repo)
    except Exception:  # noqa: BLE001  (not a gitops-app repo, no git dir: no run)
        return None
    if st and st.get("phase") != "done" and not st.get("escalated") and runs.active(st.get("run_id")) is not None:
        return st["run_id"]
    return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError, ValueError, OSError):
        return False
    return True


REUSE_SLACK_S = 60


def _age(pid: int) -> float | None:
    """Seconds since process `pid` started (`ps -o etime=`, `[[dd-]hh:]mm:ss`); None when ps cannot tell."""
    try:
        out = core.run(["ps", "-o", "etime=", "-p", str(pid)], check=False).stdout.strip()
        days, _, clock_ = out.rpartition("-")
        parts = [int(x) for x in clock_.split(":")]
    except (OSError, ValueError, core.PlatformError):
        return None
    if not out or not 2 <= len(parts) <= 3:
        return None
    h, m, sec = ([0] * (3 - len(parts)) + parts)
    return (int(days or 0) * 86400) + h * 3600 + m * 60 + sec


def _reused(pid: int, started_at: object) -> bool:
    """True when `pid` now belongs to a process younger than the mark (#773): the wait that wrote it is gone and its pid was given
    to another process, so its mark held a Stop hook for days."""
    try:
        since = dt.datetime.fromisoformat(str(started_at))
    except ValueError:
        return False
    age = _age(pid)
    return age is not None and age + REUSE_SLACK_S < (dt.datetime.now() - since).total_seconds()

@contextlib.contextmanager
def running(command: str, cwd: Path | None = None) -> Iterator[None]:
    """Mark the wait `command` as running in the git dir of `cwd` while the block runs (spec 171, AC-171.8): the Stop hook
    reads the marks. Outside a checkout, or when the mark cannot be written, nothing is marked."""
    mark: Path | None = None
    try:
        base = core.git_dir(cwd or Path.cwd())
        if base is not None:
            folder = base / WAITS_DIR
            folder.mkdir(parents=True, exist_ok=True)
            mark = folder / f"{os.getpid()}.json"
            session = next((v for n in ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID") if (v := (os.environ.get(n) or "").strip())), None)
            mark.write_text(json.dumps({"pid": os.getpid(), "command": command, "session": session,
                                        "started_at": dt.datetime.now().isoformat(timespec="seconds")}))
    except (OSError, core.PlatformError):
        mark = None
    try:
        yield
    finally:
        if mark is not None:
            mark.unlink(missing_ok=True)


def live(repo: Path, session: str | None = None) -> list[str]:
    """Commands of the waits running in the checkout of `repo`, oldest first; the marks of dead processes are removed.
    With `session`, only the waits that session runs (and marks that name no session): another session's wait in the
    same checkout, such as the shipping session's `ship wait` on its detached run (spec 200), never holds this one (#765)."""
    try:
        base = core.git_dir(repo)
    except (OSError, core.PlatformError):
        return []
    if base is None:
        return []
    found: list[tuple[str, int, str]] = []
    for f in (base / WAITS_DIR).glob("*.json"):
        try:
            data = json.loads(f.read_text())
            pid, command = int(data["pid"]), str(data["command"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not _alive(pid) or _reused(pid, data.get("started_at")):
            f.unlink(missing_ok=True)
            continue
        if session and data.get("session") and data["session"] != session:
            continue
        found.append((str(data.get("started_at") or ""), pid, command))
    return [c for _, _, c in sorted(found)]


def _add_wait(rec: dict, name: str, result: str, seconds: float) -> None:
    rec["waiting_s"] = float(rec.get("waiting_s") or 0) + seconds
    rec.setdefault("waits", []).append({"wait": name, "result": result, "seconds": round(seconds)})


def record(repo: Path, name: str, body: Callable[[], tuple[int, str]], about: Path | None = None) -> int:
    """Run `body` (-> exit code, result word) inside the run of `repo` and record it; an own run is about `about` (default
    `repo`). An exception is recorded as `error` and raised again."""
    rid = attach(repo)
    own = None if rid else runs.start("wait", repo=runs.repo_slug(about or repo))
    begin = now()
    result, code = "error", RED
    try:
        with running(f"cplat {name}", Path.cwd()):
            code, result = body()
        return code
    finally:
        secs = max(0.0, now() - begin)
        if rid:
            runs.mutate(rid, lambda rec: _add_wait(rec, name, result, secs))
        elif own:
            runs.finish(own, "done" if result in ("reached", "progress") else "failed",
                        fields={"wait": {"command": name, "result": result, "seconds": round(secs)}, "waiting_s": secs})
