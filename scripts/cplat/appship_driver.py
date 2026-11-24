"""Spec 216: the system ship's mechanical loop runs in `cplat`, not in a model session.

`cplat system ship drive` starts one detached driver per run (`drive --loop`, hidden) in the gitops repo. The driver applies the
rules `/system:ship` prescribed for the phases `publish`, `repos` and `complete`, one `cplat system ship` subprocess per step, and
starts no model. It ends on the gitops entry (the session builds it), a stop rule, an escalation or `finish`. Its state is the
system ship state (key `driver`: {pid, log, started, run_id, starts}) and its progress file `<git dir>/cplat-app-ship-driver.json`
(written only by the driver process, atomically; it outlives `finish`, which archives the state). `spawn`, `alive` and `run_step`
are the seams tests replace.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import appship_proc
import appship_report
import appship_sched
import appship_state as state
from core import PlatformError

MAX_STARTS = 2                       # AC-216.6: a driver that ends early is started once more, a second early end escalates
PROGRESS_FILE = "cplat-app-ship-driver.json"
SWITCH = "CPLAT_SYSTEM_DRIVER"       # `0` brings back the loop in the session (AC-216.10)
RUN_VAR = "CPLAT_SYSTEM_DRIVER_RUN"
SCRUBBED = ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_HEADLESS", "CPLAT_SHIP_ANSWER", "CPLAT_SHIP_ANSWER_FROM")
VERB = "cplat system ship"
OFF_LINE = f"driver: off ({SWITCH}=0); run phase repos in this session"
TIMEOUTS = 3                         # `TIMEOUT:` results (and `land` exits 2) in a row that escalate


@dataclass
class Step:
    code: int
    out: str
    err: str = ""


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------------- the seams ----------------

def spawn(gitops: Path, run_id: str, starts: int) -> dict:
    """Start `drive --loop` detached from this process; returns the `driver` entry of the state. Raises OSError."""
    import headless
    log = headless.log_dir(Path(gitops)) / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}-system-ship-driver.log"
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    env[RUN_VAR] = run_id
    cmd = [sys.executable, str(appship_proc.CPLAT), "system", "ship", "--repo", str(gitops), "drive", "--loop"]
    with open(log, "ab") as out:
        p = subprocess.Popen(cmd, cwd=gitops, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)
    return {"pid": p.pid, "log": str(log), "started": now_iso(), "run_id": run_id, "starts": starts}


def alive(pid: int | None) -> bool:
    return appship_proc.alive(pid, marker="drive")


def run_step(gitops: Path, argv: list[str]) -> Step:
    """One `cplat system ship <argv>` as a subprocess, the output captured."""
    res = subprocess.run([sys.executable, str(appship_proc.CPLAT), "system", "ship", "--repo", str(gitops), *argv],
                         cwd=gitops, capture_output=True, text=True, check=False)
    return Step(res.returncode, res.stdout, res.stderr)


# ---------------- the progress file ----------------

def progress_path(gitops: Path) -> Path:
    return state.git_dir(gitops) / PROGRESS_FILE


def progress(gitops: Path, st: dict | None = None) -> dict | None:
    """The driver's progress file. While a state with a `driver` exists, a file of another pid is ignored."""
    f = progress_path(gitops)
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    st = st if st is not None else state.load_state(gitops)
    if st and st.get("driver") and data.get("pid") != st["driver"].get("pid"):
        return None
    return data


def _write_progress(gitops: Path, data: dict) -> None:
    f = progress_path(gitops)
    tmp = f.with_name(f.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, f)


# ---------------- drive ----------------

def escalated_lines(st: dict) -> list[str]:
    """The `ESCALATED:` block (design.md, `system ship wait`)."""
    spec = st["spec"]
    lines = [f"ESCALATED: product ship {spec}: {st.get('escalated')} (cause {st.get('cause') or 'unknown'})"]
    for rid, r in (st.get("repos") or {}).items():
        if r.get("state") != "escalated":
            continue
        for q in appship_sched.questions_of(r.get("reason") or "", r.get("questions")):
            lines.append(f"{rid}: question: {q['text']} (suggested: {q.get('suggested') or 'no suggestion'})"
                         if q.get("suggested") else f"{rid}: question: {q['text']} (no suggestion)")
    lines += appship_report.state_table(st)
    lines += [f"log: {(st.get('driver') or {}).get('log') or '-'}", f"resume it with /system:ship {spec}"]
    return lines


