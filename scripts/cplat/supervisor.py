"""Spec 131: the supervisor of an unattended ship or build. One fresh session per unit, saved at checkpoints.

`drive` is called by `cplat headless` for `/component:ship` and `/component:build` with at least one spec.
It imports `headless` lazily, because headless imports this module.
"""
from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path
from typing import Callable

import budget
import ship
import stopgate
import units
from core import PlatformError

NO_CAP_MINUTES = 100000.0   # the timeout of one session when --max-minutes is not given


def _escalated(repo: Path) -> str | None:
    """The reason of an escalation made inside a session (ship state or units file), else None."""
    try:
        st = ship.load_state(repo)
    except PlatformError:
        st = None
    if st and st.get("escalated"):
        return f"{st['spec']} escalated in phase {st['phase']}: {st['escalated']}"
    data = units._read(repo)
    if data and data.get("escalated"):
        return str(data["escalated"].get("reason"))
    return None


def _session_count(repo: Path, unit: str) -> int:
    data = units._read(repo) or {"units": []}
    return next((int(u.get("sessions", 0)) for u in data["units"] if u["id"] == unit), 0)


def _summary(h, log: Path, repo: Path, spec: str, unit: str, k: int, end: str) -> None:
    line = f"{h.clock():%Y-%m-%d %H:%M} HEADLESS {repo.name}: {spec} unit {unit} session {k}: {end}  ({log.name})\n"
    with (log.parent / "summary.log").open("a") as fh:
        fh.write(line)


def _run_session(h, cmd: list[str], repo: Path, log: Path, minutes: float, rid: str | None, sid: str, env: dict[str, str]) -> int:
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return h.run_once(cmd, repo, log, minutes, rid, sid)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def drive(repo: Path, command: str, specs: list[str], prompt: str, make_cmd: Callable[[str], list[str]],
          extra_env: dict[str, str], rid: str | None, ns: argparse.Namespace, log: Path, state: dict) -> int:
    import headless as h
    command = command.strip()
    kind = command.rsplit(":", 1)[-1]   # units.py knows `ship` and `build`
    max_runs = getattr(ns, "max_runs", None)
    max_minutes = getattr(ns, "max_minutes", None)
    window = h.parse_window(getattr(ns, "quiet", None))
    no_wait = getattr(ns, "no_wait", False)
    begin = None
    last_line = budget.limits_line(rid)
    sessions = int(state.get("sessions") or 0)
    done: list[str] = []

    def end(result: str, code: int) -> int:
        state.update(result=result, code=code, sessions=sessions)
        return h.finish(repo, log, result, code)

    for spec in specs:
        units.prepare(repo, kind, spec)
        units.resume(repo)
        while True:
            data = units._read(repo) or {"units": []}
            unit = units.next_open(data)
            if unit is None:
                break
            wait = h.seconds_left_in_window(window, h.clock())
            if wait:
                if no_wait:
                    return end(f"inside the quiet window {ns.quiet}: not started", h.EXIT_QUIET)
                print(f"inside the quiet window {ns.quiet}: waiting {wait / 60:.0f} min", flush=True)
                h.sleep(wait)
            if h.stop_requested(repo):   # spec 167: a pause stops the run before its next session
                return end(h.PAUSED_RESULT, h.EXIT_STOPPED)
            begin = begin or h.clock()
            left = NO_CAP_MINUTES
            if max_minutes is not None:
                left = max_minutes - (h.clock() - begin).total_seconds() / 60
                if left <= 1:
                    result = f"time budget of {max_minutes:.0f} min used up"
                    budget.snapshot(repo, unit, result, [])
                    return end(result, h.EXIT_STOPPED)
            limit = budget.check(rid, "session", repo=repo)
            if limit:
                open_ship = h.unfinished(repo)
                if open_ship is not None:
                    result = ship.budget_stop(repo, open_ship, limit, "session")
                else:
                    result = budget.stop(rid, limit, "session")
                    budget.snapshot(repo, unit, result, [])
                return end(result, h.EXIT_STOPPED)
            if max_runs is not None and sessions >= max_runs:
                result = f"stopped after {max_runs} runs, ship run still unfinished"
                budget.snapshot(repo, unit, result, [])
                return end(result, h.EXIT_STOPPED)
            line = budget.limits_line(rid)
            if line and line != last_line:
                print(line, flush=True)
                last_line = line
            budget.count_invocation(rid)
            sessions += 1
            state["sessions"] = sessions
            sid = str(uuid.uuid4())
            if rid:
                import runs_usage
                runs_usage.register(rid, mode="own", session=sid)
            units.start_session(repo, unit, sid)
            k = _session_count(repo, unit)
            before = units.feature_head(repo, spec)
            print(f"run {sessions}: {spec} unit {unit} session {k}  (log: {log})", flush=True)
            start = log.stat().st_size if log.exists() else 0
            cmd = make_cmd(f"{prompt} --unit {unit}") + ["--session-id", sid]
            code = _run_session(h, cmd, repo, log, left, rid, sid, {**extra_env, "CPLAT_UNIT": unit})
            ending = units.end_session(repo, kind, spec, unit, before)
            commit = ending.get("checkpoint")
            reason = _escalated(repo)
            if commit:
                what = f"checkpoint {str(commit)[:7]}"
            elif reason:
                what = f"escalated: {reason}"
            elif code == 124:
                what = f"no checkpoint (timed out after {left:.0f} min)"
            else:
                what = f"no checkpoint (exit {code})"
            _summary(h, log, repo, spec, unit, k, what)
            if reason:
                return end(f"needs you: {reason}", h.EXIT_STOPPED)
            if commit and unit == "plan":
                budget.rescale(rid, repo, [spec])
                units.prepare(repo, kind, spec)   # the plan is committed: the task units appear now
            elif commit and unit == "verification":
                budget.end_grace(rid)
            if not commit and int(ending.get("stalls", 0)) >= units.STALL_LIMIT:
                text = f"no progress: unit {unit} after {units.STALL_LIMIT} sessions without a commit"
                msg = h.last_message(log, start)
                if excerpt := stopgate.excerpt(msg):
                    text += f"; last message: {excerpt}"
                try:
                    st = ship.load_state(repo)
                except PlatformError:
                    st = None
                use_ship = command.startswith("/component:ship") and st is not None
                cause = ship.no_progress_cause(repo, st if use_ship else {"spec": spec, "phase": "build"}, msg)
                state["cause"] = cause
                if use_ship:
                    ship.escalate(repo, text, cause)
                else:
                    units.escalate(repo, text, cause)
                return end(text, h.EXIT_STOPPED)
        if command.startswith("/component:ship"):
            try:
                st = ship.load_state(repo)
            except PlatformError:
                st = None
            deployed = (st or {}).get("deployed")
            if st is not None and not st.get("product"):   # spec 155: a system ship records and archives a linked run
                ship.finish(repo)
            done.append(f"shipped {spec}" + (f" ({deployed} in dev)" if deployed else ""))
        else:
            done.append("finished")
    result = "; ".join(done) if done else "finished"
    if all(d == "finished" for d in done):
        result = "finished"
    return end(result, h.EXIT_DONE)
