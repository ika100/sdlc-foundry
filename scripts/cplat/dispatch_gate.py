"""Spec 210: the one ordered start gate of the dispatcher (design.md "The gate"). Every caller asks it; none repeats the order.

  gate(slug, policy, state, usage, *, now=None) -> Gate   whether starts are allowed, how many may run, the filler window, and
                                            what `plan` and `status` print about the budget
  cost_doc(usage, policy) -> dict           the `cost` object (USD amounts rounded to 2 decimals)
  Gate                                      the result: why_not, text, max_running, filler, plan, cost, needs, hints, warnings
  PAUSED, DRAIN, DAILY, MONTHLY, UNKNOWN    the `why_not` keys
  usd(x) -> str                             `$1.20`
  NEED_*, HINT_*, WARN_TOKENS               the need commands and the hint and warning texts, for the callers that print them

The order is: paused, drain, (mode plan) the pace hold, the USD daily cap, the USD monthly cap, the token cap, usage unknown.
In mode plan the caps apply only when set. The `since` of a need is kept per id in `state.budget_since` (`dispatch_budget._since`).
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

import dispatch_budget as db
import dispatch_pace as dpace
import dispatch_policy as dp
import dispatch_state as ds
import usage_readings as ur

PAUSED, DRAIN, DAILY, MONTHLY, UNKNOWN = "paused", "drain", "daily budget reached", "monthly budget reached", "usage unknown"
HISTORY_SECONDS = 7 * 86400
NEED_DAILY_USD = "raise budget.usd_per_day in .platform/dispatch.yml (starts continue after midnight)"
NEED_MONTHLY_USD = "raise budget.usd_per_month in .platform/dispatch.yml (starts continue on the 1st)"
NEED_PLAN_UNKNOWN = "cplat dispatch sensor install, then open an interactive Claude Code session"
NEED_PLAN_UNKNOWN_REASON = "plan usage unknown: no current reading of the subscription's limits"
HINT_PLAN = "hint: subscription usage readings found; budget.mode: plan paces by your plan's limits"
HINT_COST = "hint: an API key and no subscription readings; budget.mode: cost caps spending in USD"
WARN_TOKENS = "budget.tokens_per_day is deprecated: set budget.usd_per_day (cost today: {usd})"


@dataclass
class Gate:
    why_not: str | None = None
    text: str | None = None
    max_running: int | None = None
    filler: bool = False
    plan: dict | None = None
    cost: dict = field(default_factory=dict)
    needs: list[dict] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def usd(x: float) -> str:
    return f"${x:.2f}"


def _limits(policy: dp.Policy) -> tuple[float | None, float | None, int | None]:
    b = policy.values.get("budget") or {}

    def num(v):
        return None if v is None or isinstance(v, bool) else v
    return num(b.get("usd_per_day")), num(b.get("usd_per_month")), db.limit_of(policy)


def cost_doc(usage: db.Usage, policy: dp.Policy) -> dict:
    day, month, _ = _limits(policy)
    return {"day": usage.day, "used_usd": round(usage.usd, 2), "limit_usd": None if day is None else round(day, 2),
            "month_used_usd": round(usage.month_usd, 2), "month_limit_usd": None if month is None else round(month, 2)}


def _need(slug: str, key: str, reason: str, command: str, consequence: dict) -> dict:
    return {"id": f"budget:{slug}:{key}", "kind": "budget", "stage": "Build",
            "object": {"type": "dispatch", "repo": slug, "spec": None, "run_id": None, "issue": None, "component": None,
                       "version": None, "pr": None, "url": None},
            "since": db._since(slug, key), "reason": reason, "command": command, "cwd_repo": slug,
            "consequence": consequence, "way_back": None}


def _needs(slug: str, policy: dp.Policy, usage: db.Usage, plan_unknown: bool) -> list[dict]:
    day, month, tokens = _limits(policy)
    out: list[dict] = []
    if day is not None and usage.usd >= day:
        out.append(_need(slug, usage.day, f"daily cost budget reached: {usd(usage.usd)} of {usd(day)}", NEED_DAILY_USD,
                         {"used_usd": round(usage.usd, 2), "limit_usd": round(day, 2)}))
    if month is not None and usage.month_usd >= month:
        out.append(_need(slug, usage.day[:7], f"monthly cost budget reached: {usd(usage.month_usd)} of {usd(month)}",
                         NEED_MONTHLY_USD, {"used_usd": round(usage.month_usd, 2), "limit_usd": round(month, 2)}))
    if tokens is not None and usage.used >= tokens:
        out.append(_need(slug, usage.day, f"daily token budget reached: {usage.used} of {tokens} tokens", db.NEED_COMMAND,
                         {"used": usage.used, "limit": tokens}))
    if plan_unknown:
        out.append(_need(slug, usage.day, NEED_PLAN_UNKNOWN_REASON, NEED_PLAN_UNKNOWN, {}))
    seen: set[str] = set()
    return [n for n in out if not (n["id"] in seen or seen.add(n["id"]))]


def _hints(policy: dp.Policy, now: dt.datetime) -> list[str]:
    if dp.mode(policy) == "cost":
        return [HINT_PLAN] if ur.any_reading_since(now.timestamp() - HISTORY_SECONDS) else []
    if os.environ.get("ANTHROPIC_API_KEY") and not ur.any_reading_since(0):
        return [HINT_COST]
    return []


def _unknown(policy: dp.Policy, usage: db.Usage) -> list[str]:
    day, month, tokens = _limits(policy)
    names: list[str] = []
    if day is not None or month is not None:
        names += usage.unknown_usd
    if tokens is not None or dp.mode(policy) == "plan":
        names += usage.unknown
    return list(dict.fromkeys(names))


def _hold(state: dict, policy: dp.Policy, usage: db.Usage, pace: dpace.Pace | None) -> tuple[str, str] | None:
    paused = (state.get("steering") or {}).get("paused")
    if paused == "pause":
        return PAUSED, PAUSED
    if paused == "drain":
        return DRAIN, DRAIN
    if pace is not None and pace.hold is not None:
        return pace.hold
    day, month, tokens = _limits(policy)
    if day is not None and usage.usd >= day:
        return DAILY, f"{DAILY}: {usd(usage.usd)} of {usd(day)}"
    if month is not None and usage.month_usd >= month:
        return MONTHLY, f"{MONTHLY}: {usd(usage.month_usd)} of {usd(month)}"
    if tokens is not None and usage.used >= tokens:
        return DAILY, f"{DAILY}: {usage.used} of {tokens} tokens"
    unknown = _unknown(policy, usage)
    if unknown:
        return UNKNOWN, f"{UNKNOWN}: {', '.join(unknown)}"
    return None


def gate(slug: str, policy: dp.Policy, state: dict, usage: db.Usage, *, now: dt.datetime | None = None) -> Gate:
    now = ds.now() if now is None else now
    plan_mode = dp.mode(policy) == "plan"
    pace = dpace.pace(policy, now) if plan_mode else None
    hold = _hold(state, policy, usage, pace)
    out = Gate(cost=cost_doc(usage, policy), hints=_hints(policy, now))
    if hold is not None:
        out.why_not, out.text = hold
    elif pace is not None:
        out.max_running, out.filler = pace.max_running, pace.filler
    if pace is not None:
        out.plan = dpace.doc(pace, policy)
    out.needs = _needs(slug, policy, usage, pace is not None and pace.hold is not None and pace.hold[0] == "plan usage unknown")
    if _limits(policy)[2] is not None:
        out.warnings.append(WARN_TOKENS.format(usd=usd(usage.usd)))
    return out


__all__ = ["DAILY", "DRAIN", "Gate", "HINT_COST", "HINT_PLAN", "MONTHLY", "NEED_DAILY_USD", "NEED_MONTHLY_USD", "NEED_PLAN_UNKNOWN",
           "NEED_PLAN_UNKNOWN_REASON", "PAUSED", "UNKNOWN", "WARN_TOKENS", "cost_doc", "gate", "usd"]
