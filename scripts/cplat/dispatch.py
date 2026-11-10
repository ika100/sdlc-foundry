"""cplat dispatch: run the backlog in slots (spec 167).

  cplat dispatch start [--once]                  the loop: claim ready items, run each in its own worktree, land, report
  cplat dispatch plan [--json]                   what the next cycle would do (reads, writes nothing to GitHub)
  cplat dispatch status [--json]                 slots, queue, held items, tokens of the day (local reads)
  cplat dispatch wait [--timeout S]              block until an escalation or red check (exit 1), idle (0) or the timeout (2)
  cplat dispatch report [--since D] [--json]     per day: delivered, escalated, held, tokens
  cplat dispatch inbox [--json]                  what needs you in this repo (`cplat needs` in repo scope)
  cplat dispatch pause [--drain] | resume [<item>] | slots <N> | prioritize <item> | skip <item> --reason <text>

Every verb takes `--repo DIR` (default `.`). The policy is `.platform/dispatch.yml` (see docs/dispatch.md). `land` is the hidden verb
the dispatcher spawns for a fix unit with an open pull request.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import dispatch_cycle
import dispatch_policy
import dispatch_state as ds
import dispatch_units as du
import dispatch_view
import needs as needsmod
import waits
from core import PlatformError

TICK = 5.0                 # seconds between looks at the units
CYCLE_EVERY = 60.0         # a cycle at least this often
SNAPSHOT_AGE = 300         # the loop reads GitHub again when its snapshot is older than this
INBOX_KINDS = ("approve", "answer", "escalation", "triage", "budget", "stuck")

sleep = time.sleep         # seams for tests
clock = time.monotonic


def _out(text: str) -> None:
    print(text, flush=True)


def _json(doc: object) -> None:
    _out(json.dumps(doc, indent=2))


# ---------------- the loop ----------------

def _live_pids(repo: Path, slug: str) -> set[int]:
    pids = set()
    for u in du.adopt(repo, slug):
        pid = u.get("land_pid") if u.get("status") == "landing" else u.get("pid")
        if isinstance(pid, int) and du.alive(pid):
            pids.add(pid)
    return pids


def _steering(slug: str) -> str:
    return json.dumps(ds.load(slug).get("steering"), sort_keys=True, default=str)


def _cycle(repo: Path, policy, last_no_starts: str | None, *, once: bool) -> str | None:
    """One cycle: print its action lines (the `no starts:` line of the loop only when it changed). Returns the last such line."""
    res = dispatch_cycle.run_cycle(repo, policy, max_age=0 if once else SNAPSHOT_AGE)
    no_starts = None
    for line in res.lines:
        if line.startswith("no starts:"):
            no_starts = line
            if not once and line == last_no_starts:
                continue
        _out(line)
    return no_starts


def _start(repo: Path, once: bool) -> int:
    policy = dispatch_policy.load(repo, require_file=True, require_budget=True)
    slug = ds.slug_of(repo)
    with ds.loop_lock(slug):
        if once:
            _cycle(repo, policy, None, once=True)
            return 0
        stop = {"now": False}

        def handler(signum, _frame) -> None:
            stop["now"] = True

        old = {s: signal.signal(s, handler) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            _loop(repo, slug, policy, stop)
        finally:
            for s, h in old.items():
                signal.signal(s, h)
    return 0


def _loop(repo: Path, slug: str, policy, stop: dict) -> None:
    last_no_starts: str | None = None
    last_cycle = float("-inf")
    pids: set[int] = set()
    steering = _steering(slug)
    while not stop["now"]:
        now = clock()
        live = _live_pids(repo, slug)
        changed = _steering(slug)
        if now - last_cycle >= CYCLE_EVERY or pids - live or changed != steering:
            try:
                policy = dispatch_policy.load(repo, require_file=True, require_budget=True)
            except PlatformError as err:
                print(f"ERROR: {err} (keeping the policy of the last cycle)", file=sys.stderr, flush=True)
            try:
                last_no_starts = _cycle(repo, policy, last_no_starts, once=False) or last_no_starts
            except PlatformError as err:
                print(f"ERROR: {err}", file=sys.stderr, flush=True)
            except Exception as err:  # noqa: BLE001  one failed cycle never ends the dispatcher
                print(f"ERROR: dispatch cycle failed: {type(err).__name__}: {err}", file=sys.stderr, flush=True)
            last_cycle = clock()
            live = _live_pids(repo, slug)
            steering = _steering(slug)
        pids = live
        end = clock() + TICK
        while not stop["now"] and clock() < end:
            sleep(min(0.5, max(0.0, end - clock())))


# ---------------- the read verbs ----------------

def _plan(repo: Path, as_json: bool) -> int:
    policy = dispatch_policy.load(repo)
    doc = dispatch_cycle.evaluate(repo, policy, max_age=0)
    _json(doc) if as_json else _out(dispatch_view.render_plan(doc))
    return 0


def _status(repo: Path, as_json: bool) -> int:
    policy = dispatch_policy.load(repo)
    doc = dispatch_view.status_doc(repo, ds.slug_of(repo), policy)
    _json(doc) if as_json else _out(dispatch_view.render_status(doc))
    return 0


def _wait(repo: Path, timeout: float) -> int:
    slug = ds.slug_of(repo)

    def body() -> tuple[int, str]:
        code, lines = dispatch_view.wait_result(slug, timeout)
        for line in lines:
            _out(line)
        return code, waits.RESULTS.get(code, "error")

    return waits.record(repo, "dispatch wait", body)


def _report(repo: Path, since: int, as_json: bool) -> int:
    doc = dispatch_view.report_doc(ds.slug_of(repo), since)
    _json(doc) if as_json else _out(dispatch_view.render_report(doc))
    return 0


def _inbox(repo: Path, as_json: bool) -> int:
    doc = needsmod.collect_repo(repo)
    doc = {**doc, "items": [i for i in doc["items"] if i.get("kind") in INBOX_KINDS]}
    _json(doc) if as_json else _out(needsmod.render(doc))
    return 0


# ---------------- steering ----------------

def _pause(repo: Path, drain: bool) -> int:
    mode = ds.pause(ds.slug_of(repo), drain)
    _out("draining: running units finish, nothing new starts" if mode == "drain"
         else "paused: nothing new starts; running units stop at their next checkpoint")
    return 0


def _resume(repo: Path, item: str | None) -> int:
    dispatch_policy.load(repo, require_file=True, require_budget=True)
    slug = ds.slug_of(repo)
    if item:
        key = ds.parse_item(item)
        ds.resume_item(slug, key)
        _out(f"resumed {ds.item_of(key)}: its skip and hold are dropped")
        return 0
    ds.resume(slug)
    du.clear_flags(du.adopt(repo, slug))
    _out("resumed: starts continue, paused units restart first")
    return 0


def _slots(repo: Path, n: int) -> int:
    ds.set_slots(ds.slug_of(repo), n)
    _out(f"slots: {n}")
    return 0


def _prioritize(repo: Path, item: str) -> int:
    key = ds.parse_item(item)
    ds.pin(ds.slug_of(repo), key)
    _out(f"prioritized {ds.item_of(key)}: first in line until its unit starts")
    return 0


def _skip(repo: Path, item: str, reason: str) -> int:
    key = ds.parse_item(item)
    ds.skip(ds.slug_of(repo), key, reason)
    _out(f"skipped {ds.item_of(key)}: {reason}")
    return 0


def _land(repo: Path, unit: str) -> int:
    return du.land(repo, ds.slug_of(repo), unit)


# ---------------- the command line ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat dispatch", description="Run the backlog in slots (spec 167).")
    sub = p.add_subparsers(dest="verb", required=True)

    def verb(name: str, help_text: str | None, *, json_flag: bool = False) -> argparse.ArgumentParser:
        v = sub.add_parser(name, help=help_text)
        v.add_argument("--repo", default=".", metavar="DIR", help="the repo (default .)")
        if json_flag:
            v.add_argument("--json", action="store_true")
        return v

    verb("start", "run the dispatcher loop").add_argument("--once", action="store_true", help="run one cycle and exit")
    verb("plan", "what the next cycle would do", json_flag=True)
    verb("status", "slots, queue, held items and tokens", json_flag=True)
    verb("inbox", "what needs you in this repo", json_flag=True)
    w = verb("wait", "block until something needs you or nothing runs")
    w.add_argument("--timeout", type=float, default=waits.DEFAULT_TIMEOUT, metavar="S", help="seconds (default 540)")
    r = verb("report", "delivered, escalated, held and tokens per day", json_flag=True)
    r.add_argument("--since", type=int, default=7, metavar="D", help="days (default 7)")
    verb("pause", "stop new starts; running units stop at a checkpoint").add_argument(
        "--drain", action="store_true", help="let running units finish")
    verb("resume", "allow starts again, or resume one item").add_argument("item", nargs="?")
    verb("slots", "set the number of slots (1..10)").add_argument("n", type=int, metavar="N")
    verb("prioritize", "start this item first").add_argument("item")
    s = verb("skip", "hold an item until `resume <item>`")
    s.add_argument("item")
    s.add_argument("--reason", required=True, metavar="TEXT")
    lnd = sub.add_parser("land", help=argparse.SUPPRESS)       # hidden: spawned by the dispatcher
    lnd.add_argument("unit")
    lnd.add_argument("--repo", default=".", metavar="DIR")
    return p


def main(argv: list[str]) -> int:
    try:
        ns = build_parser().parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    repo = Path(ns.repo).resolve()
    v = ns.verb
    if v == "start":
        return _start(repo, ns.once)
    if v == "plan":
        return _plan(repo, ns.json)
    if v == "status":
        return _status(repo, ns.json)
    if v == "wait":
        return _wait(repo, ns.timeout)
    if v == "report":
        return _report(repo, ns.since, ns.json)
    if v == "inbox":
        return _inbox(repo, ns.json)
    if v == "pause":
        return _pause(repo, ns.drain)
    if v == "resume":
        return _resume(repo, ns.item)
    if v == "slots":
        return _slots(repo, ns.n)
    if v == "prioritize":
        return _prioritize(repo, ns.item)
    if v == "skip":
        return _skip(repo, ns.item, ns.reason)
    return _land(repo, ns.unit)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
