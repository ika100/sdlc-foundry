"""What every cplat wait shares (spec 143): the clock, the exit codes, the time format and the run record.

Exit codes: 0 the wanted state was reached, 1 red (or the awaited run escalated), 2 timeout ("run it again"). A wait inside an
unfinished run (the repo's ship run, a `runs begin` pointer, $CPLAT_RUN_PARENT, or the system ship run of a gitops-app repo)
adds its seconds to that run's `waiting_s` and one entry to its `waits`; outside a run it records its own run of kind `wait`
with a `wait` section {command, result, seconds} (AC-143.10).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import runs

REACHED, RED, TIMEOUT = 0, 1, 2
RESULTS = {REACHED: "reached", RED: "red", TIMEOUT: "timeout"}
DEFAULT_TIMEOUT = 540.0


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
        code, result = body()
        return code
    finally:
        secs = max(0.0, now() - begin)
        if rid:
            runs.mutate(rid, lambda rec: _add_wait(rec, name, result, secs))
        elif own:
            runs.finish(own, "done" if result == "reached" else "failed",
                        fields={"wait": {"command": name, "result": result, "seconds": round(secs)}, "waiting_s": secs})
