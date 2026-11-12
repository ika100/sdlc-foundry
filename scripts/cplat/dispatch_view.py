"""Spec 167: the documents and the text of `cplat dispatch plan|status|report|wait` (design.md "Commands and output").

  status_doc(repo, slug, policy) -> dict          the `status --json` document, from the state, unit files, processes and usage
  report_doc(slug, since_days=7) -> dict          `{"schema": 1, "days": [...]}`, newest day first
  wait_result(slug, timeout) -> (code, lines)     IDLE (0) / ESCALATED or RED (1) / TIMEOUT (2); marks the events it reports seen
  policy_doc / tokens_doc / starts_doc / slots_doc / plan_doc    the parts of `plan --json` (plan_doc puts them together)
  render_plan / render_status / render_report     the text; thousands separators only here, never in JSON

`cplat dispatch inbox` is `needs.render` and needs nothing here. This module reads local files only (state.json, the unit files, the
process table through `dispatch_units.alive`); it writes only when `wait_result` marks events seen.
"""
from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from pathlib import Path

import dispatch_budget
import dispatch_policy
import dispatch_state as ds
import dispatch_units
import run_slot

SCHEMA = 1
WAIT_EVENTS = ("escalated", "red", "stuck")      # a stuck unit is an escalated one that also needs the user: a wait must not miss it
POLL = 2.0


def _n(value: int | None) -> str:
    return "?" if value is None else f"{value:,}"


def _one_line(text: object, limit: int = 300) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _hhmm(iso: object) -> str:
    return str(iso)[11:16] if iso and len(str(iso)) >= 16 else "--:--"


# ---------------- the parts of the documents ----------------

def policy_doc(slug: str, policy: dispatch_policy.Policy) -> dict:
    """`plan --json` `policy`: the file (repo-relative, null without one), the values, the defaulted and unset keys, the 7-day hint."""
    return {"file": dispatch_policy.FILE if policy.file else None, "values": policy.values, "defaulted": list(policy.defaulted),
            "unset": list(policy.unset), "usage_hint": dispatch_budget.history_hint(slug)}


def _unknown(st: dict) -> list[str]:
    """The units whose usage is unknown today (`dispatch_budget.book` marks them in the state)."""
    day = ds.today()
    return sorted(unit for unit, found in (st.get("unknown") or {}).items() if found == day)


def tokens_doc(slug: str, policy, st: dict | None = None) -> dict:
    st = st or ds.load(slug)
    usage = dispatch_budget.usage_today(slug)
    return {"day": usage.day, "used": usage.used, "limit": dispatch_budget.limit_of(policy), "unknown": _unknown(st)}


def starts_doc(slug: str, policy, st: dict | None = None) -> dict:
    """`{"allowed", "why_not"}`: paused, drain, daily budget reached or usage unknown (in that order)."""
    st = st or ds.load(slug)
    paused = st["steering"].get("paused")
    usage = dispatch_budget.usage_today(slug)
    if paused in ("pause", "drain"):
        why = paused
    elif dispatch_budget.reached(usage, policy):
        why = "daily budget reached"
    elif _unknown(st):
        why = "usage unknown"
    else:
        why = None
    return {"allowed": why is None, "why_not": why}


def no_starts_line(why: str | None, unknown: list[str] | None = None) -> str | None:
    """The text line `no starts: ...` of `start` for a `why_not` (the unit names follow `usage unknown`)."""
    if not why:
        return None
    if why == "usage unknown" and unknown:
        return f"no starts: usage unknown: {', '.join(unknown)}"
    return f"no starts: {why}"


def _running(slug: str) -> list[dict]:
    return [u for u in ds.all_units(slug) if u.get("status") not in dispatch_units.ENDED]


def manual_rows(slug: str) -> list[dict]:
    """The slots a manual `cplat headless` run holds (a holder with a unit is a dispatcher unit, counted by its unit file)."""
    return [{"command": h.command, "pid": h.pid, "since": h.since, "checkout": h.checkout}
            for h in run_slot.holders(slug) if h.unit is None]


