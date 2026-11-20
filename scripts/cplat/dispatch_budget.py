"""Spec 167: the dispatcher's daily token budget (design.md "Budget").

  unit_usage(unit, result) -> (tokens|None, usd|None)   tokens and USD of one unit so far (running) or in the end; None = unknown
  unit_tokens(unit, result) -> int | None   the tokens part of `unit_usage`
  book(slug, units) -> Usage                the growth of each unit's tokens and USD goes to today's ledger and the machine tape
  book_agent(slug, tokens, cost_usd=None, model=None) -> int   an agent call: its USD is the reported cost, else priced from the
                                            tokens, else AGENT_CEILING tokens at the model's input price
  reached(usage, policy) -> bool            today's usage is at or above `budget.tokens_per_day`
  history_hint(slug, days=7) -> [{day, tokens, usd}]   the daily usage of the last days, for `plan` without a limit
  budget_need(slug, usage, policy, running) -> dict | None   the one `budget` need of the day

The day is the local calendar day (`dispatch_state.today()`). The ledger in `state.json` is
`ledger[day] = {"units": {unit: tokens}, "agent": tokens, "usd": {unit: usd}, "agent_usd": usd}`; `counted[unit]` and
`counted_usd[unit]` are the tokens and USD of a unit already booked; more keys belong to this module: `unknown[unit]` and
`unknown_usd[unit]` (the day a unit's tokens or USD were first found unknown, so it blocks starts only that day) and
`budget_since[day]` (when the day's limit was first reached). `book` is called with every unit file of the repo
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
    usd: float = 0.0
    month_usd: float = 0.0
    unknown_usd: list[str] = field(default_factory=list)


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


def _is_num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _usd(section: dict | None) -> float | None:
    """USD of a `usage` section: 0 without a section, None when it is incomplete or its cost is not complete."""
    if section is None:
        return 0.0
    totals = section.get("totals") if isinstance(section, dict) else None
    if not totals or section.get("incomplete") or totals.get("cost_complete") is not True:
        return None
    value = totals.get("cost_usd")
    return float(value) if _is_num(value) else None


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


def _peek_section(run_id: str) -> tuple[bool, dict | None]:
    """(readable, usage section) of a headless run that has not finished: its active record, else its finished record, else
    no section (nothing yet). Not readable = the usage is unknown."""
    import runs
    import runs_usage
    rec = runs.active(run_id)
    if rec is None:
        found, usage = _record_usage(run_id, _buffer())
        return True, usage if found else None
    now = runs.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        section = runs_usage.for_run(rec, ended_at=now, budget_s=PEEK_SECONDS, peek=True)
    except Exception:  # noqa: BLE001
        return False, None
    return True, section       # None section: no session registered yet, 0 tokens so far


def unit_usage(unit: dict, result: dict | None) -> tuple[int | None, float | None]:
    """(tokens, USD) of a unit: running (no end record in the result file) the peek at the headless run, no session yet = 0;
    ended the result's `tokens` / `cost_usd`, else the unit file's, else the `usage` of the headless record in the buffer or
    store (its USD only when `cost_complete`). None = unknown."""
    if not result or not result.get("ended_at"):
        run_id = (result or {}).get("run_id")
        if not run_id:
            return 0, 0.0
        readable, section = _peek_section(run_id)
        return (_sum(section), _usd(section)) if readable else (None, None)
    tokens = next((v for v in (result.get("tokens"), unit.get("tokens")) if isinstance(v, int) and not isinstance(v, bool)), None)
    usd = next((float(v) for v in (result.get("cost_usd"), unit.get("cost_usd")) if _is_num(v)), None)
    run_id = result.get("run_id")
    if (tokens is None or usd is None) and run_id:
        found, section = _record_usage(run_id, _buffer())
        if not found:
            found, section = _record_usage(run_id, _store_records(2))
        if found:
            tokens = _sum(section) if tokens is None else tokens
            usd = _usd(section) if usd is None else usd
    return tokens, usd


def unit_tokens(unit: dict, result: dict | None) -> int | None:
    """Tokens of a unit (see `unit_usage`); None = unknown."""
    return unit_usage(unit, result)[0]


# ---------------- the ledger ----------------

def _day_entry(st: dict, day: str) -> dict:
    entry = st["ledger"].setdefault(day, {})
    if not isinstance(entry.get("units"), dict):
        entry["units"] = {}
    if not isinstance(entry.get("usd"), dict):
        entry["usd"] = {}
    entry["agent"] = int(entry.get("agent") or 0)
    entry["agent_usd"] = float(entry.get("agent_usd") or 0)
    return entry


def _used(entry: dict) -> int:
    return sum(int(v or 0) for v in entry["units"].values()) + entry["agent"]


def _used_usd(entry: dict) -> float:
    usd = entry.get("usd") if isinstance(entry.get("usd"), dict) else {}
    return sum(float(v or 0) for v in usd.values()) + float(entry.get("agent_usd") or 0)


def _month_usd(ledger: dict, day: str) -> float:
    """USD of the ledger days of the local month of `day`."""
    return sum(_used_usd(e) for d, e in ledger.items() if d[:7] == day[:7] and isinstance(e, dict))


def _tape(tokens: int) -> None:
    import usage_readings
    usage_readings.append_booked(tokens)


def _mark(st: dict, key: str, day: str, names: dict[str, bool], out: list[str]) -> None:
    """Keep the day a unit's usage was first found unknown (`names[unit]` True = unknown); it blocks starts only that day."""
    marks = st.setdefault(key, {})
    for name in [n for n in marks if n not in names]:
        del marks[name]
    for name, unknown in names.items():
        if not unknown:
            marks.pop(name, None)
        elif marks.setdefault(name, day) == day:
            out.append(name)


