"""Provider contract check (spec 110; platform-owned: /platform:update refreshes it).

Loaded with `-p scripts.contract_pytest`. Every rule of `contract/<plan_id>.json` with
`role: provider` becomes cases: the boundary values of the rule are sent to the app in-process
and the answer is compared with the contract. The copy is written by
`/component:spec --from-plan`; never edit it by hand. Override the default fixtures
`contract_send` and `contract_base` in `tests/conftest.py`.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

Send = Callable[[str, dict[str, Any]], tuple[int, Any]]
Base = Callable[[str], dict[str, Any]]

_UNSET: Any = object()
_BODY_LIMIT = 200


@dataclass
class Case:
    """One request of a provider rule.

    `accept` expects a 2xx answer, otherwise the rule's rejection.
    """

    plan_id: str
    rule: dict[str, Any]
    errors: dict[str, Any]
    name: str
    accept: bool
    value: Any = _UNSET
    removed: bool = False
    derived: Any = _UNSET  # `required: present`: used when the base body has no value of its own

    def __str__(self) -> str:
        return f"{self.plan_id}:{self.rule['id']}:{self.name}"


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _decimals(number: Any) -> int:
    text = repr(number)
    return len(text.split(".")[1]) if isinstance(number, float) and "." in text else 0


def _stepped(value: Any, step: Any, sign: int) -> Any:
    result = value + sign * step
    if isinstance(result, float):
        return round(result, max(_decimals(step), _decimals(value)))
    return result


def _derived_value(rule: dict[str, Any], rules: list[dict[str, Any]]) -> Any:
    """A valid value for a required field, from the other rules on the same field."""
    same = [r for r in rules if r["endpoint"] == rule["endpoint"] and r["field"] == rule["field"]]
    for other in same:
        if other["kind"] == "allowed":
            return other["value"][0]
    for other in same:
        if other["kind"] == "min_length":
            return "x" * max(other["value"], 1)
    for other in same:
        if other["kind"] == "min_value":
            return other["value"]
    return "x"


def _not_allowed(values: list[Any]) -> Any:
    if all(_is_number(v) for v in values):
        return max(values) + 1
    out = f"{values[0]}-not-allowed"
    while out in values:
        out += "-not-allowed"
    return out


def _cases_of(
    plan_id: str,
    rule: dict[str, Any],
    errors: dict[str, Any],
    rules: list[dict[str, Any]],
) -> list[Case]:
    kind, value = rule["kind"], rule["value"]

    def case(name: str, accept: bool, **kw: Any) -> Case:
        return Case(plan_id, rule, errors, name, accept, **kw)

    if kind == "required":
        return [
            case("present", True, derived=_derived_value(rule, rules)),
            case("missing", False, removed=True),
        ]
    if kind in ("min_length", "max_length"):
        past = value - 1 if kind == "min_length" else value + 1
        out = [case("at-limit", True, value="x" * value)]
        if past >= 0 and not (kind == "min_length" and value == 0):
            out.append(case("past-limit", False, value="x" * past))
        return out
    if kind in ("min_value", "max_value"):
        step = rule.get("step", 1)
        past = _stepped(value, step, -1 if kind == "min_value" else 1)
        return [case("at-limit", True, value=value), case("past-limit", False, value=past)]
    if kind == "allowed":
        out = [case(f"allowed={v}", True, value=v) for v in value]
        return [*out, case("not-allowed", False, value=_not_allowed(value))]
    return []


def contract_cases(root: Path | None = None) -> list[Case]:
    """Every provider rule of every `contract/*.json` under `root` (default: the cwd)."""
    base_dir = (root if root is not None else Path.cwd()) / "contract"
    cases: list[Case] = []
    for path in sorted(base_dir.glob("*.json")):
        doc = json.loads(path.read_text())
        rules = doc.get("rules") or []
        for rule in rules:
            if rule.get("role") == "provider":
                cases.extend(_cases_of(doc["plan_id"], rule, doc.get("errors") or {}, rules))
    return cases


def _get(body: dict[str, Any], dotted: str) -> Any:
    node: Any = body
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return _UNSET
        node = node[key]
    return node


def _set(body: dict[str, Any], dotted: str, value: Any, *, remove: bool = False) -> None:
    *parents, last = dotted.split(".")
    node = body
    for key in parents:
        child = node.get(key)
        if not isinstance(child, dict):
            if remove:
                return
            child = node[key] = {}
        node = child
    if remove:
        node.pop(last, None)
    else:
        node[last] = value


def _shown(case: Case, value: Any) -> str:
    if case.removed:
        return "field removed"
    if isinstance(value, str) and len(value) > 40:
        return f"{len(value)} characters"
    return str(value)


def _is_rejection(case: Case, status: int, body: Any) -> bool:
    rule, errors = case.rule, case.errors
    fields = errors.get("body") or {}
    if status != rule.get("status", errors.get("status")):
        return False
    listed = fields.get("list")
    if listed:
        found = body.get(listed) if isinstance(body, dict) else None
        candidates = found if isinstance(found, list) else []
    else:
        candidates = [body]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        message = item.get(fields.get("message"))
        if (
            item.get(fields.get("field")) == rule["field"]
            and item.get(fields.get("rule")) == rule["id"]
            and isinstance(message, str)
            and message
        ):
            return True
    return False


def check_case(case: Case, send: Send, base: Base) -> None:
    """Send the case's request and assert the answer the contract demands.

    The AssertionError names rule, field, expected and actual.
    """
    rule = case.rule
    body = copy.deepcopy(base(rule["endpoint"]))
    value = case.value
    if case.derived is not _UNSET:
        existing = _get(body, rule["field"])
        value = case.derived if existing is _UNSET else existing
    if case.removed:
        _set(body, rule["field"], None, remove=True)
    else:
        _set(body, rule["field"], value)
    status, answer = send(rule["endpoint"], body)
    if case.accept:
        ok = 200 <= status < 300
        expected = "accepted (2xx)"
    else:
        ok = _is_rejection(case, status, answer)
        fields = case.errors.get("body") or {}
        expected = (
            f"rejected {rule.get('status', case.errors.get('status'))} with "
            f"{fields.get('field')}={rule['field']} {fields.get('rule')}={rule['id']} and a message"
        )
    if not ok:
        text = answer if isinstance(answer, str) else json.dumps(answer, default=str)
        raise AssertionError(
            f"contract {case.plan_id} rule {rule['id']} field {rule['field']}: {case.name} "
            f"({_shown(case, value)}) on {rule['endpoint']}: expected {expected}, "
            f"got {status} {text[:_BODY_LIMIT]}"
        )


@pytest.fixture()
def contract_send() -> Send:
    """(endpoint "POST /todos", body) -> (status, json or text), against the app in-process."""
    from fastapi.testclient import TestClient

    from {{ module_name }}.main import app

    client = TestClient(app)

    def send(endpoint: str, body: dict[str, Any]) -> tuple[int, Any]:
        method, path = endpoint.split(" ", 1)
        if "{" in path:
            raise AssertionError(
                f"{endpoint} has a path parameter: override contract_send in tests/conftest.py"
            )
        response = client.request(method, path, json=body)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text

    return send


@pytest.fixture()
def contract_base() -> Base:
    """endpoint -> a valid request body.

    Override in tests/conftest.py when an endpoint needs more than `{}`.
    """
    return lambda endpoint: {}