def _held_line(row: dict) -> str:
    return f"  held by {row['command']} (manual)  pid {row['pid']}  since {row['since']}  {row['checkout']}"


def slots_doc(slug: str, policy, st: dict | None = None) -> dict:
    st = st or ds.load(slug)
    total = int(st["steering"].get("slots") or policy.values["slots"])
    manual = manual_rows(slug)
    running = len(_running(slug)) + len(manual)
    return {"total": total, "running": running, "free": max(total - running, 0), "manual": manual}


def plan_doc(repo: Path | str, slug: str, policy, candidates: list[dict], *, read_at: str | None = None,
             unavailable: list[dict] | None = None) -> dict:
    """The whole `plan --json` document from the candidate rows of the evaluation (design.md)."""
    st = ds.load(slug)
    return {"schema": SCHEMA, "repo": slug, "read_at": read_at or ds.stamp(), "policy": policy_doc(slug, policy),
            "tokens": tokens_doc(slug, policy, st), "starts": starts_doc(slug, policy, st), "slots": slots_doc(slug, policy, st),
            "candidates": candidates, "unavailable": unavailable or []}


# ---------------- status ----------------

def _phase(unit: dict) -> str:
    status = str(unit.get("status") or "running")
    if unit.get("kind") == "ship" and status not in ("paused", "landing"):
        phase = (dispatch_units._ship_state(unit.get("worktree") or "") or {}).get("phase")
        if phase and phase != "done":
            return str(phase)
    return status


def status_doc(repo: Path | str, slug: str, policy) -> dict:
    st = ds.load(slug)
    counted = st.get("counted") or {}
    units = sorted(_running(slug), key=lambda u: (int(u.get("slot") or 0), str(u.get("unit"))))
    rows = [{"slot": u.get("slot"), "unit": u.get("unit"), "item": u.get("item"), "kind": u.get("kind"), "mode": u.get("mode"),
             "phase": _phase(u), "since": u.get("started_at"), "tokens": counted.get(u.get("unit")), "pid": u.get("pid"),
             "log": u.get("log"), "pr": u.get("pr")} for u in units]
    cycle = st.get("last_cycle") or {}
    running = ds.loop_alive(slug)
    return {"schema": SCHEMA, "repo": slug, "loop": {"running": running, "pid": ds.loop_pid(slug) if running else None},
            "paused": st["steering"].get("paused"),
            "slots": {"total": int(st["steering"].get("slots") or policy.values["slots"]), "units": rows,
                      "manual": manual_rows(slug)},
            "queue": [dict(q) for q in cycle.get("queue") or []], "held": [dict(h) for h in cycle.get("held") or []],
            "tokens": tokens_doc(slug, policy, st), "last_cycle": cycle.get("at")}


def render_status(doc: dict) -> str:
    loop = doc["loop"]
    head = f"dispatcher: {'running (pid ' + str(loop['pid']) + ')' if loop['running'] else 'not running'}"
    if doc["paused"]:
        head += f"  [{doc['paused']}]"
    lines = [head, f"slots: {len(doc['slots']['units']) + len(doc['slots']['manual'])} of {doc['slots']['total']} in use"]
    for u in doc["slots"]["units"]:
        pr = f"  {u['pr']}" if u.get("pr") else ""
        lines.append(f"  slot {u['slot']}  {u['unit']}  {u['item']}  {u['kind']}  {u['mode']}  {u['phase']}  since {_hhmm(u['since'])}"
                     f"  tokens {_n(u['tokens'])}  pid {u['pid']}  log: {u['log']}{pr}")
    lines += [_held_line(m) for m in doc["slots"]["manual"]]
    lines.append(f"queue ({len(doc['queue'])}):")
    lines += [f"  {q.get('item')}  {q.get('kind')}  {q.get('mode')}" for q in doc["queue"]]
    lines.append(f"held ({len(doc['held'])}):")
    lines += [f"  {h.get('item')}  {h.get('reason')}" + (f" ({h['detail']})" if h.get("detail") else "") for h in doc["held"]]
    t = doc["tokens"]
    lines.append(f"tokens today ({t['day']}): {_n(t['used'])} of {_n(t['limit']) if t['limit'] is not None else 'no limit set'}")
    if t["unknown"]:
        lines.append("usage unknown: " + ", ".join(t["unknown"]))
    lines.append(f"last cycle: {doc['last_cycle'] or 'never'}")
    return "\n".join(lines)


