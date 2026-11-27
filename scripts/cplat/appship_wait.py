"""Spec 216: `cplat system ship wait [--timeout T]` blocks on the detached system ship driver (AC-216.6).

It prints one timed line per driver step that ended during the call and ends with exactly one result: `DONE:`, `STOPPED:`,
`ESCALATED:`, `ENTRY:`, `ENDED:`, `WAIT:` (progress at the deadline) or `TIMEOUT:` (nothing changed). The polls use
`waits.now` / `waits.sleep` against a fixed deadline, so the call ends by T + 10 s at the latest.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import appship_driver
import appship_report
import appship_sched
import appship_state as state
import waits

NO_DRIVER = "no driver recorded for this system ship run; start it with cplat system ship drive"
NEXT_DRIVE = "next: cplat system ship drive"


def escalated_lines(st: dict) -> list[str]:
    """The `ESCALATED:` block (design.md, `system ship wait`)."""
    spec = st["spec"]
    lines = [f"ESCALATED: product ship {spec}: {st.get('escalated')} (cause {st.get('cause') or 'unknown'})"]
    for rid, r in (st.get("repos") or {}).items():
        if r.get("state") != "escalated":
            continue
        for q in appship_sched.questions_of(r.get("reason") or "", r.get("questions")):
            suggested = f"suggested: {q['suggested']}" if q.get("suggested") else "no suggestion"
            lines.append(f"{rid}: question: {q['text']} ({suggested})")
    lines += appship_report.state_table(st)
    lines += [f"log: {(st.get('driver') or {}).get('log') or '-'}", f"resume it with /system:ship {spec}"]
    return lines


def _words(argv: list[str]) -> str:
    """The words of a step up to the first option; `escalate` keeps only its verb (its reason is not for the line)."""
    if argv and argv[0] == "escalate":
        return "escalate"
    out: list[str] = []
    for a in argv:
        if a.startswith("-"):
            break
        out.append(a)
    return " ".join(out)


def _ts(text: object) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(text)).timestamp()
    except ValueError:
        return None


def _ended(steps: list[dict]) -> set[int]:
    return {i for i, s in enumerate(steps) if s.get("ended")}


def _result(st: dict | None, prog: dict | None, gitops: Path) -> tuple[int, list[str]] | None:
    """The first matching row 0-6 of the wait table, or None (rows 7 and 8 are the deadline's)."""
    end = (prog or {}).get("end") or {}
    kind = end.get("kind")
    if not (st and st.get("driver")) and kind != "done":
        return 1, [NO_DRIVER]
    if kind == "done":
        spec = (prog or {}).get("spec") or (st or {}).get("spec")
        return 0, [f"DONE: product ship {spec} is done", *(end.get("report") or []), f"archive: {end.get('archive') or '-'}"]
    if kind == "stopped":
        return 1, [f"STOPPED: {end.get('line')}"]
    assert st is not None
    if st.get("escalated"):
        return 1, escalated_lines(st)
    if kind == "entry":
        return 0, [f"ENTRY: {end.get('id')} in {end.get('worktree')}",
                   "next: build it as references/ship-entry.md says, then cplat system ship drive"]
    drv = st["driver"]
    if not appship_driver.alive(drv.get("pid")):
        if int(drv.get("starts") or 1) < appship_driver.MAX_STARTS:
            return 1, [f"ENDED: driver ended in phase {st['phase']}; log {drv.get('log')}", NEXT_DRIVE]
        esc = state.escalate(gitops, f"system ship driver ended twice in phase {st['phase']}; log {drv.get('log')}", "environment")
        return 1, escalated_lines(state.load_state(gitops) or esc)
    return None


def wait(gitops: Path, timeout: float, interval: float = 5.0) -> tuple[int, list[str]]:
    gitops = Path(gitops)
    begin = waits.now()
    deadline = begin + timeout
    st = state.load_state(gitops)
    prog = appship_driver.progress(gitops, st)
    steps0 = (prog or {}).get("steps") or []
    printed = _ended(steps0)
    n0, ended0 = len(steps0), len(printed)
    mark0 = state._mark(gitops, st)["phase"] if st else None
    progressed = False
    while True:
        st = state.load_state(gitops)
        prog = appship_driver.progress(gitops, st)
        steps = (prog or {}).get("steps") or []
        for i in sorted(_ended(steps) - printed):
            s = steps[i]
            print(f"{waits.clock()} driver: cplat system ship {_words(s.get('argv') or [])} -> exit {s.get('code')}", flush=True)
            printed.add(i)
        if len(steps) > n0 or len(printed) > ended0:
            progressed = True
        if st and state._mark(gitops, st)["phase"] != mark0:
            progressed = True
        if (res := _result(st, prog, gitops)) is not None:
            return res
        left = deadline - waits.now()
        if left <= 0:
            break
        waits.sleep(min(interval, left))
    if progressed:
        return 0, [f"WAIT: driver still going, progress in the last {timeout:g}s; run the same wait again"]
    assert st is not None
    last = None
    for s in reversed(steps):
        last = _ts(s.get("ended") or s.get("at"))
        if last is not None:
            break
    if last is None:
        last = _ts((prog or {}).get("started") or st["driver"].get("started"))
    since = waits.duration(waits.now() - last) if last is not None else "unknown time"
    return 2, [f"TIMEOUT: system ship {st['spec']} in phase {st['phase']}, no driver step for {since}; log {st['driver'].get('log')}"]
