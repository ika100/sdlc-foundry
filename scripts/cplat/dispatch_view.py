"""Spec 167: the documents and the text of `cplat dispatch plan|status|report|wait` (design.md "Commands and output").

  status_doc(repo, slug, policy) -> dict          the `status --json` document, from the state, unit files, processes and usage
  report_doc(slug, since_days=7) -> dict          `{"schema": 1, "days": [...]}`, newest day first
  wait_result(slug, timeout) -> (code, lines)     IDLE (0) / ESCALATED or RED (1) / TIMEOUT (2); marks the events it reports seen
  policy_doc / tokens_doc / starts_doc / slots_doc / plan_doc    the parts of `plan --json` (plan_doc puts them together)
  Spec 210: plan_doc and status_doc add `plan`, `cost`, `hints` and `warnings` from `dispatch_gate.gate`; `starts` carries its text
  render_plan / render_status / render_report     the text; thousands separators only here, never in JSON

`cplat dispatch inbox` is `needs.render` and needs nothing here. This module reads local files only (state.json, the unit files, the
process table through `dispatch_units.alive`); it writes only when `wait_result` marks events seen. The limit of `tokens_doc` goes
through today's raise (spec 193): `raised` says so and the text adds ` (raised for today)`.
"""
from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from pathlib import Path

import dispatch_budget
import dispatch_gate
import dispatch_pace
import dispatch_platform
import dispatch_policy
import dispatch_state as ds
import dispatch_units
import release_hold
import run_slot
import units as unitsmod

SCHEMA = 1
WAIT_EVENTS = ("escalated", "red", "stuck")      # a stuck unit is an escalated one that also needs the user: a wait must not miss it
POLL = 2.0


def _n(value: int | None) -> str:
    return "?" if value is None else f"{value:,}"


RAISED = " (raised for today)"          # after the limit when today's raise holds (spec 193)


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


def _unknown(st: dict, key: str = "unknown") -> list[str]:
    """The units whose tokens (`unknown`) or USD (`unknown_usd`) are unknown today (`dispatch_budget.book` marks them in the state)."""
    day = ds.today()
    return sorted(unit for unit, found in (st.get(key) or {}).items() if found == day)


def tokens_doc(slug: str, policy, st: dict | None = None) -> dict:
    st = st or ds.load(slug)
    usage = dispatch_budget.usage_today(slug)
    limit = dispatch_budget.limit_of(policy, slug)
    return {"day": usage.day, "used": usage.used, "limit": limit, "raised": limit != dispatch_budget.policy_limit(policy),
            "unknown": _unknown(st)}


def _gate(slug: str, policy, st: dict, gate: dispatch_gate.Gate | None) -> dispatch_gate.Gate:
    if gate:
        return gate
    usage = dispatch_budget.usage_today(slug)
    usage.unknown, usage.unknown_usd = _unknown(st), _unknown(st, "unknown_usd")
    return dispatch_gate.gate(slug, policy, st, usage)


def starts_doc(slug: str, policy, st: dict | None = None, gate: dispatch_gate.Gate | None = None) -> dict:
    """`{"allowed", "why_not", "text"}` of the gate: paused, drain, the plan, the USD and token caps, usage unknown (in that order)."""
    g = _gate(slug, policy, st or ds.load(slug), gate)
    return {"allowed": g.why_not is None, "why_not": g.why_not, "text": g.text}


def budget_docs(g: dispatch_gate.Gate) -> dict:
    """The keys `plan` and `status` share: `plan` (null in mode cost), `cost`, `hints`, `warnings`."""
    return {"plan": g.plan, "cost": g.cost, "hints": list(g.hints), "warnings": list(g.warnings)}


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
    units = _running(slug)
    used = dispatch_units.occupied(units, total) + len(manual)
    return {"total": total, "running": len(units) + len(manual), "free": max(total - used, 0), "manual": manual}


def plan_doc(repo: Path | str, slug: str, policy, candidates: list[dict], *, read_at: str | None = None,
             unavailable: list[dict] | None = None, gate: dispatch_gate.Gate | None = None) -> dict:
    """The whole `plan --json` document from the candidate rows of the evaluation (design.md)."""
    st = ds.load(slug)
    g = _gate(slug, policy, st, gate)
    return {"schema": SCHEMA, "repo": slug, "read_at": read_at or ds.stamp(), "policy": policy_doc(slug, policy),
            "tokens": tokens_doc(slug, policy, st), "starts": starts_doc(slug, policy, st, g), **budget_docs(g),
            "slots": slots_doc(slug, policy, st), "candidates": candidates, "unavailable": unavailable or []}


