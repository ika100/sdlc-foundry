"""Spec 200: an interactive `/component:ship` hands the run to its own `cplat headless "/component:ship <spec>"` process.

The shipping session ran every phase in one context that filled up. `cplat component ship start <spec> --detach` runs the
ordinary `start` (every refusal, the claim, the branch switch), then starts the headless ship detached in the clone and records
it in the ship state under `headless` ({pid, log, started, starts, run_id, flags}). The headless run is a child of the
interactive session's ship run (CPLAT_RUN_PARENT), so one budget covers both and each token is counted once. A live process is
reused, an ended one is started once more (MAX_STARTS), and a headless session never hands off. The shipping session's own data
(its session id) lives in `<git common dir>/cplat-ship-handoff.json`, so the two processes never write the same file.
`spawn` and `alive` are the seams tests replace (as in appship_proc).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import appship_proc
import ship
import stopgate
from core import PlatformError

CPLAT = Path(__file__).resolve().with_name("cplat.py")
MAX_STARTS = 2          # AC-200.4: a process that ends early is started once more, a second early end escalates
HANDOFF_FILE = "cplat-ship-handoff.json"
NOT_HANDED_OFF = "headless: not handed off (this session runs under cplat headless)"
DROPPED = ("CLAUDE_CODE_SESSION_ID", "CPLAT_SESSION_ID", "CPLAT_UNIT", "CPLAT_HEADLESS", "CPLAT_SYSTEM_DIR",
           "CPLAT_SHIP_ANSWER", "CPLAT_SHIP_ANSWER_FROM")
ENDING_WAIT = 60        # seconds an escalated run's process may take to end


def command(spec_id: str, flags: list[str]) -> list[str]:
    """The headless ship, with the plugin folders this session was given (benchmarks)."""
    dirs = [d for d in os.environ.get("CPLAT_PLUGIN_DIRS", "").split(os.pathsep) if d]
    prompt = " ".join([f"/component:ship {spec_id}", *flags])
    return [sys.executable, str(CPLAT), "headless", *[a for d in dirs for a in ("--plugin-dir", d)], prompt]


def spawn(repo: Path, spec_id: str, flags: list[str], parent_run: str | None, starts: int = 1,
          answer: str | None = None) -> dict:
    """Start the headless ship detached from this process; returns its state entry. Raises OSError."""
    import headless
    log = headless.log_dir(repo) / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}-ship.log"
    env = {k: v for k, v in os.environ.items() if k not in DROPPED}
    if parent_run:
        env["CPLAT_RUN_PARENT"] = parent_run
    if answer is not None:
        env["CPLAT_SHIP_ANSWER"] = answer
        env["CPLAT_SHIP_ANSWER_FROM"] = "shipping session"
    with open(log, "ab") as out:
        p = subprocess.Popen(command(spec_id, flags), cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=out,
                             stderr=subprocess.STDOUT, start_new_session=True)
    return {"pid": p.pid, "log": str(log), "started": dt.datetime.now().isoformat(timespec="seconds"), "starts": starts,
            "run_id": parent_run, "flags": list(flags)}


def alive(pid: int | None) -> bool:
    return appship_proc.alive(pid)


def in_headless() -> bool:
    return bool(os.environ.get("CPLAT_HEADLESS") or os.environ.get("CPLAT_UNIT"))


# ---------------- the handoff file (written only by the shipping session) ----------------

def _file(repo: Path) -> Path:
    return ship.state_path(repo).parent / HANDOFF_FILE


def read_file(repo: Path) -> dict:
    try:
        data = json.loads(_file(repo).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_by(repo: Path, spec_id: str, session: str | None) -> None:
    old = read_file(repo)
    gate = old.get("gate") if old.get("spec") == spec_id and isinstance(old.get("gate"), dict) else {}
    _file(repo).write_text(json.dumps({"spec": spec_id, "by": session, "gate": gate}, indent=2) + "\n")


# ---------------- output ----------------

def escalated_lines(st: dict) -> list[str]:
    """The `ESCALATED:` lines of `ship wait` and of a refused third start."""
    lines = [f"ESCALATED: ship {st['spec']}: {st.get('escalated')} (cause {st.get('cause') or 'unknown'})"]
    for q in st.get("questions") or []:
        suggested = q.get("suggested")
        lines.append(f"question: {q.get('text')} (" + (f"suggested: {suggested}" if suggested else "no suggestion") + ")")
    if (st.get("headless") or {}).get("log"):
        lines.append(f"log: {st['headless']['log']}")
    lines.append(f"resume it with /component:ship {st['spec']}")
    return lines


def _handed_off(st: dict) -> str:
    h = st["headless"]
    return "\n".join([f"headless: pid {h['pid']}, log {h['log']}", ship.describe(st, next=False),
                      "next: cplat component ship wait"])


# ---------------- the --detach path of `ship start` ----------------

def detach(repo: Path, ns: argparse.Namespace) -> int:
    if in_headless():                                         # 1: a headless session never hands off
        print(NOT_HANDED_OFF)
        return ship.start_plain(repo, ns)
    sp = ship.specmod.find(repo, ns.spec)
    flags = [f for f, on in (("--no-merge", ns.no_merge), ("--full", ns.full)) if on]
    st = ship.load_state(repo)
    if st and st["spec"] == sp.id and st.get("headless") and alive(st["headless"].get("pid")):   # 2
        if not st.get("escalated"):
            write_by(repo, sp.id, stopgate.session_of_env())
            print(_handed_off(st))
            return 0
        waited = 0
        while alive(st["headless"].get("pid")) and waited < ENDING_WAIT:
            ship.sleep(2)
            waited += 2
        if alive(st["headless"].get("pid")):
            raise PlatformError(f"the headless session of {sp.id} (pid {st['headless'].get('pid')}) is still ending",
                                hint="run the same command again")
        st = ship.load_state(repo)
    if st and st["spec"] == sp.id and st["phase"] == "done" and not st.get("escalated"):       # 3
        log = (st.get("headless") or {}).get("log")
        print("headless: run is done" + (f"; log {log}" if log else ""))
        print(ship.describe(st))
        return 0
    st = ship.start(repo, ns.spec, not ns.no_merge, ns.take_over, None, ns.budget, detach=True)   # 4: no system link, the spawn drops it
    old = st.get("headless") or {}
    starts = old.get("starts", 0) + 1 if old and old.get("run_id") == st.get("run_id") and not alive(old.get("pid")) else 1   # 5
    if starts > MAX_STARTS:
        ship.escalate(repo, f"headless session ended twice in phase {st['phase']}; log {old.get('log')}", "environment")
        print("\n".join(escalated_lines(ship.require_state(repo))))
        return 1
    if st["phase"] in ("plan", "build", "pr"):
        ship.say(ship.on_branch(repo, st["branch"]))
    try:                                                      # 6
        entry = spawn(repo, sp.id, flags, st.get("run_id"), starts, ns.answer)
    except OSError as e:
        raise PlatformError(f"cannot start cplat headless: {e}") from e
    st["headless"] = entry
    ship.save_state(repo, st)
    write_by(repo, sp.id, stopgate.session_of_env())
    print(_handed_off(st))
    return 0
