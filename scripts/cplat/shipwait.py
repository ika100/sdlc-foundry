"""`component ship wait` and `system ship next --wait` (spec 143): block on a ship run instead of polling its status.

  cplat component ship wait [--repo DIR] [--phase P] [--timeout S]
      one line with the time per phase change and per finished unit of the clone's ship run; exit 0 at phase P or later
      (plan, build, pr, land, deploy, done; default done), 1 ESCALATED (questions and log) or ENDED (a handed-off process
      died; the second end escalates as `environment`), 2 TIMEOUT (with the log); at the fixed deadline with progress
      (a phase, a unit or the feature branch moved) exit 0 with a `WAIT:` line (spec 200); a clone without a ship run exits 1 at once
  cplat system ship next --wait [--timeout S] [--json]
      while the action is `wait`: a line per phase change of each running repo; a repo whose ship ended is recorded as
      `cplat system ship repo result <id>` does; then the next action, printed as `next` prints it; when the timeout runs out with the action still `wait`:
      exit 0 with the action and a `WAIT:` line if a repo made progress, exit 2 TIMEOUT if none did (spec 194)
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import appship_sched as sched
import appship_state as state
import core
import runs
import ship
import ship_handoff
import units
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


def _done_units(repo: Path) -> list[str]:
    data = units._read(repo) or {}
    return [u["id"] for u in data.get("units") or [] if u.get("status") == "done"]


def _branch_head(repo: Path, branch: str | None) -> str:
    if not branch or not repo.is_dir():
        return ""
    p = core.run(["git", "rev-parse", "-q", "--verify", f"refs/heads/{branch}"], cwd=repo, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def ship_wait(repo: Path, phase: str | None, timeout: float, interval: float = SHIP_INTERVAL) -> tuple[int, list[str]]:
    st = ship.load_state(repo)
    if not st:
        raise PlatformError(f"no ship run in {repo}", hint="start one with /component:ship <spec> (cplat component ship start <spec>)")
    spec, target = st["spec"], ship.PHASES.index(phase or "done")
    begin = waits.now()
    seen, since = None, begin
    known: set[str] | None = None
    head: str | None = None
    progressed = False
    while True:
        st = ship.load_state(repo) or _archived(repo, spec) or st
        cur = st.get("phase") or "plan"
        if cur != seen:
            ship.say(f"{waits.clock()} ship {spec}: phase {cur}")
            progressed = progressed or seen is not None
            seen, since = cur, _phase_start(st) or waits.now()
        done = _done_units(repo)
        if known is not None:
            for u in done:
                if u not in known:
                    ship.say(f"{waits.clock()} ship {spec}: unit {u} done")
                    progressed = True
        known = set(done) | (known or set())
        now_head = _branch_head(repo, st.get("branch"))
        if head is not None and now_head != head:
            progressed = True
        head = now_head
        if st.get("escalated"):
            return waits.RED, ship_handoff.escalated_lines(st)
        if cur in ship.PHASES and ship.PHASES.index(cur) >= target:
            return waits.REACHED, [f"REACHED: ship {spec} is in phase {cur}"]
        hand = st.get("headless")
        log = (hand or {}).get("log")
        if hand and not ship_handoff.alive(hand.get("pid")):
            st = ship.load_state(repo) or st
            if not st.get("escalated") and st.get("phase") != "done":
                if int(hand.get("starts") or 1) < ship_handoff.MAX_STARTS:
                    return waits.RED, [f"ENDED: headless session ended in phase {cur}; log {log}",
                                       f"resume it with cplat component ship start {spec} --detach"]
                ship.escalate(repo, f"headless session ended a second time in phase {cur}; log {log}", "environment")
                return waits.RED, ship_handoff.escalated_lines(ship.load_state(repo) or st)
        left = timeout - (waits.now() - begin)
        if left <= 0:
            if progressed:
                return waits.REACHED, [f"WAIT: run still going, progress in the last {int(timeout)}s; run the same wait again"]
            lines = [f"TIMEOUT: ship {spec} is still in phase {cur} after {int(timeout)}s of waiting "
                     f"(in it for {waits.duration(waits.now() - since)})"]
            if log:
                lines.append(f"log: {log}")
            return waits.TIMEOUT, [*lines, "run the same wait again"]
        waits.sleep(min(interval, left))


def _head(clone: Path) -> str:
    p = core.run(["git", "rev-parse", "-q", "HEAD"], cwd=clone, check=False) if clone.is_dir() else None
    return (p.stdout.strip() if p and p.returncode == 0 else "")


def _before_start(sh: dict, entry: dict) -> bool:
    """Spec 169 (AC-169.4): the clone's escalation was saved before the repo's current session started, which is still
    alive: it belongs to the run before, and the new session clears it when it resumes."""
    proc = entry.get("proc") or {}
    if not proc.get("started") or not sched._session_runs(entry):
        return False
    try:
        return dt.datetime.fromisoformat(sh.get("updated") or "") < dt.datetime.fromisoformat(proc["started"])
    except ValueError:
        return False


def next_wait(gitops: Path, timeout: float, as_json: bool, interval: float = NEXT_INTERVAL) -> tuple[int, dict | None, list[str]]:
    """(exit code, the action when it is no longer `wait`, the TIMEOUT lines)."""
    out = sys.stderr if as_json else sys.stdout
    begin = waits.now()
    progressed = False
    seen: dict[str, str] = {}
    marks: dict[str, str] = {}
    while True:
        st = state.require_state(gitops)
        action = sched.next_action(gitops, st)
        if action["action"] != "wait":
            return waits.REACHED, action, []
        ended = []
        for rid in action["running"]:
            entry = (st.get("repos") or {}).get(rid, {})
            clone = Path(entry.get("clone") or sched.clone_path(gitops, rid))
            sh = ship.load_state(clone) if clone.is_dir() else None
            if sh is None and entry.get("spec") and clone.is_dir():   # spec 155: archived by the repo's own session
                sh = _archived(clone, entry["spec"])
            if sh and sh.get("escalated") and _before_start(sh, entry):   # spec 169: the session just started has not resumed yet
                sh = {**sh, "escalated": None}
            text = ((sh or {}).get("phase") or "not started") + (" (escalated)" if (sh or {}).get("escalated") else "")
            if seen.get(rid) != text:
                print(f"{waits.clock()} {rid}: phase {text}", file=out, flush=True)
                seen[rid] = text
            mark = f"{text} {_head(clone)}"   # spec 194: a new phase or commit is progress; the deadline stays fixed
            if marks.get(rid) not in (None, mark):
                progressed = True
            marks[rid] = mark
            if sh and (sh.get("escalated") or sh.get("phase") == "done"):
                ended.append(rid)
            elif line := sched.check_session(gitops, rid, sh):        # spec 155 (AC-155.5)
                print(f"{waits.clock()} {line}", file=out, flush=True)
                progressed = True
        for rid in ended:                         # the step /system:ship takes next: record the repo's result
            _, lines = sched.result(gitops, rid, st.get("context"))
            print("\n".join(lines), file=out, flush=True)
        if ended:
            continue
        left = timeout - (waits.now() - begin)
        if left <= 0:
            if progressed:
                return waits.REACHED, action, [f"WAIT: repos still running, progress in the last {int(timeout)}s; run the same wait again"]
            running =", ".join(f"{rid} ({seen.get(rid, '?')})" for rid in action["running"]) or "none"
            return waits.TIMEOUT, None, [f"TIMEOUT: action still wait, no repo made progress for {int(timeout)}s; running: {running}",
                                         "run the same wait again"]
        waits.sleep(min(interval, left))