# ---------------- status ----------------

def _phase(unit: dict) -> str:
    status = str(unit.get("status") or "running")
    if unit.get("kind") == "ship" and status not in ("paused", "landing"):
        phase = (dispatch_units._ship_state(unit.get("worktree") or "") or {}).get("phase")
        if phase and phase != "done":
            return str(phase)
    return status


def _paused_at(unit: dict) -> dict:
    """The phase a paused unit stands in (the ship phase, else the next open unit) and the commit of its last done unit."""
    wt = unit.get("worktree") or ""
    phase = (dispatch_units._ship_state(wt) or {}).get("phase") if wt else None
    try:
        rows = unitsmod.rows(Path(wt)) if wt else []
    except Exception:  # noqa: BLE001  (a broken units file must not break status)
        rows = []
    if not phase or phase == "done":
        phase = next((r["id"] for r in rows if r["status"] != "done"), None)
    checkpoint = next((r["commit"] for r in reversed(rows) if r["status"] == "done" and r.get("commit")), None)
    return {"phase": phase, "checkpoint": checkpoint}


def _escalated_today(slug: str) -> list[dict]:
    day = ds.today()
    out = []
    for u in sorted(ds.all_units(slug), key=lambda u: str(u.get("ended_at") or "")):
        if u.get("status") not in ("escalated", "stuck") or str(u.get("ended_at") or "")[:10] != day:
            continue
        reason, cause = str(u.get("reason") or ""), u.get("cause")
        label = "escalated: looping" if reason.startswith("looping:") else f"escalated: {cause or 'unknown'}"
        out.append({"unit": u.get("unit"), "item": u.get("item"), "kind": u.get("kind"), "label": label, "cause": cause,
                    "reason": reason, "ended_at": u.get("ended_at"), "log": u.get("log")})
    return out


def status_doc(repo: Path | str, slug: str, policy, gate: dispatch_gate.Gate | None = None) -> dict:
    st = ds.load(slug)
    g = _gate(slug, policy, st, gate)
    counted = st.get("counted") or {}
    units = sorted(_running(slug), key=lambda u: (int(u.get("slot") or 0), str(u.get("unit"))))
    rows = [{"slot": u.get("slot"), "unit": u.get("unit"), "item": u.get("item"), "kind": u.get("kind"), "mode": u.get("mode"),
             "phase": _phase(u), "since": u.get("started_at"), "tokens": counted.get(u.get("unit")), "pid": u.get("pid"),
             "log": u.get("log"), "pr": u.get("pr"),
             **({"paused_at": _paused_at(u)} if _phase(u) == "paused" else {})} for u in units]
    cycle = st.get("last_cycle") or {}
    running = ds.loop_alive(slug)
    return {"schema": SCHEMA, "repo": slug, "loop": {"running": running, "pid": ds.loop_pid(slug) if running else None},
            "paused": st["steering"].get("paused"),
            "slots": {"total": int(st["steering"].get("slots") or policy.values["slots"]), "units": rows,
                      "manual": manual_rows(slug)},
            "queue": [dict(q) for q in cycle.get("queue") or []], "held": [dict(h) for h in cycle.get("held") or []],
            "escalated": _escalated_today(slug), "tokens": tokens_doc(slug, policy, st), "last_cycle": cycle.get("at"),
            "release_hold": release_hold.view(slug), "platform": dispatch_platform.state(repo), **budget_docs(g)}


def _hold_line(hold: dict) -> str:
    """Spec 198: `release hold: <version> since <time>`, with the stop and its expiry when the release stopped."""
    line = f"release hold: {hold['version']} since {release_hold.hhmm(hold['since'])}"
    if hold["state"] != "running":
        line += f", {hold['state']}, expires {release_hold.hhmm(hold['expires'])}"
    return line


def _clock(iso: object, now: dt.datetime) -> str:
    try:
        return dispatch_pace.fmt_when(dt.datetime.fromisoformat(str(iso)), now)
    except ValueError:
        return "--:--"


