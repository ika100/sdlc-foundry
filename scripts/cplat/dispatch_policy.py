"""Spec 167: the dispatcher's policy file `.platform/dispatch.yml` (design.md "The policy").

  load(repo, require_file=, require_budget=) -> Policy   typed, with the defaults filled in; PlatformError for a bad file
  budget_args(policy) -> ["--budget", "cost=20", ...]    the per-unit limits for `cplat headless`
  serialize(repo) -> ["merge", ...]                       never raises; a missing or broken file is ["merge"]

`Policy.values` is the full effective mapping (`budget.tokens_per_day` is None when unset), `Policy.file` the absolute path
of the file or None, `Policy.defaulted` the dotted leaf keys that came from the defaults and `Policy.unset` the keys that
have no default and were not given (`budget.tokens_per_day`).
"""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import priority
from core import PlatformError

FILE = ".platform/dispatch.yml"
TOKENS_KEY = "budget.tokens_per_day"
USD_DAY_KEY = "budget.usd_per_day"
USD_MONTH_KEY = "budget.usd_per_month"
MODE_KEY = "budget.mode"
MODES = ("cost", "plan")
BUDGET_KEYS = ("mode", "usd_per_day", "usd_per_month", "tokens_per_day", "per_unit", "plan")
PLAN_KEYS = ("weekly_target", "window_stop", "filler_only", "filler_tasks", "filler_drafts")
PLAN_DEFAULTS: dict = {"weekly_target": 0.92, "window_stop": 0.80, "filler_only": ["priority:P2", "label:enhancement"],
                       "filler_tasks": [], "filler_drafts": True}
PER_UNIT_KEYS = ("minutes", "invocations", "reruns", "cost")
SOURCES = ("issues", "specs")
SERIALIZE = ("merge", "e2e")
APPROVE = ("human", "self")
MERGE = ("green-ci",)
FIXED_PRIORITY = ("spec-order", "oldest")

DEFAULTS: dict = {
    "slots": 1,
    "budget": {"mode": "cost", "usd_per_day": None, "usd_per_month": None, "tokens_per_day": None,
               "per_unit": {}, "plan": None},
    "sources": ["issues"],
    "ready": {"labels": [], "exclude_labels": []},
    "priority": ["label:p0", "label:bug", "label:p1", "spec-order", "oldest"],
    "gates": {"approve_specs": "human", "merge": "green-ci"},
    "serialize": ["merge"],
    "guard": {"loop_calls": 10, "loop_minutes": 5},
}
# The dotted keys that take a default (the leaves of DEFAULTS; `budget.per_unit` is one leaf, a mapping).
DEFAULTED_KEYS = ("slots", "budget.mode", "budget.per_unit", "sources", "ready.labels", "ready.exclude_labels", "priority",
                  "gates.approve_specs", "gates.merge", "serialize", "guard.loop_calls", "guard.loop_minutes")


@dataclass
class Policy:
    values: dict
    file: Path | None = None
    defaulted: list[str] = field(default_factory=list)
    unset: list[str] = field(default_factory=list)


def _err(key: str, message: str) -> PlatformError:
    return PlatformError(f"{FILE}: {key}: {message}")


def _unknown(key: str, allowed) -> PlatformError:
    return _err(key, f"unknown key (allowed: {', '.join(allowed)})")


def _bad(key: str, value, allowed: str) -> PlatformError:
    shown = "off" if value is False else ("null" if value is None else value)
    return _err(key, f"{shown} is not allowed (allowed: {allowed})")


def _mapping(key: str, value, allowed) -> dict:
    if not isinstance(value, dict):
        raise _bad(key, value, "a mapping with the keys " + ", ".join(allowed))
    for k in value:
        if k not in allowed:
            raise _unknown(f"{key}.{k}" if key != "(top level)" else str(k), allowed)
    return value


