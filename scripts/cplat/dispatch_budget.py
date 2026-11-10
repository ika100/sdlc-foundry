"""Spec 167: the dispatcher's daily token budget (design.md "Budget").

  unit_tokens(unit, result) -> int | None   tokens of one unit so far (running) or in the end; None = unknown usage
  book(slug, units) -> Usage                the growth of each unit's tokens goes to today's ledger
  book_agent(slug, tokens) -> int           an agent call of the dispatcher; missing usage books AGENT_CEILING
  reached(usage, policy) -> bool            today's usage is at or above `budget.tokens_per_day`
  history_hint(slug, days=7) -> [{day, tokens}]   the daily usage of the last days, for `plan` without a limit
  budget_need(slug, usage, policy, running) -> dict | None   the one `budget` need of the day

The day is the local calendar day (`dispatch_state.today()`). The ledger in `state.json` is
`ledger[day] = {"units": {unit: tokens}, "agent": tokens}` and `counted[unit]` the tokens of a unit already booked; two more
keys belong to this module: `unknown[unit]` (the day a unit's usage was first found unknown, so it blocks starts only that
day) and `budget_since[day]` (when the day's limit was first reached). `book` is called with every unit file of the repo
before a unit is finished and its worktree removed, so the last growth of a unit is booked.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import dispatch_state as ds

AGENT_CEILING = 200_000          # tokens booked for an agent call whose answer has no usage (bounded by --max-turns 8)
TOKEN_KEYS = ("input", "output", "cache_read", "cache_write")
PEEK_SECONDS = 3.0
NEED_COMMAND = "raise budget.tokens_per_day in .platform/dispatch.yml (starts continue after midnight)"


@dataclass
class Usage:
    day: str
    used: int
    unknown: list[str] = field(default_factory=list)


# ---------------- tokens of one unit ----------------

def _sum(section: dict | None) -> int | None:
    """Tokens of a `usage` section: 0 without a section (no session), None when it is incomplete or has no totals."""
    if section is None:
        return 0
    totals = section.get("totals") if isinstance(section, dict) else None
    if not totals or section.get("incomplete"):
        return None
    try:
        return int(sum(float(totals.get(k) or 0) for k in TOKEN_KEYS))
    except (TypeError, ValueError):
        return None


def _record_usage(run_id: str, records: list[dict]) -> tuple[bool, dict | None]:
    """(found, usage section) of the finished record of `run_id` among `records`."""
    for rec in records:
        if rec.get("run_id") == run_id:
            usage = rec.get("usage")
            return True, usage if isinstance(usage, dict) else None
    return False, None


def _buffer() -> list[dict]:
    import runs
    return runs._safe_buffer()


def _store_records(days: int) -> list[dict]:
    """The records of the run store of the last `days` days; [] when there is no store or it cannot be read."""
    try:
        import runlist
        info, records = runlist._store(days)
        return records if info.get("state") == "ok" else []
    except Exception:  # noqa: BLE001
        return []


def _peek(run_id: str) -> int | None:
    """The tokens of a headless run that has not finished: its active record, else its finished record, else 0."""
    import runs
    import runs_usage
    rec = runs.active(run_id)
    if rec is None:
        found, usage = _record_usage(run_id, _buffer())
        return _sum(usage) if found else 0
    now = runs.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        section = runs_usage.for_run(rec, ended_at=now, budget_s=PEEK_SECONDS, peek=True)
    except Exception:  # noqa: BLE001
        return None
    return _sum(section)       # None section: no session registered yet, 0 tokens so far


def unit_tokens(unit: dict, result: dict | None) -> int | None:
    """Tokens of a unit: running (no end record in the result file) the peek at the headless run, no session yet = 0; ended the
    result's `tokens`, else the unit file's, else the `usage` of the headless record in the buffer or store. None = unknown."""
    if not result or not result.get("ended_at"):
        run_id = (result or {}).get("run_id")
        return _peek(run_id) if run_id else 0
    for known in (result.get("tokens"), unit.get("tokens")):
        if isinstance(known, int) and not isinstance(known, bool):
            return known
    run_id = result.get("run_id")
    if not run_id:
        return None
    found, usage = _record_usage(run_id, _buffer())
    if not found:
        found, usage = _record_usage(run_id, _store_records(2))
    return _sum(usage) if found else None


# ---------------- the ledger ----------------

def _day_entry(st: dict, day: str) -> dict:
    entry = st["ledger"].setdefault(day, {})
    if not isinstance(entry.get("units"), dict):
        entry["units"] = {}
    entry["agent"] = int(entry.get("agent") or 0)
    return entry


def _used(entry: dict) -> int:
    return sum(int(v or 0) for v in entry["units"].values()) + entry["agent"]


def book(slug: str, units: list[dict]) -> Usage:
    """Book the growth of each unit's tokens to today and return today's usage and the units whose usage is unknown today."""
    day = ds.today()
    tokens: dict[str, int | None] = {}
    for unit in units:
        if not unit.get("unit"):
            continue
        result = ds.read_result(unit["worktree"]) if unit.get("worktree") else None
        tokens[unit["unit"]] = unit_tokens(unit, result)
    out = Usage(day, 0)

    def go(st: dict) -> None:
        entry = _day_entry(st, day)
        marks = st.setdefault("unknown", {})
        for name in [n for n in marks if n not in tokens]:
            del marks[name]
        for name, n in tokens.items():
            if n is None:
                if marks.setdefault(name, day) == day:       # unknown blocks starts only on the day it was found
                    out.unknown.append(name)
                continue
            marks.pop(name, None)
            counted = int(st["counted"].get(name) or 0)
            if n > counted:
                entry["units"][name] = int(entry["units"].get(name) or 0) + n - counted
                st["counted"][name] = n
        out.used = _used(entry)
    ds.update(slug, go)
    return out


def book_agent(slug: str, tokens: int | None) -> int:
    """Book the tokens of one agent call to today (AGENT_CEILING when its answer had no usage); returns what was booked."""
    booked = int(tokens) if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0 else AGENT_CEILING

    def go(st: dict) -> None:
        entry = _day_entry(st, ds.today())
        entry["agent"] += booked
    ds.update(slug, go)
    return booked


def usage_today(slug: str) -> Usage:
    """Today's booked usage without booking anything (the units whose usage is unknown are not known here: use `book`)."""
    day = ds.today()
    entry = ds.load(slug)["ledger"].get(day) or {}
    units = entry.get("units") if isinstance(entry.get("units"), dict) else {}
    return Usage(day, sum(int(v or 0) for v in units.values()) + int(entry.get("agent") or 0))