def _age(p: dict, now: dt.datetime) -> str:
    if p["source"] == "limit":
        return f"usage limit until {_clock(p.get('limit_until'), now)}"
    try:
        minutes = max(int((now - dt.datetime.fromisoformat(str(p["read_at"]))).total_seconds() // 60), 0)
    except (TypeError, ValueError):
        return "no reading"
    return f"estimate from a reading {minutes} min old" if p["source"] == "estimate" else f"reading {minutes} min old"


def _window(name: str, w: dict, extra: list[str], now: dt.datetime) -> str:
    used = "?" if w["used"] is None else f"{dispatch_pace.fmt_pct(w['used'])} %"
    if w.get("resets_at"):
        extra = [*extra, f"resets {_clock(w['resets_at'], now)}"]
    return f"{name} {used} ({', '.join(extra)})"


def plan_line(p: dict, now: dt.datetime | None = None) -> str:
    """`plan usage: 5h 83 % (stop 80 %, resets 15:45) · week 41 % (pace 46 %, target 92 %, resets Mon 00:00) · reading 4 min old`."""
    now = ds.now() if now is None else now
    if p["source"] == "unknown":
        return "plan usage: unknown (install the sensor and open an interactive session)"
    five, week, pct = p["five_hour"], p["seven_day"], dispatch_pace.fmt_pct
    stop, target = pct(five["stop"]), pct(week["target"])
    pace = [] if week.get("pace") is None else [f"pace {pct(week['pace'])} %"]
    return (f"plan usage: {_window('5h', five, [f'stop {stop} %'], now)} · "
            f"{_window('week', week, [*pace, f'target {target} %'], now)} · {_age(p, now)}")


def cost_line(c: dict) -> str:
    """`cost today: $1.20 of $5.00 · this month: $30.40 of $100.00` (no month part without a monthly limit)."""
    line = f"cost today: {dispatch_gate.usd(c['used_usd'])}"
    line += f" of {dispatch_gate.usd(c['limit_usd'])}" if c["limit_usd"] is not None else " (no USD limit set)"
    if c["month_limit_usd"] is not None:
        line += f" · this month: {dispatch_gate.usd(c['month_used_usd'])} of {dispatch_gate.usd(c['month_limit_usd'])}"
    return line


def _budget_lines(doc: dict) -> list[str]:
    """The plan line, the cost line (mode cost or any USD cap), then each warning and each hint."""
    cost = doc["cost"]
    lines = [plan_line(doc["plan"])] if doc.get("plan") else []
    if not doc.get("plan") or cost["limit_usd"] is not None or cost["month_limit_usd"] is not None:
        lines.append(cost_line(cost))
    return lines + list(doc.get("warnings") or []) + list(doc.get("hints") or [])


def _held_text(h: dict) -> str:
    """`held: <detail>` for a budget hold, `held: filler only` for a filler-only candidate, else `<reason> (<detail>)`."""
    if h.get("reason") == "budget":
        return f"held: {h.get('detail')}"
    if h.get("reason") == "filler only":
        return "held: filler only"
    return f"{h.get('reason')}" + (f" ({h['detail']})" if h.get("detail") else "")


def _slots_line(slots: dict) -> str:
    """`slots: 2 of 3 building, 3 landing` when a unit lands (#1033), else `slots: 2 of 3 in use`."""
    landing = sum(1 for u in slots["units"] if u["phase"] in ("landing", "land"))
    if not landing:
        return f"slots: {len(slots['units']) + len(slots['manual'])} of {slots['total']} in use"
    building = len(slots["units"]) - landing + len(slots["manual"])
    return f"slots: {building} of {slots['total']} building, {landing} landing"


def render_status(doc: dict) -> str:
    loop = doc["loop"]
    head = f"dispatcher: {'running (pid ' + str(loop['pid']) + ')' if loop['running'] else 'not running'}"
    if doc["paused"]:
        head += f"  [{doc['paused']}]"
    hold = doc.get("release_hold")
    lines = [head, *([_hold_line(hold)] if hold else []), _slots_line(doc["slots"])]
    for u in doc["slots"]["units"]:
        pr = f"  {u['pr']}" if u.get("pr") else ""
        phase = u["phase"]
        if u.get("paused_at"):
            phase = f"paused (phase {u['paused_at']['phase']}, checkpoint {(u['paused_at']['checkpoint'] or '-')[:7]})"
        lines.append(f"  slot {u['slot']}  {u['unit']}  {u['item']}  {u['kind']}  {u['mode']}  {phase}  since {_hhmm(u['since'])}"
                     f"  tokens {_n(u['tokens'])}  pid {u['pid']}  log: {u['log']}{pr}")
    lines += [_held_line(m) for m in doc["slots"]["manual"]]
    lines.append(f"queue ({len(doc['queue'])}):")
    lines += [f"  {q.get('item')}  {q.get('kind')}  {q.get('mode')}" for q in doc["queue"]]
    lines.append(f"held ({len(doc['held'])}):")
    lines += [f"  {h.get('item')}  {_held_text(h)}" for h in doc["held"]]
    escalated = doc.get("escalated") or []
    lines.append(f"escalated today ({len(escalated)}):")
    lines += [f"  {e['unit']}  {e['item']}  {e['label']}  {_one_line(e['reason'])}" for e in escalated]
    lines += _budget_lines(doc)
    t = doc["tokens"]
    lines.append(f"tokens today ({t['day']}): {_n(t['used'])} of {_n(t['limit']) if t['limit'] is not None else 'no limit set'}"
                 + (RAISED if t.get("raised") else ""))
    if t["unknown"]:
        lines.append("usage unknown: " + ", ".join(t["unknown"]))
    lines.append(f"last cycle: {doc['last_cycle'] or 'never'}")
    if doc.get("platform"):
        lines.append(dispatch_platform.line(doc["platform"]))
    return "\n".join(lines)


# ---------------- plan (text) ----------------

def _flat(values: dict) -> list[tuple[str, object]]:
    """The leaf keys of the policy in file order (`budget.per_unit` is one leaf)."""
    out: list[tuple[str, object]] = []
    for key, value in values.items():
        if key in ("ready", "gates", "guard"):
            out += [(f"{key}.{k}", v) for k, v in value.items()]
        elif key == "budget":
            out += [(f"budget.{k}", value.get(k)) for k in ("mode", "usd_per_day", "usd_per_month", "tokens_per_day", "per_unit")]
            out += [(f"budget.plan.{k}", v) for k, v in (value.get("plan") or {}).items()]
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
    return " ".join(f"{h['day']} {'$?' if h.get('usd') is None else dispatch_gate.usd(h['usd'])}" for h in hint)


def render_plan(doc: dict) -> str:
    pol = doc["policy"]
    lines = [f"policy: {pol['file']}" if pol["file"] else f"policy: defaults (no {dispatch_policy.FILE})"]
    for key, value in _flat(pol["values"]):
        if key in pol["unset"]:
            lines.append(f"  {key}: unset (required by start and resume in mode cost) — last 7 days: {_hint(pol.get('usage_hint') or [])}")
            continue
        if value is None and key.startswith("budget."):
            # a daily USD limit is the way forward, so the deprecation note is for the policies that still lack it
            deprecated = key == dispatch_policy.TOKENS_KEY and "budget.usd_per_day" in pol["unset"]
            lines.append(f"  {key}: unset" + (" (deprecated)" if deprecated else ""))
            continue
        lines.append(f"  {key}: {_value(value)}" + (" (default)" if key in pol["defaulted"] else ""))
    t = doc["tokens"]
    lines += _budget_lines(doc)
    if (doc.get("plan") or {}).get("filler"):
        lines.append("filler: true")
    lines.append(f"tokens today: {_n(t['used'])} of {_n(t['limit']) if t['limit'] is not None else 'no limit set'}"
                 + (RAISED if t.get("raised") else ""))
    if t.get("unknown"):
        lines.append("usage unknown: " + ", ".join(t["unknown"]))
    if doc["starts"].get("text"):
        lines.append(f"no starts: {doc['starts']['text']}")
    lines += [_held_line(m) for m in doc["slots"]["manual"]]
    lines.append(f"candidates ({len(doc['candidates'])}):")
    for c in doc["candidates"]:
        if c["verdict"] == "ready":
            verdict = "ready"
        elif c.get("reason") == "skipped":
            verdict = f"held: skipped: {c['detail']}" if c.get("detail") else "held: skipped"
        elif c.get("reason") in ("budget", "filler only"):
            verdict = _held_text(c)
        else:
            verdict = f"held: {c.get('reason')}" + (f" ({c['detail']})" if c.get("detail") else "")
        slot = f"slot {c['slot']}" + (" (filler)" if c.get("filler") else "") if c.get("slot") else ("queued" if c["verdict"] == "ready" else "-")
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


__all__ = ["budget_docs", "check", "cost_line", "no_starts_line", "plan_doc", "plan_line", "policy_doc", "render_plan", "render_report", "render_status", "report_doc",
           "slots_doc", "starts_doc", "status_doc", "tokens_doc", "wait_result"]
