"""Spec 210 acceptance tests: fixtures of the plan-usage files and the cost ledger shared by the `test_210_*` files.

The usage files are machine-wide state under `$XDG_STATE_HOME/sdlc-foundry/usage/` (design.md "Usage files"): `readings.json`,
`booked.jsonl`, `limit.json`. They are written here in the documented file format, so a test does not depend on the writer
modules. Times are naive local datetimes (the world's clock `World.now`); the files hold Unix seconds.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

H = dt.timedelta(hours=1)
M = dt.timedelta(minutes=1)
D = dt.timedelta(days=1)
TODAY = "2026-11-10"
SLUG = "acme/shop-api"

PRIOR_HINT = "hint: subscription usage readings found; budget.mode: plan paces by your plan's limits"
API_HINT = "hint: an API key and no subscription readings; budget.mode: cost caps spending in USD"
UNKNOWN_TEXT = "plan usage unknown (install the sensor and open an interactive session)"


def usage_dir(w) -> Path:
    return w.state_home / "sdlc-foundry" / "usage"


def ts(when: dt.datetime) -> int:
    return int(when.timestamp())


def reading(at: dt.datetime, used: float, resets: dt.datetime) -> dict:
    return {"at": ts(at), "used": used, "resets_at": ts(resets)}


def window(last: dict | None, history: list | None = None) -> dict:
    return {"last": last, "history": list(history if history is not None else ([last] if last else []))}


def put_readings(w, five: dict | None = None, seven: dict | None = None) -> None:
    d = usage_dir(w)
    d.mkdir(parents=True, exist_ok=True)
    (d / "readings.json").write_text(json.dumps({"schema": 1, "five_hour": five or window(None), "seven_day": seven or window(None)}))


def fresh(w, five=10.0, week=30.0, age_min=4, week_elapsed=0.5, week_remaining: dt.timedelta | None = None) -> None:
    """A reading `age_min` minutes old. The week is `week_elapsed` of its 7 days through (default: half, pace 46 %)."""
    at = w.now - age_min * M
    five_resets = w.now + 3 * H
    seven_resets = w.now + (week_remaining if week_remaining is not None else 7 * D * (1 - week_elapsed))
    put_readings(w, five=window(reading(at, five, five_resets)), seven=window(reading(at, week, seven_resets)))


def tape(w, *rows) -> None:
    """rows of (datetime, tokens): the dispatcher's time-stamped bookings."""
    d = usage_dir(w)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "booked.jsonl").open("a") as fh:
        for at, tokens in rows:
            fh.write(json.dumps({"at": at.timestamp(), "tokens": tokens}) + "\n")


def put_limit(w, until: dt.datetime, reset_known=True, message="You've hit your session limit · resets 3:45pm", at=None) -> None:
    d = usage_dir(w)
    d.mkdir(parents=True, exist_ok=True)
    (d / "limit.json").write_text(json.dumps({"at": ts(at or w.now - 5 * M), "until": ts(until), "reset_known": reset_known, "message": message}))


def read_json(path: Path):
    return json.loads(path.read_text())


def ledger(w, day=TODAY, usd=None, agent_usd=0.0, units=None, agent=0, **more) -> None:
    """The per-repo ledger of one day (design.md "Data"): USD per unit and of the dispatcher's agent calls, and the legacy tokens."""
    cur = w.state().get("ledger") or {}
    cur[day] = {"units": units or {}, "agent": agent, "usd": usd or {}, "agent_usd": agent_usd}
    w.write_state(ledger=cur, counted={}, counted_usd={}, **more)


def issues(w, n=3, labels=("triaged", "bug")) -> None:
    for i in range(1, n + 1):
        w.issue(i, title=f"issue {i}", labels=list(labels), created=f"2026-11-0{i}T08:00:00Z")


def plan_mode(w, **kw) -> dict:
    """The policy of a plan-mode repo; `kw` are the other `budget.plan.*` keys or top-level keys."""
    plan = kw.pop("plan", None)
    budget = {"mode": "plan"}
    if plan:
        budget["plan"] = plan
    budget.update(kw.pop("budget", {}))
    return w.policy(budget=budget, **kw)


def run_started(w, *, cycles=1) -> list[str]:
    outs = []
    for _ in range(cycles):
        r = w.run("start", "--once")
        assert r.rc == 0, r
        outs.append(r.out)
    return outs


def sensor_env(w, now: dt.datetime | None = None) -> dict:
    env = dict(os.environ)
    if now is not None:
        env["CPLAT_SENSOR_NOW"] = str(now.timestamp())
    return env


def run_status_line(command: str, payload: dict | str, env: dict) -> subprocess.CompletedProcess:
    """What Claude Code does with the configured status line: the command through a shell, the input on stdin."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(command, shell=True, input=text.encode(), capture_output=True, env=env, timeout=60)


def status_input(five=None, seven=None, extra=None) -> dict:
    """A status line input as Claude Code sends it; `five`/`seven` are (used_percentage, resets_at) or None (window absent)."""
    doc = {"session_id": "abc", "model": {"display_name": "Opus"}, "workspace": {"current_dir": "/tmp"}}
    limits = {}
    if five:
        limits["five_hour"] = {"used_percentage": five[0], "resets_at": five[1]}
    if seven:
        limits["seven_day"] = {"used_percentage": seven[0], "resets_at": seven[1]}
    if limits is not None and (five or seven):
        doc["rate_limits"] = limits
    doc.update(extra or {})
    return doc


PY = sys.executable


def record_message(w, message: str, ended: dt.datetime, seconds: float = 120.0) -> None:
    """What `headless` and `supervisor` do with the end of a session: the limit message is recorded where the dispatcher reads it."""
    import usagelimit
    hit = usagelimit.detect(message, seconds, ended)
    if hit is not None:
        usagelimit.record(hit, ended)
