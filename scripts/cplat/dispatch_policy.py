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
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core import PlatformError

FILE = ".platform/dispatch.yml"
TOKENS_KEY = "budget.tokens_per_day"
PER_UNIT_KEYS = ("minutes", "invocations", "reruns", "cost")
SOURCES = ("issues", "specs")
SERIALIZE = ("merge", "e2e")
APPROVE = ("human", "self")
MERGE = ("green-ci",)
FIXED_PRIORITY = ("spec-order", "oldest")

DEFAULTS: dict = {
    "slots": 1,
    "budget": {"tokens_per_day": None, "per_unit": {}},
    "sources": ["issues"],
    "ready": {"labels": [], "exclude_labels": []},
    "priority": ["label:bug", "label:p1", "spec-order", "oldest"],
    "gates": {"approve_specs": "human", "merge": "green-ci"},
    "serialize": ["merge"],
}
# The dotted keys that take a default (the leaves of DEFAULTS; `budget.per_unit` is one leaf, a mapping).
DEFAULTED_KEYS = ("slots", "budget.per_unit", "sources", "ready.labels", "ready.exclude_labels", "priority",
                  "gates.approve_specs", "gates.merge", "serialize")


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
        b = _mapping("budget", top["budget"] or {}, ("tokens_per_day", "per_unit"))
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
    if "serialize" in top:
        out["serialize"] = _subset("serialize", top["serialize"], SERIALIZE, must_have="merge")
    return out


def _given(data: dict | None, dotted: str) -> bool:
    node = data or {}
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node or node[part] is None and part == "tokens_per_day":
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
    unset = [TOKENS_KEY] if values["budget"]["tokens_per_day"] is None else []
    if require_budget and unset:
        raise PlatformError(f"{FILE}: {TOKENS_KEY} is required (it has no default)",
                            hint="set a daily token limit in the policy file (see docs/dispatch.md); "
                                 "cplat dispatch plan shows the daily usage of the last 7 days")
    return Policy(values=values, file=path if path.is_file() else None, defaulted=defaulted, unset=unset)


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
