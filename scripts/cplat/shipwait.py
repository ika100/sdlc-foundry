"""`component ship wait` and `system ship next --wait` (spec 143): block on a ship run instead of polling its status.

  cplat component ship wait [--repo DIR] [--phase P] [--timeout S]
      one line with the time per phase change of the clone's ship run; exit 0 at phase P or later (plan, build, pr, land,
      deploy, done; default done), 1 ESCALATED, 2 TIMEOUT; a clone without a ship run exits 1 at once
  cplat system ship next --wait [--timeout S] [--json]
      while the action is `wait`: a line per phase change of each running repo; a repo whose ship ended is recorded as
      `cplat system ship repo result <id>` does; then the next action, printed as `next` prints it; exit 2 TIMEOUT
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import appship_sched as sched
import appship_state as state
import runs
import ship
import waits
from core import PlatformError

SHIP_INTERVAL = 5.0
NEXT_INTERVAL = 10.0


def _archived(repo: Path, spec: str) -> dict | None:
    """The newest archived state of `spec` (`ship finish` moved it away while the wait ran)."""
    try:
        files = sorted(ship.state_path(repo).parent.glob(f"cplat-ship-{spec}-[0-9]*.json"))
        return json.loads(files[-1].read_text()) if files else None
    except (OSError, ValueError, PlatformError):
        return None


def _phase_start(st: dict) -> float | None:
    """When the run entered its current phase, from its run record; None when unknown."""
    rec = runs.active(st.get("run_id")) or {}
    for p in reversed(rec.get("phases") or []):
        if p.get("name") == st.get("phase") and p.get("ended_at") is None:
            try:
                return dt.datetime.fromisoformat(str(p["started_at"]).replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                return None
    return None


def ship_wait(repo: Path, phase: str | None, timeout: float, interval: float = SHIP_INTERVAL) -> tuple[int, list[str]]:
    st = ship.load_state(repo)
    if not st:
        raise PlatformError(f"no ship run in {repo}", hint="start one with /component:ship <spec> (cplat component ship start <spec>)")
    spec, target = st["spec"], ship.PHASES.index(phase or "done")
    begin = waits.now()
    seen, since = None, begin
    while True:
        st = ship.load_state(repo) or _archived(repo, spec) or st
        cur = st.get("phase") or "plan"
        if cur != seen:
            ship.say(f"{waits.clock()} ship {spec}: phase {cur}")
            seen, since = cur, _phase_start(st) or waits.now()
        if st.get("escalated"):
            return waits.RED, [f"ESCALATED: ship {spec}: {st['escalated']} (cause {st.get('cause') or 'unknown'})",
                               f"resume it with /component:ship {spec}"]
        if cur in ship.PHASES and ship.PHASES.index(cur) >= target:
            return waits.REACHED, [f"REACHED: ship {spec} is in phase {cur}"]
        left = timeout - (waits.now() - begin)
        if left <= 0:
            return waits.TIMEOUT, [f"TIMEOUT: ship {spec} is still in phase {cur} after {int(timeout)}s of waiting "
                                   f"(in it for {waits.duration(waits.now() - since)})", "run the same wait again"]
        waits.sleep(min(interval, left))


def next_wait(gitops: Path, timeout: float, as_json: bool, interval: float = NEXT_INTERVAL) -> tuple[int, dict | None, list[str]]:
    """(exit code, the action when it is no longer `wait`, the TIMEOUT lines)."""
    out = sys.stderr if as_json else sys.stdout
    begin = waits.now()
    seen: dict[str, str] = {}
    while True:
        st = state.require_state(gitops)
        action = sched.next_action(gitops, st)
        if action["action"] != "wait":
            return waits.REACHED, action, []
        ended = []
        for rid in action["running"]:
            clone = Path((st.get("repos") or {}).get(rid, {}).get("clone") or sched.clone_path(gitops, rid))
            sh = ship.load_state(clone) if clone.is_dir() else None
            text = ((sh or {}).get("phase") or "not started") + (" (escalated)" if (sh or {}).get("escalated") else "")
            if seen.get(rid) != text:
                print(f"{waits.clock()} {rid}: phase {text}", file=out, flush=True)
                seen[rid] = text
            if sh and (sh.get("escalated") or sh.get("phase") == "done"):
                ended.append(rid)
        for rid in ended:                         # the step /system:ship takes next: record the repo's result
            _, lines = sched.result(gitops, rid, st.get("context"))
            print("\n".join(lines), file=out, flush=True)
        if ended:
            continue
        left = timeout - (waits.now() - begin)
        if left <= 0:
            running = ", ".join(f"{rid} ({seen.get(rid, '?')})" for rid in action["running"]) or "none"
            return waits.TIMEOUT, None, [f"TIMEOUT: action still wait after {int(timeout)}s; running: {running}",
                                         "run the same wait again"]
        waits.sleep(min(interval, left))
