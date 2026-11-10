"""Spec 167: one scheduling pass of the dispatcher and its read-only twin for `cplat dispatch plan` (design.md "Units", "Budget").

  run_cycle(repo, policy, *, max_age=0, announce=None) -> CycleResult   observe and act on the units, book tokens, read the backlog,
                                                                      fill the free slots, write the needs, notify
  evaluate(repo, policy, *, max_age=0) -> dict                         the `plan --json` document: the same decisions, no write to
                                                                      GitHub, branches, worktrees or claims

Both share `_schedule`: the ready items in order take the free slots one by one (ship-busy, the premise check of an issue, the mode
check of a spec, then `start`); `evaluate` only records what would happen. Nothing starts and no agent call is made while the
dispatcher is paused or draining, the daily budget is reached or a unit's usage is unknown (`why_not`). Agent tokens are booked
right after each call, so the limit also stops the calls. Everything the cycle remembers is in `state.json` and the unit files.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import dispatch_agent
import dispatch_backlog
import dispatch_budget
import dispatch_notify
import dispatch_ready
import dispatch_state as ds
import dispatch_units as du
import dispatch_view
import spec as specmod
from core import PlatformError

SCHEMA = 1
PAUSED, DRAIN, BUDGET, UNKNOWN = "paused", "drain", "daily budget reached", "usage unknown"

_announced = False        # the `adopted <unit>` lines are printed by the first cycle of a process


@dataclass
class CycleResult:
    lines: list[str] = field(default_factory=list)        # the action lines `cplat dispatch start` prints
    why_not: str | None = None                            # paused | drain | daily budget reached | usage unknown
    started: list[str] = field(default_factory=list)      # the units started in this cycle
    queue: list[dict] = field(default_factory=list)       # ready items without a slot: {item, kind, mode}
    held: list[dict] = field(default_factory=list)        # held items: {item, reason, detail}
    unavailable: dict[str, str] = field(default_factory=dict)


@dataclass
class Entry:
    v: dispatch_ready.Verdict
    mode: str | None = None
    slot: int | None = None
    premise: str | None = None          # holds | resolved | unchecked (issues), None for a spec
    started: bool = False
    closed: bool = False                # an issue the premise check closed as stale


@dataclass
class Schedule:
    entries: list[Entry]
    lines: list[str] = field(default_factory=list)
    why_not: str | None = None
    why_text: str | None = None
    started: list[str] = field(default_factory=list)
    closed: bool = False


def _first(error: object) -> str:
    return (str(error).splitlines() or [""])[0]


# ---------------- slots and the reasons not to start ----------------

def effective_slots(state: dict, policy) -> int:
    """The `slots` override of `cplat dispatch slots`, else the policy's."""
    n = (state.get("steering") or {}).get("slots")
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 1 else int(policy.values["slots"])


def free_numbers(running: list[dict], total: int) -> list[int]:
    """The slot numbers a start can take: the lowest numbers no running unit holds, as many as `total` minus the running units."""
    used = {int(u.get("slot") or 0) for u in running}
    out: list[int] = []
    n = 0
    while len(out) < max(0, total - len(running)):
        n += 1
        if n not in used:
            out.append(n)
    return out


def _why_not(state: dict, usage: dispatch_budget.Usage, policy) -> tuple[str | None, str | None]:
    """(the `why_not` key, the text after `no starts: `)."""
    paused = (state.get("steering") or {}).get("paused")
    if paused == "pause":
        return PAUSED, PAUSED
    if paused == "drain":
        return DRAIN, DRAIN
    if dispatch_budget.reached(usage, policy):
        return BUDGET, BUDGET
    if usage.unknown:
        return UNKNOWN, f"{UNKNOWN}: {', '.join(usage.unknown)}"
    return None, None


def _running(units: list[dict]) -> list[dict]:
    return [u for u in units if u.get("status") not in du.ENDED]


def _reached(slug: str, policy) -> bool:
    return dispatch_budget.reached(dispatch_budget.usage_today(slug), policy)


# ---------------- the candidates ----------------

def _judge(repo: Path, slug: str, policy, snap, state: dict, units: list[dict]):
    """(ready verdicts in the order they take slots, the held verdicts in the order of the candidates)."""
    cands = dispatch_backlog.candidates(snap, policy)
    verdicts = dispatch_ready.judge(cands, snap, state, units, policy, slug=slug, shape=specmod.repo_shape(repo))
    ready = [v for v in verdicts if v.ready]
    ordered = dispatch_ready.order(ready, policy.values["priority"], (state.get("steering") or {}).get("pinned") or [])
    return ordered, [v for v in verdicts if not v.ready]


def _entry(v: dispatch_ready.Verdict) -> Entry:
    fix = v.cand.kind == "fix"
    return Entry(v, mode="single" if fix else None, premise="unchecked" if fix else None)


