"""cplat dispatch: run the backlog in slots (spec 167).

  cplat dispatch start [--once | --detach]       the loop: claim ready items, run each in its own worktree, land, report
  cplat dispatch build --slots N                 start a build: N slots, a build record, the loop in its own session (spec 193)
  cplat dispatch plan [--json]                   what the next cycle would do (reads, writes nothing to GitHub)
  cplat dispatch status [--json]                 slots, queue, held items, tokens of the day (local reads)
  cplat dispatch wait [--timeout S]              block until an escalation or red check (exit 1), idle (0) or the timeout (2)
  cplat dispatch report [--since D] [--json]     per day: delivered, escalated, held, tokens
  cplat dispatch inbox [--json]                  what needs you in this repo (`cplat needs` in repo scope)
  cplat dispatch budget [--today N | --reset-today]   the day's limit, raised for today only (local state), or back to the policy
  cplat dispatch setup (--show [--json] | --tokens-per-day N)   the policy file from the 7-day hint, landed by a pull request
  cplat dispatch answer <item> --answer TEXT [--question K]   the answer to a stopped unit, written into its spec or issue
  cplat dispatch pause [--drain] | resume [<item>] | slots <N> | prioritize <item> | skip <item> --reason <text>

  cplat dispatch sensor install | remove         record the plan's two usage windows from every interactive session (spec 210)

Every verb takes `--repo DIR` (default `.`). The policy is `.platform/dispatch.yml` (see docs/dispatch.md). `land` is the hidden verb
the dispatcher spawns for a fix unit with an open pull request, `task <unit>` the one it spawns for a filler task (spec 210).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

import dispatch_answer
import dispatch_budget
import dispatch_cycle
import dispatch_items
import dispatch_policy
import dispatch_sensor
import dispatch_setup
import dispatch_state as ds
import dispatch_units as du
import dispatch_view
import needs as needsmod
import waits
from core import PlatformError

DETACH_WAIT = 5.0          # seconds `start --detach` waits for the new loop to hold its lock
TICK = 5.0                # seconds between looks at the units
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


def spawn_loop(repo: Path, log: Path) -> int:   # tests replace this
    """The loop in a new session: stdin closed, output appended to `log`. Returns its pid."""
    return du._detach([sys.executable, str(du.CPLAT), "dispatch", "start", "--repo", str(repo)], repo, dict(os.environ), log)


def _detach(repo: Path) -> int:
    dispatch_policy.load(repo, require_file=True, require_budget=True)
    slug = ds.slug_of(repo)
    if ds.loop_alive(slug):
        _out(f"running: the build loop runs already (pid {ds.loop_pid(slug) or '?'})")
        return 0
    log = ds.base(slug) / "logs" / "loop.log"
    pid = spawn_loop(repo, log)
    end = clock() + DETACH_WAIT
    while not ds.loop_alive(slug):
        if clock() >= end:
            print(f"ERROR: the build loop did not start within {DETACH_WAIT:g} s; see {log}", file=sys.stderr, flush=True)
            return 1
        sleep(0.1)
    _out(f"started: the build loop (pid {ds.loop_pid(slug) or pid}), log {log}")
    return 0


def _build(repo: Path, slots: str) -> int:
    try:
        n = int(slots)
    except ValueError:
        n = 0
    if not 1 <= n <= ds.MAX_SLOTS:
        raise ds.ItemRefused(f"slots {slots} is not allowed (allowed: 1..{ds.MAX_SLOTS})")
    try:
        dispatch_policy.load(repo, require_file=True, require_budget=True)
    except PlatformError as err:
        raise ds.ItemRefused(str(err)) from err
    slug = ds.slug_of(repo)
    ds.set_slots(slug, n)
    ds.resume(slug)
    ds.open_build(slug, n)
    _out(f"slots: {n}")
    _out(f"build started at {ds.now().strftime('%H:%M')}")
    code = _detach(repo)
    if code == 0:
        _out("Undo: cplat dispatch pause --drain")
    return code


def _number(text: str, what: str) -> int:
    try:
        return int(str(text).replace(",", ""))
    except ValueError:
        raise ds.ItemRefused(f"{text} is not a whole number of {what}") from None


def _budget(repo: Path, today: str | None, reset: bool) -> int:
    policy = dispatch_policy.load(repo)
    slug = ds.slug_of(repo)
    day = ds.today()
    base_limit = dispatch_budget.policy_limit(policy)
    if reset:
        ds.reset_today(slug)
        _out(f"budget for {day}: back to {base_limit:,}" if base_limit is not None else f"budget for {day}: back to the policy")
        return 0
    limit = dispatch_budget.limit_of(policy, slug)
    if today is not None:
        if limit is None:
            raise ds.ItemRefused(f"{dispatch_policy.FILE} sets no {dispatch_policy.TOKENS_KEY}: there is no budget to raise")
        n = _number(today, "tokens")
        if n <= limit:
            raise ds.ItemRefused(f"{n:,} is not above today's budget of {limit:,}")
        ds.raise_today(slug, n)
        _out(f"budget for {day}: {n:,} tokens (the policy says {base_limit:,}; back to it at midnight)")
        _out("Undo: cplat dispatch budget --reset-today")
        return 0
    if limit is None:
        _out(f"budget for {day}: none (the policy sets no {dispatch_policy.TOKENS_KEY})")
    elif limit != base_limit:
        _out(f"budget for {day}: {limit:,} tokens (raised for today; the policy says {base_limit:,})")
    else:
        _out(f"budget for {day}: {limit:,} tokens")
    return 0


def _setup(repo: Path, show: bool, as_json: bool, tokens: str | None) -> int:
    slug = ds.slug_of(repo)
    if show:
        n = dispatch_setup.suggest(slug)
        file = dispatch_setup.text(n)
        if as_json:
            _json({"file": file, "tokens_per_day": n, "hint": dispatch_budget.history_hint(slug)})
        else:
            _out(file.rstrip("\n"))
        return 0
    if tokens is None:
        raise ds.ItemRefused("give --show or --tokens-per-day N")
    n = _number(tokens, "tokens")
    if n < 1:
        raise ds.ItemRefused(f"{n} tokens per day is not allowed (at least 1)")
    if (repo / dispatch_policy.FILE).exists():
        raise ds.ItemRefused(f"{dispatch_policy.FILE} exists already: edit it instead (docs/dispatch.md)")
    for line in dispatch_setup.apply(repo, n):
        _out(line)
    return 0


def _answer(repo: Path, item: str, text: str, question: int | None) -> int:
    dispatch_policy.load(repo)
    slug = ds.slug_of(repo)
    found = dispatch_items.resolve(repo, slug, item)
    for line in dispatch_answer.answer(repo, slug, found.key, text, question):
        _out(line)
    return 0


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
    dispatch_policy.load(repo)
    slug = ds.slug_of(repo)

    def body() -> tuple[int, str]:
        code, lines = dispatch_view.wait_result(slug, timeout)
        for line in lines:
            _out(line)
        return code, waits.RESULTS.get(code, "error")

    return waits.record(repo, "dispatch wait", body)


def _report(repo: Path, since: int, as_json: bool) -> int:
    dispatch_policy.load(repo)
    doc = dispatch_view.report_doc(ds.slug_of(repo), since)
    _json(doc) if as_json else _out(dispatch_view.render_report(doc))
    return 0


def _inbox(repo: Path, as_json: bool) -> int:
    dispatch_policy.load(repo)
    doc = needsmod.collect_repo(repo)
    doc = {**doc, "items": [i for i in doc["items"] if i.get("kind") in INBOX_KINDS]}
    _json(doc) if as_json else _out(needsmod.render(doc))
    return 0


# ---------------- steering ----------------

def _pause(repo: Path, drain: bool) -> int:
    dispatch_policy.load(repo)
    mode = ds.pause(ds.slug_of(repo), drain)
    _out("draining: running units finish, nothing new starts" if mode == "drain"
         else "paused: nothing new starts; running units stop at their next stop")
    return 0


def _resume(repo: Path, item: str | None) -> int:
    dispatch_policy.load(repo, require_file=True, require_budget=True)
    slug = ds.slug_of(repo)
    if item:
        found = dispatch_items.resolve(repo, slug, item)
        ds.resume_item(slug, found.key)
        _out(f"resumed: {found.label}")
        for n in _lift_label(repo, slug, found.key):
            _out(f"label removed: #{n}")
        return 0
    ds.resume(slug)
    du.clear_flags(du.adopt(repo, slug))
    _out("resumed: starts continue, paused units restart first")
    return 0


def _lift_label(repo: Path, slug: str, key: str) -> list[int]:
    """Remove `needs-decision` from the open issues of the item that carry it (a fix: its issue; a spec: the issues its unit tracks)."""
    worktree = ds.worktree_path(slug, key)
    unit = ds.read_unit(worktree) if worktree.is_dir() else None
    numbers = [int(key.split("-", 1)[1])] if key.startswith("issue-") else (du._issues_of(unit) if unit else [])
    removed = []
    for n in numbers:
        try:
            doc = json.loads(du.gh(["issue", "view", str(n), "--json", "state,labels"], cwd=repo) or "{}")
        except ValueError:
            continue
        has = any(label.get("name") == du.NEEDS_DECISION for label in doc.get("labels") or [])
        if doc.get("state") == "OPEN" and has and du.gh(["issue", "edit", str(n), "--remove-label", du.NEEDS_DECISION], cwd=repo) is not None:
            removed.append(n)
    return removed


def _slots(repo: Path, n: int) -> int:
    dispatch_policy.load(repo)
    ds.set_slots(ds.slug_of(repo), n)
    _out(f"slots: {n}")
    return 0


def _prioritize(repo: Path, item: str) -> int:
    dispatch_policy.load(repo)
    slug = ds.slug_of(repo)
    found = dispatch_items.resolve(repo, slug, item)
    ds.pin(slug, found.key)
    _out(f"prioritized: {found.label}")
    return 0


def _skip(repo: Path, item: str, reason: str) -> int:
    dispatch_policy.load(repo)
    slug = ds.slug_of(repo)
    found = dispatch_items.resolve(repo, slug, item)
    ds.skip(slug, found.key, reason)
    _out(f"skipped: {found.label} (reason: {reason})")
    return 0


def _sensor(action: str) -> int:
    _out(dispatch_sensor.install() if action == "install" else dispatch_sensor.remove())
    return 0


def _land(repo: Path, unit: str) -> int:
    return du.land(repo, ds.slug_of(repo), unit)


def _task(repo: Path, unit: str) -> int:
    return du.run_task(repo, ds.slug_of(repo), unit)


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

    st = verb("start", "run the dispatcher loop")
    st.add_argument("--once", action="store_true", help="run one cycle and exit")
    st.add_argument("--detach", action="store_true", help="run the loop in its own session and return")
    verb("build", "start a build: slots, a build record and the loop").add_argument("--slots", required=True, metavar="N")
    b = verb("budget", "show the day's token budget, raise it for today or take the raise back")
    b.add_argument("--today", metavar="N", help="raise the limit of today (local state, never the policy file)")
    b.add_argument("--reset-today", action="store_true", help="back to the policy's limit")
    su = verb("setup", "the policy file from the 7-day hint, landed by a pull request", json_flag=True)
    su.add_argument("--show", action="store_true", help="print the file, write nothing")
    su.add_argument("--tokens-per-day", metavar="N", help="write the policy with this budget through a pull request")
    a = verb("answer", "answer the stop of an item")
    a.add_argument("item")
    a.add_argument("--answer", required=True, metavar="TEXT")
    a.add_argument("--question", type=int, metavar="K", help="question K (1-based) of the stop")
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
    verb("sensor", "install or remove the usage status line sensor", json_flag=True).add_argument(
        "action", choices=("install", "remove"))
    lnd = sub.add_parser("land", help=argparse.SUPPRESS)       # hidden: spawned by the dispatcher
    lnd.add_argument("unit")
    lnd.add_argument("--repo", default=".", metavar="DIR")
    tsk = sub.add_parser("task", help=argparse.SUPPRESS)       # hidden: spawned by the dispatcher for a filler task
    tsk.add_argument("unit")
    tsk.add_argument("--repo", default=".", metavar="DIR")
    return p


def main(argv: list[str]) -> int:
    try:
        ns = build_parser().parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    try:
        return _run(ns)
    except ds.ItemRefused as err:
        print(f"ERROR: {err}", file=sys.stderr, flush=True)
        return 2


def _run(ns: argparse.Namespace) -> int:
    repo = Path(ns.repo).resolve()
    v = ns.verb
    if v == "sensor":
        return _sensor(ns.action)
    if v == "start":
        if ns.detach:
            if ns.once:
                raise ds.ItemRefused("--detach and --once cannot be combined")
            return _detach(repo)
        return _start(repo, ns.once)
    if v == "build":
        return _build(repo, ns.slots)
    if v == "budget":
        if ns.today is not None and ns.reset_today:
            raise ds.ItemRefused("--today and --reset-today cannot be combined")
        return _budget(repo, ns.today, ns.reset_today)
    if v == "setup":
        return _setup(repo, ns.show, ns.json, ns.tokens_per_day)
    if v == "answer":
        return _answer(repo, ns.item, ns.answer, ns.question)
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
    if v == "task":
        return _task(repo, ns.unit)
    return _land(repo, ns.unit)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
