"""Spec 124 (ADR-060): every autonomy rule `cplat` needs, in one pure module (standard library only, no I/O).

  LEVELS, CAP, DEFAULTS, ROUTES, CRITICALITY, DAYS      the tables of design.md
  validate(env, block) / validate_instance(c, env, block) / validate_top(block)   PlatformError with the renderer's messages
  effective(env, block, paused=, promotion=) -> dict    the environment object of `model show --json` and autonomy.json
  instance(env_obj, max_) -> {"max", "effective"}       an instance acts at the lower of its environment and its `max`
  compare(old, new) -> {field: tighter|looser|same}     tighten(old, new) -> the tighter of each field, never looser than old
  allows(level) -> str                                  the one-sentence text of a level
  outside(policy, fix, merges_today=, runs_today=, now=) -> [guardrail names]    AC-124.14
  parse_duration("24h") -> timedelta                    in_window(window, now) -> bool
"""
from __future__ import annotations

import copy
import datetime as dt
import re
from typing import Any
from zoneinfo import ZoneInfo

from core import PlatformError

LEVELS = ("observe", "advise", "propose", "act", "improve")
CAP = {"dev": "improve", "staging": "improve", "prod": "act"}
ROUTES = ("fix",)
CRITICALITY = ("low", "medium", "high")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULTS: dict[str, Any] = {
    "engine": None,
    "autoMerge": {"routes": ["fix"], "maxCriticality": "low"},
    "riskGate": {"maxFiles": 5, "maxLines": 200, "regressionTest": True, "secondReview": True},
    "budget": {"runsPerDay": 5, "mergesPerDay": 2,
               "perRun": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}},
    "window": {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"},
    "undoWindow": "24h",
}

_ALLOWS = {
    "observe": "The engine may record issues from signals.",
    "advise": "The engine may also triage them and notify.",
    "propose": "The engine may also open fix pull requests that a person merges.",
    "act": "The engine may also merge fixes within the guardrails, roll back after a failed smoke, and let a person undo.",
    "improve": "The engine may act as `act` until a later spec defines it.",
}
_KEYS = ("level", "autoMerge", "riskGate", "budget", "window", "undoWindow", "engine")
_GROUPS = {
    "autoMerge": ("routes", "maxCriticality"),
    "riskGate": ("maxFiles", "maxLines", "regressionTest", "secondReview"),
    "budget": ("runsPerDay", "mergesPerDay", "perRun"),
    "budget.perRun": ("minutes", "invocations", "reruns", "cost"),
    "window": ("days", "from", "to", "timezone"),
}
_DURATION = re.compile(r"^(\d{1,4})([mhd])$")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}
_MINUTES = {"m": 1, "h": 60, "d": 1440}


def allows(level: str) -> str:
    """The one-sentence text of what the engine may do at `level`."""
    return _ALLOWS[level]


# ---------------- validation ----------------

def _fail(msg: str) -> PlatformError:
    return PlatformError(msg)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _mapping(v: Any, path: str, allowed: tuple[str, ...]) -> dict:
    if not isinstance(v, dict):
        raise _fail(f"{path} must be a mapping")
    for k in v:
        if k not in allowed:
            raise _fail(f"{path}: unknown key {k!r} (allowed: {', '.join(allowed)})")
    return v


def _level(v: Any, path: str) -> str:
    if v not in LEVELS:
        raise _fail(f"{path} must be one of {', '.join(LEVELS)}, got {v!r}")
    return v


def _clock(v: Any) -> str | None:
    """`"HH:MM"`; YAML 1.1 reads an unquoted 17:00 as the number 1020, which counts as that time."""
    if _is_int(v) and 0 <= v < 1440:
        return f"{v // 60:02d}:{v % 60:02d}"
    return v if isinstance(v, str) and _TIME.match(v) else None