def _held(v: dispatch_ready.Verdict, reason: str, detail: str | None) -> dispatch_ready.Verdict:
    return replace(v, verdict="held", reason=reason, detail=detail, approve=None)


def _marker_seen(row: dict, state: dict | None = None) -> bool:
    """The issue was closed as stale once and is open again, so it is never closed as stale again. Two sources: the number
    in `state.json` (kept when the dispatcher closes it; survives a removed label) and the stale marker in its comments."""
    if int(row.get("number") or 0) in ((state or {}).get("stale_closed") or []):
        return True
    return any(du.STALE_MARK in str(c.get("body") or "") for c in row.get("comments") or [] if isinstance(c, dict))


# ---------------- the scheduling pass ----------------

def _schedule(repo: Path, slug: str, policy, snap, state: dict, units: list[dict], ordered: list, held: list, usage, *,
              act: bool) -> Schedule:
    """Fill the free slots with the ready items in order. `act` False only records the decisions (`plan`)."""
    sched = Schedule([])
    running = _running(units)
    free = free_numbers(running, effective_slots(state, policy))
    ship_unit = dispatch_ready.ship_busy_unit(units)
    ship_taken: str | None = None
    sched.why_not, sched.why_text = _why_not(state, usage, policy)
    rows = {int(r["number"]): r for r in snap.issues}

    def stop(reason: str) -> None:
        sched.why_not = sched.why_text = reason

    for v in ordered:
        e = _entry(v)
        sched.entries.append(e)
        cand = v.cand
        if cand.kind == "ship" and (ship_unit or ship_taken):
            e.v = dispatch_ready.hold_ship_busy(v, ship_unit or ship_taken)
            continue
        if sched.why_not is None and not free:
            continue                                        # no free slot: it queues
        if sched.why_not is not None:
            continue                                        # nothing starts and no agent is asked
        if cand.kind == "fix":
            row = rows.get(int(cand.number))
            if row is not None and not _marker_seen(row, state):
                res = dispatch_agent.premise(repo, row, snap.main_sha or "")
                dispatch_budget.book_agent(slug, res.get("tokens"))
                e.premise = res["verdict"]
                if res["verdict"] == "resolved" and res.get("evidence"):
                    if act:
                        sched.lines += du.close_stale(repo, slug, int(cand.number), res["evidence"], str(res.get("why") or ""))
                        sched.closed = True
                    else:
                        e.v = dispatch_ready.hold_stale(v, res["evidence"])
                    e.closed = act
                    continue
        else:
            res = dispatch_agent.mode(repo, dispatch_backlog.as_spec(cand.spec))
            dispatch_budget.book_agent(slug, res.get("tokens"))
            e.mode = res["mode"]
        if _reached(slug, policy):
            stop(BUDGET)                                    # the agent call itself reached the limit
            continue
        slot = free[0]
        if act:
            try:
                start = du.start(repo, slug, cand, e.mode or "single", slot, policy)
            except PlatformError as err:
                sched.lines.append(f"could not start {cand.item}: {_first(err)}")
                continue
            sched.lines += start.lines
            if start.held:
                e.v = _held(v, start.held, start.detail)
                continue
            if start.unit is None or start.unit.get("status") in du.ENDED:
                continue                                    # it ended at once (its escalation is in the lines): the slot is free
            e.started = True
            sched.started.append(start.unit["unit"])
        free.pop(0)
        e.slot = slot
        if cand.kind == "ship":
            ship_taken = cand.item
    sched.entries += [_entry(v) for v in held]
    return sched


# ---------------- one cycle ----------------

def _settle_units(repo: Path, slug: str, policy, lines: list[str], needs: list[dict]) -> None:
    """Steering and the ends of units: flags for a pause, resume of paused units first, then observe and act on each unit."""
    state = ds.load(slug)
    paused = (state.get("steering") or {}).get("paused")
    units = du.adopt(repo, slug)
    if paused == "pause":
        du.pause_flags(units)
    else:
        du.clear_flags([u for u in units if u.get("status") in ("starting", "running")])
    order = sorted(units, key=lambda u: 0 if u.get("status") == "paused" else 1)       # paused units come first after `resume`
    for u in order:
        try:
            if u.get("status") == "paused":
                if paused is None:
                    step = du.resume_paused(repo, slug, u, policy)
                else:
                    continue
            else:
                if paused == "pause" and du.observe(repo, slug, u).state == "restart":
                    continue                                # nothing is started again while paused
                step = du.advance(repo, slug, u, policy)
                now = ds.read_unit(u["worktree"]) or u
                if paused is None and now.get("status") == "paused":
                    step.lines += du.resume_paused(repo, slug, now, policy).lines
        except PlatformError as err:
            lines.append(f"error {u.get('unit')}: {_first(err)}")
            continue
        lines += step.lines
        needs += step.needs