# ---------------- plan (text) ----------------

def _flat(values: dict) -> list[tuple[str, object]]:
    """The leaf keys of the policy in file order (`budget.per_unit` is one leaf)."""
    out: list[tuple[str, object]] = []
    for key, value in values.items():
        if key in ("ready", "gates"):
            out += [(f"{key}.{k}", v) for k, v in value.items()]
        elif key == "budget":
            out += [("budget.tokens_per_day", value.get("tokens_per_day")), ("budget.per_unit", value.get("per_unit"))]
        else:
            out.append((key, value))
    return out


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_value(v)}" for k, v in value.items()) + "}"
    return str(value)


def _hint(hint: list[dict]) -> str:
    return " ".join(f"{h['day']} {_n(h['tokens'])}" for h in hint)


def render_plan(doc: dict) -> str:
    pol = doc["policy"]
    lines = [f"policy: {pol['file']}" if pol["file"] else f"policy: defaults (no {dispatch_policy.FILE})"]
    for key, value in _flat(pol["values"]):
        if key == dispatch_policy.TOKENS_KEY and value is None:
            lines.append(f"  {key}: unset (required by start and resume) — last 7 days: {_hint(pol.get('usage_hint') or [])}")
            continue
        lines.append(f"  {key}: {_value(value)}" + (" (default)" if key in pol["defaulted"] else ""))
    t = doc["tokens"]
    lines.append(f"tokens today: {_n(t['used'])} of {_n(t['limit']) if t['limit'] is not None else 'no limit set'}")
    if t.get("unknown"):
        lines.append("usage unknown: " + ", ".join(t["unknown"]))
    line = no_starts_line(doc["starts"]["why_not"], t.get("unknown"))
    if line:
        lines.append(line)
    lines += [_held_line(m) for m in doc["slots"]["manual"]]
    lines.append(f"candidates ({len(doc['candidates'])}):")
    for c in doc["candidates"]:
        if c["verdict"] == "ready":
            verdict = "ready"
        elif c.get("reason") == "skipped":
            verdict = f"held: skipped: {c['detail']}" if c.get("detail") else "held: skipped"
        else:
            verdict = f"held: {c.get('reason')}" + (f" ({c['detail']})" if c.get("detail") else "")
        slot = f"slot {c['slot']}" if c.get("slot") else ("queued" if c["verdict"] == "ready" else "-")
        lines.append(f"{c['item']}  {c['kind']}  {verdict}  {c.get('mode') or '-'}  {slot}  premise {c.get('premise') or '-'}  {c['title']}")
    for u in doc.get("unavailable") or []:
        lines.append(f"unavailable: {u['source']}: {u['error']}")
    return "\n".join(lines)


# ---------------- report ----------------

def _day_of(entry: dict) -> str:
    return str(entry.get("ended_at") or entry.get("started_at") or "")[:10]