def limit_of(policy) -> int | None:
    value = policy.values.get("budget", {}).get("tokens_per_day")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def reached(usage: Usage, policy) -> bool:
    """True once today's usage is at or above the daily limit (never without a limit)."""
    limit = limit_of(policy)
    return limit is not None and usage.used >= limit


# ---------------- the 7-day hint of `plan` ----------------

def _local_day(started_at: object) -> str | None:
    try:
        when = dt.datetime.strptime(str(started_at), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return when.astimezone().strftime("%Y-%m-%d")


def history_hint(slug: str, days: int = 7) -> list[dict]:
    """`[{day, tokens}]`, the last `days` days oldest first: the tokens of the top-level run records (no `parent`) of this repo
    by local start day, from the buffer and the store. A day that cannot be read (an incomplete usage, a store that
    cannot be reached) has `tokens` None."""
    today = ds.now().date()
    wanted = [(today - dt.timedelta(days=n)).isoformat() for n in range(days - 1, -1, -1)]
    totals: dict[str, int | None] = {d: 0 for d in wanted}
    records: dict[str, dict] = {}
    store_ok = True
    try:
        import runlist
        import runs
        info, stored = runlist._store(days + 1)
        if info.get("state") in ("unreachable", "public"):
            store_ok = False
        for rec in stored:
            if rec.get("run_id"):
                records[rec["run_id"]] = rec
        for rec in runs._safe_buffer():
            if rec.get("run_id") and not rec.get("followup"):
                records[rec["run_id"]] = rec
    except Exception:  # noqa: BLE001
        store_ok = False
    if not store_ok:
        return [{"day": d, "tokens": None} for d in wanted]
    for rec in records.values():
        if rec.get("parent") or rec.get("repo") != slug:
            continue
        day = _local_day(rec.get("started_at"))
        if day not in totals or totals[day] is None:
            continue
        n = _sum(rec.get("usage") if isinstance(rec.get("usage"), dict) else None)
        totals[day] = None if n is None else totals[day] + n
    return [{"day": d, "tokens": totals[d]} for d in wanted]


# ---------------- the need ----------------

def _since(slug: str, day: str) -> str:
    """When the day's limit was first reached (kept, so the need keeps its `since` all day)."""
    found: dict[str, str] = {}

    def go(st: dict) -> None:
        marks = st.setdefault("budget_since", {})
        found["at"] = marks.setdefault(day, ds.now().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    ds.update(slug, go)
    return found["at"]


def budget_need(slug: str, usage: Usage, policy, running: list[str]) -> dict | None:
    """The `budget` item of the needs file for today, None while the limit is not reached (the need is resolved then)."""
    limit = limit_of(policy)
    if limit is None or usage.used < limit:
        return None
    return {"id": f"budget:{slug}:{usage.day}", "kind": "budget", "stage": "Build",
            "object": {"type": "dispatch", "repo": slug, "spec": None, "run_id": None, "issue": None, "component": None,
                       "version": None, "pr": None, "url": None},
            "since": _since(slug, usage.day),
            "reason": f"daily token budget reached: {usage.used} of {limit} tokens",
            "command": NEED_COMMAND, "cwd_repo": slug,
            "consequence": {"used": usage.used, "limit": limit, "running": list(running)}, "way_back": None}


__all__ = ["AGENT_CEILING", "Usage", "book", "book_agent", "budget_need", "history_hint", "limit_of", "reached", "unit_tokens",
           "usage_today"]