def validate(env: str, block: Any) -> None:
    """Raise PlatformError (the renderer's message) for a wrong `environments.<env>.autonomy`."""
    p = f"environments.{env}.autonomy"
    b = _mapping(block, p, _KEYS)
    if "level" in b:
        lv = _level(b["level"], f"{p}.level")
        if LEVELS.index(lv) > LEVELS.index(CAP.get(env, "improve")):
            raise _fail(f"{p}.level: {CAP[env]} is the highest level allowed in {env}, got {lv!r}")
    if "engine" in b:
        e = b["engine"]
        if not (isinstance(e, str) and re.match(r"^https?://[^\s/]", e)):
            raise _fail(f"{p}.engine must be an http(s) URL")
    if "autoMerge" in b:
        _auto_merge(b["autoMerge"], f"{p}.autoMerge")
    if "riskGate" in b:
        _risk_gate(b["riskGate"], f"{p}.riskGate")
    if "budget" in b:
        _budget(b["budget"], f"{p}.budget")
    if "window" in b:
        _window(b["window"], f"{p}.window")
    if "undoWindow" in b:
        try:
            parse_duration(b["undoWindow"])
        except ValueError:
            raise _fail(f"{p}.undoWindow must be a duration like 24h, 90m or 2d, got {b['undoWindow']!r}") from None


def _auto_merge(v: Any, p: str) -> None:
    m = _mapping(v, p, _GROUPS["autoMerge"])
    if "routes" in m:
        routes = m["routes"]
        if not isinstance(routes, list):
            raise _fail(f"{p}.routes must be a list (allowed: {', '.join(ROUTES)})")
        for r in routes:
            if r == "spec":
                raise _fail(f"{p}.routes: spec is refused: a spec always needs a person's approval (allowed: {', '.join(ROUTES)})")
            if r not in ROUTES:
                raise _fail(f"{p}.routes: {r!r} is not a route (allowed: {', '.join(ROUTES)})")
    if "maxCriticality" in m and m["maxCriticality"] not in CRITICALITY:
        raise _fail(f"{p}.maxCriticality must be one of {', '.join(CRITICALITY)}, got {m['maxCriticality']!r}")


def _risk_gate(v: Any, p: str) -> None:
    m = _mapping(v, p, _GROUPS["riskGate"])
    for k in ("maxFiles", "maxLines"):
        if k in m and not (_is_int(m[k]) and m[k] >= 1):
            raise _fail(f"{p}.{k} must be an integer >= 1, got {m[k]!r}")
    for k in ("regressionTest", "secondReview"):
        if k in m and not isinstance(m[k], bool):
            raise _fail(f"{p}.{k} must be true or false, got {m[k]!r}")


def _budget(v: Any, p: str) -> None:
    m = _mapping(v, p, _GROUPS["budget"])
    for k in ("runsPerDay", "mergesPerDay"):
        if k in m and not (_is_int(m[k]) and m[k] >= 0):
            raise _fail(f"{p}.{k} must be an integer >= 0, got {m[k]!r}")
    if "perRun" in m:
        per = _mapping(m["perRun"], f"{p}.perRun", _GROUPS["budget.perRun"])
        for k, x in per.items():
            if not (_is_num(x) and x > 0):
                raise _fail(f"{p}.perRun.{k} must be a number > 0, got {x!r}")


def _window(v: Any, p: str) -> None:
    m = _mapping(v, p, _GROUPS["window"])
    if "days" in m:
        d = m["days"]
        if not (isinstance(d, list) and d and all(x in DAYS for x in d) and len(set(d)) == len(d)):
            raise _fail(f"{p}.days must be a non-empty list of {', '.join(DAYS)} without duplicates, got {d!r}")
    for k in ("from", "to"):
        if k in m and _clock(m[k]) is None:
            raise _fail(f'{p}.{k} must be "HH:MM", got {m[k]!r}')
    if "from" in m and "to" in m and _clock(m["from"]) == _clock(m["to"]):
        raise _fail(f"{p}: from and to must differ")
    if "timezone" in m:
        try:
            ZoneInfo(m["timezone"])
        except Exception:
            raise _fail(f"{p}.timezone must be an IANA time zone name, got {m['timezone']!r}") from None


def validate_instance(component: str, env: str, block: Any) -> None:
    """Raise PlatformError for a wrong `components.<c>.instances.<env>.autonomy`."""
    p = f"components.{component}.instances.{env}.autonomy"
    b = _mapping(block, p, ("max",))
    if "max" in b:
        _level(b["max"], f"{p}.max")


def validate_top(block: Any) -> None:
    """Raise PlatformError for a wrong top-level `autonomy`."""
    b = _mapping(block, "autonomy", ("paused",))
    if "paused" in b and not isinstance(b["paused"], bool):
        raise _fail("autonomy.paused must be true or false")


# ---------------- effective policy ----------------