def book(slug: str, units: list[dict]) -> Usage:
    """Book the growth of each unit's tokens and USD to today and return today's usage and the units whose usage is unknown
    today. The growth of tokens of the pass also goes to the machine-wide tape."""
    day = ds.today()
    seen: dict[str, tuple[int | None, float | None]] = {}
    for unit in units:
        if not unit.get("unit"):
            continue
        result = ds.read_result(unit["worktree"]) if unit.get("worktree") else None
        seen[unit["unit"]] = unit_usage(unit, result)
    out = Usage(day, 0)
    grown = [0]

    def go(st: dict) -> None:
        entry = _day_entry(st, day)
        counted_usd = st.setdefault("counted_usd", {})
        _mark(st, "unknown", day, {n: v[0] is None for n, v in seen.items()}, out.unknown)
        _mark(st, "unknown_usd", day, {n: v[1] is None for n, v in seen.items()}, out.unknown_usd)
        for name, (n, usd) in seen.items():
            if n is not None:
                counted = int(st["counted"].get(name) or 0)
                if n > counted:
                    entry["units"][name] = int(entry["units"].get(name) or 0) + n - counted
                    st["counted"][name] = n
                    grown[0] += n - counted
            if usd is not None:
                before = float(counted_usd.get(name) or 0)
                if usd > before:
                    entry["usd"][name] = float(entry["usd"].get(name) or 0) + usd - before
                    counted_usd[name] = usd
        out.used = _used(entry)
        out.usd = _used_usd(entry)
        out.month_usd = _month_usd(st["ledger"], day)
    ds.update(slug, go)
    _tape(grown[0])
    return out


def _agent_cost(tokens: int | None, cost_usd: float | None, model: str | None) -> tuple[int, float]:
    """(tokens, USD) booked for one agent call: the reported cost, else the tokens priced as input, else the ceiling."""
    import usage_cost
    known = isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0
    booked = int(tokens) if known else AGENT_CEILING
    if _is_num(cost_usd) and cost_usd >= 0:
        return (booked if known else 0), float(cost_usd)
    prices = usage_cost.load_prices()
    priced = usage_cost.model_cost(prices, model, booked, 0, 0, 0) if model else None
    if priced is None:        # an unpriced model is booked at the highest input price of the table
        priced = max(p["input"] for p in prices.models.values()) * booked / 1e6
    return booked, priced


def book_agent(slug: str, tokens: int | None, cost_usd: float | None = None, model: str | None = None) -> int:
    """Book one agent call to today and return the tokens booked (AGENT_CEILING when the answer had no usage and no cost). Its USD
    is `cost_usd` when given, else the tokens priced as input, else the ceiling at the model's input price. The tokens go to
    the machine-wide tape too."""
    booked, usd = _agent_cost(tokens, cost_usd, model)

    def go(st: dict) -> None:
        entry = _day_entry(st, ds.today())
        entry["agent"] += booked
        entry["agent_usd"] += usd
    ds.update(slug, go)
    _tape(booked)
    return booked


def usage_today(slug: str) -> Usage:
    """Today's booked usage without booking anything (the units whose usage is unknown are not known here: use `book`)."""
    day = ds.today()
    ledger = ds.load(slug)["ledger"]
    entry = ledger.get(day) or {}
    units = entry.get("units") if isinstance(entry.get("units"), dict) else {}
    return Usage(day, sum(int(v or 0) for v in units.values()) + int(entry.get("agent") or 0), usd=_used_usd(entry),
                 month_usd=_month_usd(ledger, day))


def limit_of(policy) -> int | None:
    value = (policy.values.get("budget") or {}).get("tokens_per_day")
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
    """`[{day, tokens, usd}]`, the last `days` days oldest first: the tokens and USD of the top-level run records (no `parent`)
    of this repo by local start day, from the buffer and the store. A day that cannot be read (an incomplete usage, a store
    that cannot be reached) has `tokens` None; `usd` is None when a record is not `cost_complete`."""
    today = ds.now().date()
    wanted = [(today - dt.timedelta(days=n)).isoformat() for n in range(days - 1, -1, -1)]
    totals: dict[str, int | None] = {d: 0 for d in wanted}
    dollars: dict[str, float | None] = {d: 0.0 for d in wanted}
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
        return [{"day": d, "tokens": None, "usd": None} for d in wanted]
    for rec in records.values():
        if rec.get("parent") or rec.get("repo") != slug:
            continue
        day = _local_day(rec.get("started_at"))
        if day not in totals:
            continue
        usage = rec.get("usage") if isinstance(rec.get("usage"), dict) else None
        n, u = _sum(usage), _usd(usage)
        if totals[day] is not None:
            totals[day] = None if n is None else totals[day] + n
        if dollars[day] is not None:
            dollars[day] = None if u is None else dollars[day] + u
    return [{"day": d, "tokens": totals[d], "usd": dollars[d]} for d in wanted]


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
           "unit_usage", "usage_today"]