def run_cycle(repo: Path | str, policy, *, max_age: int = 0, announce: bool | None = None) -> CycleResult:
    """One scheduling pass. `max_age` is how old (seconds) a cached backlog snapshot may be: 0 reads GitHub again (`--once`); the loop
    passes 300. `announce` prints `adopted <unit> (pid N)` for the live units of a former dispatcher (default: the first cycle of
    this process)."""
    global _announced
    repo = Path(repo)
    slug = ds.slug_of(repo)
    out = CycleResult()
    if announce is None:
        announce = not _announced
    _announced = True
    if announce:
        out.lines += du.adopted_lines(du.adopt(repo, slug))
    prev_read = (ds.load(slug).get("last_cycle") or {}).get("read_at")
    new_needs: list[dict] = []
    _settle_units(repo, slug, policy, out.lines, new_needs)
    usage = dispatch_budget.book(slug, ds.all_units(slug))
    snap = dispatch_backlog.snapshot(repo, slug, max_age=max_age, fetch=True)
    out.unavailable = dict(snap.unavailable)
    out.lines += du.cleanup(repo, slug, snap.read_at)
    units = ds.all_units(slug)
    state = ds.load(slug)
    ordered, held = _judge(repo, slug, policy, snap, state, units)
    sched = _schedule(repo, slug, policy, snap, state, units, ordered, held, usage, act=True)
    out.lines += sched.lines
    out.started = sched.started
    out.why_not = sched.why_not
    if sched.why_text:
        out.lines.append(f"no starts: {sched.why_text}")
    if sched.closed:
        ds.update(slug, lambda st: st.__setitem__("snapshot", {}))      # the closed issue must not come back from the cache
    out.queue = [{"item": e.v.item, "kind": e.v.cand.kind, "mode": e.mode} for e in sched.entries
                 if e.v.ready and not e.started and not e.closed]
    out.held = [{"item": e.v.item, "reason": e.v.reason, "detail": e.v.detail} for e in sched.entries if not e.v.ready]
    final = ds.all_units(slug)
    now_usage = dispatch_budget.usage_today(slug)
    usage = dispatch_budget.Usage(now_usage.day, now_usage.used, usage.unknown)
    _record(slug, snap, final, policy, out)
    running = [u["unit"] for u in _running(final)]
    need = dispatch_budget.budget_need(slug, usage, policy, running)
    fresh = snap.read_at != prev_read and "issues" not in snap.unavailable
    dispatch_notify.write_needs(slug, ([need] if need else []) + new_needs, snap.issues if fresh else None)
    try:
        dispatch_notify.notify_pass(repo, slug)
    except Exception as err:  # noqa: BLE001  a failing notification never stops the dispatcher
        print(f"notify failed: {_first(err)}", file=sys.stderr)
    return out


def _record(slug: str, snap, units: list[dict], policy, out: CycleResult) -> None:
    """`last_cycle` (queue, held, slots) and the day's held items, for `status`, `wait`, `report` and the digest."""
    day = ds.today()
    running = _running(units)

    def go(st: dict) -> None:
        total = effective_slots(st, policy)
        st["last_cycle"] = {"at": ds.stamp(), "read_at": snap.read_at, "queue": out.queue, "held": out.held,
                            "slots": {"total": total, "running": len(running), "free": max(0, total - len(running))}}
        if out.held:
            record = st["days"].setdefault(day, {"held": {}}).setdefault("held", {})
            for h in out.held:
                record[h["item"]] = h["reason"]
    ds.update(slug, go)


# ---------------- the plan ----------------

def _candidate_doc(e: Entry) -> dict:
    v = e.v
    return {"item": v.item, "key": v.key, "kind": v.cand.kind, "title": v.cand.title, "verdict": v.verdict, "reason": v.reason,
            "detail": v.detail, "mode": e.mode, "slot": e.slot, "premise": e.premise, "approve": v.approve}


def evaluate(repo: Path | str, policy, *, max_age: int = 0) -> dict:
    """The document of `cplat dispatch plan --json`. It reads GitHub (a cached snapshot only when younger than `max_age` seconds),
    fetches nothing and writes nothing to GitHub, branches, worktrees or claims; it may make the premise and mode calls of the items
    that would start (cached and booked) and updates the local ledger."""
    repo = Path(repo)
    slug = ds.slug_of(repo)
    units = ds.all_units(slug)
    usage = dispatch_budget.book(slug, units)
    snap = dispatch_backlog.snapshot(repo, slug, max_age=max_age, fetch=False)
    state = ds.load(slug)
    ordered, held = _judge(repo, slug, policy, snap, state, units)
    sched = _schedule(repo, slug, policy, snap, state, units, ordered, held, usage, act=False)
    return dispatch_view.plan_doc(repo, slug, policy, [_candidate_doc(e) for e in sched.entries], read_at=snap.read_at,
                                  unavailable=[{"source": k, "error": v} for k, v in snap.unavailable.items()])


__all__ = ["CycleResult", "Entry", "Schedule", "effective_slots", "evaluate", "free_numbers", "run_cycle"]