def _int(key: str, value, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        raise _bad(key, value, f"an integer {low}..{high}" if high is not None else f"an integer >= {low}")
    return value


def _usd(key: str, value) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise _bad(key, value, "a number > 0")
    return value


def _share(key: str, value) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.50 <= value <= 1.00:
        raise _bad(key, value, "a number 0.50..1.00")
    return value


def _filler_only(value) -> list[str]:
    key = "budget.plan.filler_only"
    allowed = "a list of label:<name> or priority:P0|P1|P2"
    if not isinstance(value, list):
        raise _bad(key, value, allowed)
    for rule in value:
        if not isinstance(rule, str) or not (re.fullmatch(r"priority:P[012]", rule) or (rule.startswith("label:") and len(rule) > 6)):
            raise _bad(key, rule, allowed)
    return list(dict.fromkeys(value))


def _filler_tasks(value) -> list[dict]:
    key = "budget.plan.filler_tasks"
    if not isinstance(value, list):
        raise _bad(key, value, "a list of mappings with the keys name, command")
    out: list[dict] = []
    for item in value:
        item = _mapping(key, item, ("name", "command"))
        for k in ("name", "command"):
            if not isinstance(item.get(k), str) or not item[k].strip():
                raise _err(key, f"{k} is required (allowed: a non-empty string)")
        if any(item["name"] == o["name"] for o in out):
            raise _bad(key, item["name"], "unique names")
        out.append({"name": item["name"], "command": item["command"]})
    return out


def _plan(value, mode: str) -> dict:
    """The `budget.plan` mapping filled with the defaults (mode plan only; in mode cost any key is refused)."""
    if mode != "plan":
        first = next(iter(value), None) if isinstance(value, dict) else None
        raise _err(f"budget.plan.{first}" if first is not None else "budget.plan", "needs budget.mode: plan")
    p = _mapping("budget.plan", {} if value is None else value, PLAN_KEYS)
    out = copy.deepcopy(PLAN_DEFAULTS)
    for k, v in p.items():
        key = f"budget.plan.{k}"
        if k in ("weekly_target", "window_stop"):
            out[k] = _share(key, v)
        elif k == "filler_only":
            out[k] = _filler_only(v)
        elif k == "filler_tasks":
            out[k] = _filler_tasks(v)
        elif not isinstance(v, bool):
            raise _bad(key, v, "true, false")
        else:
            out[k] = v
    return out


def _subset(key: str, value, allowed: tuple, *, must_have: str | None = None) -> list[str]:
    """A non-empty list whose items all come from `allowed`; without duplicates."""
    shown = ", ".join(allowed)
    if not isinstance(value, list) or not value:
        raise _bad(key, [] if value == [] else value, f"a non-empty list of: {shown}")
    for item in value:
        if item not in allowed:
            raise _bad(key, item, shown)
    out = list(dict.fromkeys(value))
    if must_have and must_have not in out:
        raise _err(key, f"must contain {must_have} (allowed: {shown})")
    return out


def _strings(key: str, value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise _bad(key, value, "a list of label names")
    return list(value)


def _priority(value) -> list[str]:
    allowed = "label:<name>, spec-order, oldest"
    if not isinstance(value, list) or not value:
        raise _bad("priority", [] if value == [] else value, f"a non-empty list of: {allowed}")
    for rule in value:
        if not isinstance(rule, str) or not (rule in FIXED_PRIORITY or (rule.startswith("label:") and len(rule) > 6)):
            raise _bad("priority", rule, allowed)
    return list(dict.fromkeys(value))


def _per_unit(value) -> dict:
    if value is None:
        return {}
    value = _mapping("budget.per_unit", value, PER_UNIT_KEYS)
    out: dict = {}
    for k, v in value.items():
        key = f"budget.per_unit.{k}"
        if v is False or (isinstance(v, str) and v.strip().lower() == "off"):   # YAML 1.1 reads a bare `off` as False
            out[k] = "off"
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise _bad(key, v, "a number > 0 or off")
        out[k] = v
    return out


def _validate(data) -> dict:
    """The effective mapping of a parsed file (None for an empty file); `defaulted` keys come from the caller."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise _bad("(top level)", data, "a mapping with the keys " + ", ".join(DEFAULTS))
    top = _mapping("(top level)", data, tuple(DEFAULTS))
    out = copy.deepcopy(DEFAULTS)
    if "slots" in top:
        out["slots"] = _int("slots", top["slots"], 1, 10)
    if "budget" in top:
        b = _mapping("budget", top["budget"] or {}, BUDGET_KEYS)
        mode = b.get("mode", "cost")
        if mode not in MODES:
            raise _bad(MODE_KEY, mode, ", ".join(MODES))
        out["budget"]["mode"] = mode
        for k in ("usd_per_day", "usd_per_month"):
            if b.get(k) is not None:
                out["budget"][k] = _usd(f"budget.{k}", b[k])
        if "plan" in b:
            out["budget"]["plan"] = _plan(b["plan"], mode)
        elif mode == "plan":
            out["budget"]["plan"] = copy.deepcopy(PLAN_DEFAULTS)
        if b.get("tokens_per_day") is not None:
            out["budget"]["tokens_per_day"] = _int(TOKENS_KEY, b["tokens_per_day"], 1)
        if "per_unit" in b:
            out["budget"]["per_unit"] = _per_unit(b["per_unit"])
    if "sources" in top:
        out["sources"] = _subset("sources", top["sources"], SOURCES)
    if "ready" in top:
        r = _mapping("ready", top["ready"] or {}, ("labels", "exclude_labels"))
        for k in r:
            out["ready"][k] = _strings(f"ready.{k}", r[k] if r[k] is not None else [])
    if "priority" in top:
        out["priority"] = _priority(top["priority"])
    if "gates" in top:
        g = _mapping("gates", top["gates"] or {}, ("approve_specs", "merge"))
        for k, allowed in (("approve_specs", APPROVE), ("merge", MERGE)):
            if k in g:
                if g[k] not in allowed:
                    raise _bad(f"gates.{k}", g[k], ", ".join(allowed))
                out["gates"][k] = g[k]
    if "guard" in top:
        g = _mapping("guard", top["guard"] or {}, ("loop_calls", "loop_minutes"))
        if "loop_calls" in g:
            out["guard"]["loop_calls"] = _int("guard.loop_calls", g["loop_calls"], 3, 100)
        if "loop_minutes" in g:
            out["guard"]["loop_minutes"] = _int("guard.loop_minutes", g["loop_minutes"], 1, 60)
    if "serialize" in top:
        out["serialize"] = _subset("serialize", top["serialize"], SERIALIZE, must_have="merge")
    return out


_NULLABLE = ("tokens_per_day", "usd_per_day", "usd_per_month")


def _given(data: dict | None, dotted: str) -> bool:
    node = data or {}
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node or node[part] is None and part in _NULLABLE:
            return False
        node = node[part]
    return True


def load(repo: Path | str, *, require_file: bool = False, require_budget: bool = False) -> Policy:
    path = Path(repo) / FILE
    data = None
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text())
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            raise PlatformError(f"{FILE}: cannot read the file: {str(e).splitlines()[0] if str(e) else type(e).__name__}",
                                hint="fix the YAML syntax; cplat dispatch plan shows the defaults") from e
    elif require_file:
        raise PlatformError(f"no {FILE} in {repo}",
                            hint="commit a policy file (see docs/dispatch.md); cplat dispatch plan shows the defaults")
    values = _validate(data)
    given = data if isinstance(data, dict) else {}
    defaulted = [k for k in DEFAULTED_KEYS if not _given(given, k)]
    if values["budget"]["mode"] == "plan":
        b = given.get("budget")
        given_plan = b.get("plan") if isinstance(b, dict) else None
        given_plan = given_plan if isinstance(given_plan, dict) else {}
        defaulted += [f"budget.plan.{k}" for k in PLAN_DEFAULTS if k not in given_plan]
    unset = [USD_DAY_KEY] if values["budget"]["mode"] == "cost" and values["budget"]["usd_per_day"] is None else []
    if require_budget and unset and values["budget"]["tokens_per_day"] is None:
        raise PlatformError(f"{FILE}: {USD_DAY_KEY} is required in mode cost (or the deprecated {TOKENS_KEY})",
                            hint="set a daily limit in US dollars (see docs/dispatch.md); "
                                 "cplat dispatch plan shows the cost of the last 7 days")
    return Policy(values=values, file=path if path.is_file() else None, defaulted=defaulted, unset=unset)


def mode(policy: Policy) -> str:
    return policy.values.get("budget", {}).get("mode", "cost")


def filler_match(policy: Policy, labels: list[str]) -> bool:
    """True when a `budget.plan.filler_only` rule matches the labels (always false in mode cost)."""
    plan = policy.values.get("budget", {}).get("plan")
    if mode(policy) != "plan" or not plan:
        return False
    low = [str(x).lower() for x in labels]
    for rule in plan["filler_only"]:
        kind, _, name = rule.partition(":")
        if kind == "label" and name.lower() in low:
            return True
        if kind == "priority" and priority.most_urgent(low) == name:
            return True
    return False


def budget_args(policy: Policy) -> list[str]:
    """`--budget KEY=VALUE` pairs for `cplat headless` (the keys the policy sets)."""
    out: list[str] = []
    for k in PER_UNIT_KEYS:
        if k in policy.values["budget"]["per_unit"]:
            out += ["--budget", f"{k}={policy.values['budget']['per_unit'][k]}"]
    return out


def serialize(repo: Path | str) -> list[str]:
    """The serialized steps; a missing or broken file is `["merge"]`. Never raises."""
    try:
        return list(load(repo).values["serialize"])
    except Exception:  # noqa: BLE001  (a broken file must not stop a merge from taking the lock)
        return ["merge"]