def drive(gitops: Path) -> int:
    if os.environ.get(SWITCH) == "0":
        print(OFF_LINE)
        return 0
    gitops = Path(gitops)
    exceeded: tuple[str, str] | None = None
    with state._locked(gitops):
        st = state.load_state(gitops)
        if not st:
            print("no system ship run in this repo; start one with /system:ship <spec>")
            return 1
        phase, spec = st["phase"], st["spec"]
        if st.get("escalated"):
            print(f"phase {phase}: the run is escalated; resume it with /system:ship {spec}")
            return 1
        if phase == "plan":
            print(f"phase plan: plan the product first (/system:plan {spec}), then {VERB} phase publish")
            return 1
        if phase == "done":
            print(f"phase done: the run is finished; {VERB} finish")
            return 1
        cur = st.get("driver") or {}
        same_run = bool(cur) and cur.get("run_id") == st.get("run_id")
        if same_run and alive(cur.get("pid")):
            print(f"driver: pid {cur['pid']}, log {cur['log']}")
            print(f"next: {VERB} wait")
            return 0
        starts = 1
        if same_run:
            prog = progress(gitops, st)
            starts = 1 if prog and prog.get("end") else int(cur.get("starts") or 1) + 1
        if starts > MAX_STARTS:
            exceeded = (phase, str(cur.get("log")))
        else:
            try:
                rec = spawn(gitops, st["run_id"], starts)
            except OSError as e:
                raise PlatformError(f"cannot start the system ship driver: {e}") from e
            st["driver"] = rec
            state.save_state(gitops, st)
            print(f"driver: pid {rec['pid']}, log {rec['log']}")
            print(f"next: {VERB} wait")
            return 0
    phase, log = exceeded
    esc = state.escalate(gitops, f"system ship driver ended twice in phase {phase}; log {log}", "environment")
    print("\n".join(escalated_lines(esc)))
    return 1


# ---------------- the loop ----------------

class _End(Exception):
    """The driver ends; `end` is the progress file's end record (None: the state tells the wait why)."""

    def __init__(self, end: dict | None = None) -> None:
        super().__init__()
        self.end = end


def _lines(r: Step) -> list[str]:
    return [ln.strip() for ln in (r.out + "\n" + r.err).splitlines() if ln.strip()]


def _timeout_line(r: Step) -> str:
    lines = _lines(r)
    return next((ln for ln in lines if ln.startswith("TIMEOUT:")), lines[0] if lines else "TIMEOUT: no output")