def effective(env: str, block: dict | None, *, paused: bool, promotion: str) -> dict:
    """The environment object: declared policy merged with the defaults, plus the effective level."""
    b = block or {}
    d = copy.deepcopy(DEFAULTS)
    for key in ("autoMerge", "riskGate", "window"):
        d[key].update(copy.deepcopy(b.get(key) or {}))
    d["budget"]["perRun"].update(copy.deepcopy((b.get("budget") or {}).get("perRun") or {}))
    d["budget"].update({k: v for k, v in (b.get("budget") or {}).items() if k != "perRun"})
    for k in ("from", "to"):
        d["window"][k] = _clock(d["window"][k]) or d["window"][k]
    declared = b.get("level") or "observe"
    eff = "observe" if paused else ("act" if declared == "improve" else declared)
    return {"declared": declared, "effective": eff, "cap": CAP.get(env, "improve"), "paused": bool(paused),
            "engine": b.get("engine"), "autoMerge": d["autoMerge"], "riskGate": d["riskGate"], "budget": d["budget"],
            "window": d["window"], "undoWindow": b.get("undoWindow", d["undoWindow"]), "promotion": promotion}


def _lower(a: str, b: str) -> str:
    return a if LEVELS.index(a) <= LEVELS.index(b) else b


def instance(env_obj: dict, max_: str | None) -> dict:
    """An instance acts at the lower of its environment's effective level and its `max`."""
    eff = env_obj["effective"] if max_ is None else _lower(env_obj["effective"], max_)
    return {"max": max_, "effective": eff}


# ---------------- durations and windows ----------------

def parse_duration(text: Any) -> dt.timedelta:
    """`<n>m`, `<n>h` or `<n>d` with n from 1 to 9999; ValueError otherwise."""
    m = _DURATION.match(text) if isinstance(text, str) else None
    if not m or not 1 <= int(m.group(1)) <= 9999:
        raise ValueError(f"not a duration like 24h, 90m or 2d: {text!r}")
    return dt.timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})


def _minutes(clock: str) -> int:
    h, m = clock.split(":")
    return int(h) * 60 + int(m)


def _covered(w: dict) -> set[int]:
    """The minutes of the week (Monday 00:00 = 0) that a window covers."""
    start, end = _minutes(_clock(w["from"]) or w["from"]), _minutes(_clock(w["to"]) or w["to"])
    out: set[int] = set()
    for day in w["days"]:
        base = DAYS.index(day) * 1440
        span = range(start, end) if start < end else range(start, end + 1440)
        out.update((base + m) % 10080 for m in span)
    return out


def in_window(window: dict, now: dt.datetime) -> bool:
    """`now` in the window's timezone is on one of its days and in [from, to); `to` < `from` spans midnight."""
    local = now.astimezone(ZoneInfo(window.get("timezone", "UTC")))
    start, end = _minutes(_clock(window["from"]) or window["from"]), _minutes(_clock(window["to"]) or window["to"])
    t = local.hour * 60 + local.minute
    today, yesterday = DAYS[local.weekday()], DAYS[(local.weekday() - 1) % 7]
    if start < end:
        return today in window["days"] and start <= t < end
    return (today in window["days"] and t >= start) or (yesterday in window["days"] and t < end)


# ---------------- tighter and looser ----------------

def _field_verdict(old: Any, new: Any, rank) -> str:
    a, b = rank(old), rank(new)
    return "same" if a == b else ("tighter" if b < a else "looser")


def _window_verdict(old: dict, new: dict) -> str:
    if old == new or (old.get("timezone") == new.get("timezone") and _covered(old) == _covered(new)
                      and old.get("from") == new.get("from") and old.get("to") == new.get("to")):
        return "same"
    if old.get("timezone") == new.get("timezone") and _covered(new) <= _covered(old):
        return "tighter"
    return "looser"


def _fields(p: dict) -> dict[str, Any]:
    """Every compared field of a policy, by name."""
    out: dict[str, Any] = {"level": p["declared"], "engine": p.get("engine"),
                           "autoMerge.routes": p["autoMerge"]["routes"],
                           "autoMerge.maxCriticality": p["autoMerge"]["maxCriticality"]}
    for k, v in p["riskGate"].items():
        out[f"riskGate.{k}"] = v
    for k, v in p["budget"].items():
        if k != "perRun":
            out[f"budget.{k}"] = v
    for k, v in p["budget"]["perRun"].items():
        out[f"budget.perRun.{k}"] = v
    out["window"] = p["window"]
    out["undoWindow"] = p["undoWindow"]
    return out