def report_doc(slug: str, since_days: int = 7) -> dict:
    """Per local day (today and the `since_days - 1` days before), newest first; a day with nothing to report is left out."""
    st = ds.load(slug)
    cutoff = (ds.now().date() - dt.timedelta(days=max(since_days, 1) - 1)).isoformat()
    days: dict[str, dict] = {}

    def row(day: str) -> dict:
        return days.setdefault(day, {"day": day, "delivered": [], "escalated": [], "held": [], "tokens": 0})

    for h in st.get("history") or []:
        day = _day_of(h)
        if day < cutoff:
            continue
        if h.get("outcome") == "done":
            row(day)["delivered"].append({"item": h.get("item"), "unit": h.get("unit"), "pr": h.get("pr"), "tokens": h.get("tokens")})
        elif h.get("outcome") in ("escalated", "stuck"):
            row(day)["escalated"].append({"item": h.get("item"), "unit": h.get("unit"), "reason": h.get("reason")})
    for day, held in (st.get("days") or {}).items():
        if day >= cutoff:
            for item, reason in (held.get("held") or {}).items():
                row(day)["held"].append({"item": item, "reason": reason})
    for day, entry in (st.get("ledger") or {}).items():
        if day >= cutoff:
            units = entry.get("units") if isinstance(entry.get("units"), dict) else {}
            tokens = sum(int(v or 0) for v in units.values()) + int(entry.get("agent") or 0)
            if tokens or day in days:
                row(day)["tokens"] = tokens
    return {"schema": SCHEMA, "days": [days[d] for d in sorted(days, reverse=True)]}


def render_report(doc: dict) -> str:
    if not doc["days"]:
        return "nothing to report"
    lines: list[str] = []
    for d in doc["days"]:
        lines.append(f"{d['day']}  delivered {len(d['delivered'])}  escalated {len(d['escalated'])}  held {len(d['held'])}  "
                     f"tokens {_n(d['tokens'])}")
        lines += [f"  delivered {e['item']}  {e['unit']}  {e.get('pr') or '-'}  tokens {_n(e.get('tokens'))}" for e in d["delivered"]]
        lines += [f"  escalated {e['item']}  {e['unit']}: {_one_line(e.get('reason'))}" for e in d["escalated"]]
        lines += [f"  held {e['item']}: {e['reason']}" for e in d["held"]]
    return "\n".join(lines)


# ---------------- wait ----------------

def _event_line(e: dict) -> str:
    reason = _one_line(e.get("reason"))
    if e["kind"] == "red":
        return f"RED: {e.get('unit')} {e.get('item')} {e.get('pr') or '-'}: {reason}"
    return f"ESCALATED: {e.get('unit')} {e.get('item')}: {reason}"


def check(slug: str, timeout: float | None = None) -> tuple[int | None, list[str]]:
    """One look at the state: (code, lines) when `wait` is done, (None, []) while it goes on. `timeout` is None until it ran out."""
    events = ds.events_unseen(slug, WAIT_EVENTS)
    if events:
        for e in events:
            ds.mark_seen(slug, e["seq"])
        return 1, [_event_line(e) for e in events]
    running = _running(slug)
    queued = (ds.load(slug).get("last_cycle") or {}).get("queue") or []
    alone = [] if ds.loop_alive(slug) else ["no dispatcher loop runs for this repo (cplat dispatch start)"]
    if not running and not queued:
        return 0, ["IDLE: no unit runs and nothing ready is queued", *alone]
    if timeout is None:
        return None, []
    lines = [f"TIMEOUT: {len(running)} unit(s) running after {timeout:g}s"]
    lines += [f"  {u['unit']} {u['item']} {_phase(u)} since {_hhmm(u.get('started_at'))}" for u in running]
    return 2, [*lines, *alone]


def wait_result(slug: str, timeout: float = 540, *, sleep: Callable[[float], None] = time.sleep,
                clock: Callable[[], float] = time.monotonic) -> tuple[int, list[str]]:
    """Wait for an unseen escalated/red event (exit 1), for nothing left to do (exit 0) or for `timeout` seconds (exit 2)."""
    deadline = clock() + timeout
    while True:
        code, lines = check(slug)
        if code is not None:
            return code, lines
        left = deadline - clock()
        if left <= 0:
            code, lines = check(slug, timeout)
            return code if code is not None else 2, lines
        sleep(min(POLL, left))


__all__ = ["check", "no_starts_line", "plan_doc", "policy_doc", "render_plan", "render_report", "render_status", "report_doc",
           "slots_doc", "starts_doc", "status_doc", "tokens_doc", "wait_result"]