class _Loop:
    def __init__(self, gitops: Path, st: dict) -> None:
        drv = st.get("driver") or {}
        self.gitops = gitops
        self.log = drv.get("log")
        self.data: dict = {"spec": st["spec"], "run_id": st.get("run_id"), "pid": os.getpid(), "log": self.log,
                           "started": now_iso(), "steps": [], "end": None}
        _write_progress(gitops, self.data)

    # -- one step
    def step(self, *argv: str) -> Step:
        rec = {"at": now_iso(), "argv": list(argv), "code": None}
        self.data["steps"].append(rec)
        _write_progress(self.gitops, self.data)
        self._log(f"=== {dt.datetime.now():%H:%M:%S} {VERB} {' '.join(argv)}\n")
        r = run_step(self.gitops, list(argv))
        self._log(r.out + ("\n" if r.out and not r.out.endswith("\n") else "") + r.err
                  + ("\n" if r.err and not r.err.endswith("\n") else "") + f"=== exit {r.code}\n")
        lines = _lines(r)
        rec.update(code=r.code, line=lines[0] if lines else "", ended=now_iso())
        _write_progress(self.gitops, self.data)
        return r

    def _log(self, text: str) -> None:
        if not self.log:
            return
        try:
            with open(self.log, "a") as f:
                f.write(text)
        except OSError:
            pass

    # -- ends
    def end(self, kind: str | None = None, **fields: object) -> None:
        raise _End({"kind": kind, **fields, "at": now_iso()} if kind else None)

    def escalate_timeout(self, r: Step) -> None:
        self.step("escalate", _timeout_line(r), "--cause", "environment")
        self.end()

    # -- the turn
    def turn(self) -> None:
        st = state.load_state(self.gitops)
        if not st or st.get("escalated") or st["phase"] == "done":
            self.end()
        assert st is not None
        for rid, rp in (st.get("repos") or {}).items():
            if rp.get("shape") == "gitops-app" and rp.get("state") == "running":
                self.end("entry", id=rid, worktree=rp.get("clone"))
        phase = st["phase"]
        if phase == "publish":
            r = self.step("publish")
            if r.code != 0:
                lines = _lines(r)
                self.end("stopped", line=next((ln for ln in lines if " is red" in ln), lines[0] if lines else f"publish exited {r.code}"))
        elif phase == "complete":
            self.complete_steps(True)
        elif phase == "repos":
            r = self.step("next", "--json")
            try:
                action = json.loads(r.out)
            except ValueError:
                action = None
            if r.code != 0 or not isinstance(action, dict):
                self.end()
            self.act(action)
        else:
            self.end()

    def act(self, a: dict) -> None:
        kind = a.get("action")
        if kind == "start":
            self.start(a)
        elif kind == "wait":
            self.wait()
        elif kind == "answer":
            ans = a["answer"]
            qs = ans.get("questions") or []
            if ans.get("cause") == "decision" and qs and all(q.get("suggested") for q in qs):
                text = "; ".join(f"{q['text']}: {q['suggested']}" for q in qs)
                r = self.step("repo", "resume", ans["id"], "--answer", text)
            else:
                r = self.step("repo", "hold", ans["id"])
            if r.code != 0:
                self.end()
        elif kind == "escalate":
            st = state.load_state(self.gitops) or {}
            ids = a.get("escalated") or []
            reason = ((st.get("repos") or {}).get(ids[0]) or {}).get("reason") if ids else None
            self.step("escalate", reason or "no repo can go on")
            self.end()
        elif kind == "land":
            self.land()
        elif kind == "complete":
            self.complete_steps(False)
        else:
            self.end()

    def start(self, a: dict) -> None:
        listed = a.get("start") or []
        if not listed:
            self.end()
        for s in listed:
            r = self.step("repo", "start", s["id"])
            if r.code == 0:
                continue
            text = r.out + "\n" + r.err
            if "preflight failed:" in text:
                continue
            if "has uncommitted changes" in text:
                self.end("stopped", line=next(ln for ln in _lines(r) if "has uncommitted changes" in ln))
            st = state.load_state(self.gitops) or {}
            if st.get("escalated") or ((st.get("repos") or {}).get(s["id"]) or {}).get("state") == "escalated":
                continue
            self.end()
        entry = next((s for s in listed if s.get("entry")), None)
        if entry:
            self.end("entry", id=entry["id"], worktree=entry.get("clone"))

    def wait(self) -> None:
        timeouts = 0
        while True:
            r = self.step("next", "--wait", "--json")
            if r.code == 0:
                try:
                    action = json.loads(r.out)
                except ValueError:
                    self.end()
                if not isinstance(action, dict):
                    self.end()
                if "WAIT:" in r.err or action.get("action") == "wait":
                    timeouts = 0
                    continue
                self.act(action)
                return
            if r.code == 2:
                timeouts += 1
                if timeouts >= TIMEOUTS:
                    self.escalate_timeout(r)
                continue
            self.end()

    def land(self) -> None:
        twos = 0
        while True:
            r = self.step("land")
            if r.code == 0:
                self.complete_steps(False)
            elif r.code == 3:
                continue
            elif r.code == 2:
                twos += 1
                if twos >= TIMEOUTS:
                    self.escalate_timeout(r)
            else:
                self.end()

    def complete_steps(self, phase_already_set: bool) -> None:
        if not phase_already_set and self.step("phase", "complete").code != 0:
            self.end()
        r = self.step("complete")
        if r.code != 0:
            self.end()
        f = self.step("finish")
        if f.code != 0:
            self.end()
        m = re.search(r"state archived to (.+)", f.out)
        self.end("done", report=r.out.splitlines(), archive=m.group(1).strip() if m else None)


def loop(gitops: Path) -> int:
    """`drive --loop`: the driver process. Returns 0; the progress file and the state say how it ended."""
    gitops = Path(gitops)
    with state._locked(gitops):                  # `drive` holds the lock until it has recorded this process
        st = state.load_state(gitops)
    if not st:
        return 0
    run = _Loop(gitops, st)
    try:
        while True:
            run.turn()
    except _End as e:
        if e.end:
            run.data["end"] = e.end
            _write_progress(gitops, run.data)
    return 0