def _verdict(name: str, old: Any, new: Any) -> str:
    if name == "engine":
        return "same" if old == new else "looser"
    if name == "window":
        return _window_verdict(old, new)
    if name == "autoMerge.routes":
        if set(old) == set(new):
            return "same"
        return "tighter" if set(new) < set(old) else "looser"
    if name == "level":
        return _field_verdict(old, new, LEVELS.index)
    if name == "autoMerge.maxCriticality":
        return _field_verdict(old, new, CRITICALITY.index)
    if name in ("riskGate.regressionTest", "riskGate.secondReview"):
        return _field_verdict(old, new, lambda v: 0 if v else 1)
    if name == "undoWindow":
        return _field_verdict(old, new, lambda v: -parse_duration(v))
    return _field_verdict(old, new, lambda v: v)


def compare(old: dict, new: dict) -> dict[str, str]:
    """Classify each field of `new` against `old` as tighter, looser or same."""
    o, n = _fields(old), _fields(new)
    return {k: _verdict(k, o[k], n[k]) for k in o if k in n}


def tighten(old: dict, new: dict) -> dict:
    """The tighter of each field, old or new. Never looser than `old`."""
    out = copy.deepcopy(old)
    verdicts = compare(old, new)
    nf = _fields(new)

    def pick(name: str, current: Any) -> Any:
        return copy.deepcopy(nf[name]) if verdicts.get(name) == "tighter" else current

    out["declared"] = pick("level", old["declared"])
    out["effective"] = _lower(old["effective"], new["effective"]) if verdicts.get("level") == "tighter" else old["effective"]
    out["autoMerge"]["routes"] = pick("autoMerge.routes", out["autoMerge"]["routes"])
    out["autoMerge"]["maxCriticality"] = pick("autoMerge.maxCriticality", out["autoMerge"]["maxCriticality"])
    for k in out["riskGate"]:
        out["riskGate"][k] = pick(f"riskGate.{k}", out["riskGate"][k])
    for k in out["budget"]:
        if k != "perRun":
            out["budget"][k] = pick(f"budget.{k}", out["budget"][k])
    for k in out["budget"]["perRun"]:
        out["budget"]["perRun"][k] = pick(f"budget.perRun.{k}", out["budget"]["perRun"][k])
    out["window"] = pick("window", out["window"])
    out["undoWindow"] = pick("undoWindow", out["undoWindow"])
    return out


# ---------------- the guardrails ----------------

def outside(policy: dict, fix: dict, *, merges_today: int, runs_today: int, now: dt.datetime) -> list[str]:
    """The guardrails a fix is outside, in the design's order. A missing fact counts as outside."""
    am, rg, bg = policy["autoMerge"], policy["riskGate"], policy["budget"]
    change = fix.get("change") if isinstance(fix.get("change"), dict) else {}
    reg = fix.get("regression") if isinstance(fix.get("regression"), dict) else {}
    review = fix.get("second_review") if isinstance(fix.get("second_review"), dict) else {}
    crit = fix.get("criticality")
    out: list[str] = []
    if fix.get("route") not in am["routes"]:
        out.append("autoMerge.routes")
    if crit not in CRITICALITY or CRITICALITY.index(crit) > CRITICALITY.index(am["maxCriticality"]):
        out.append("autoMerge.maxCriticality")
    files, lines = change.get("files"), change.get("lines")
    if not _is_int(files) or files > rg["maxFiles"]:
        out.append("riskGate.maxFiles")
    if not _is_int(lines) or lines > rg["maxLines"]:
        out.append("riskGate.maxLines")
    if rg["regressionTest"] and not (reg.get("before") == "failed" and reg.get("after") == "passed"):
        out.append("riskGate.regressionTest")
    if rg["secondReview"] and review.get("result") != "passed":
        out.append("riskGate.secondReview")
    if merges_today >= bg["mergesPerDay"]:
        out.append("budget.mergesPerDay")
    if runs_today > bg["runsPerDay"]:
        out.append("budget.runsPerDay")
    if not in_window(policy["window"], now):
        out.append("window")
    return out
