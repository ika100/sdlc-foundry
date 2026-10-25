"""Spec 099 (ADR-035): price table and the cost / bucket part of the `usage` section.

  load_prices(path=) -> Prices                         taken date + per-model prices (USD per million tokens)
  model_cost(prices, model, input, output, cache_read, cache_write) -> float | None   None = unpriced
  section(items, prices) -> dict                       totals / by_phase / by_role / by_model

items are (call, share, phase, role) tuples; phase None everywhere means no `by_phase` key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT = Path(__file__).with_name("prices.json")
FAILED = "(failed)"
_COUNTS = ("calls", "failed_calls", "input", "output", "cache_read", "cache_write")


@dataclass
class Prices:
    taken: str
    models: dict[str, dict[str, float]]


def load_prices(path: Path = DEFAULT) -> Prices:
    data = json.loads(Path(path).read_text())
    return Prices(str(data["taken"]), dict(data["models"]))


def _lookup(prices: Prices, model: str) -> dict[str, float] | None:
    if model in prices.models:
        return prices.models[model]
    keys = [k for k in prices.models if model.startswith(k + "-")]
    return prices.models[max(keys, key=len)] if keys else None


def model_cost(prices: Prices, model: str, input: int, output: int, cache_read: int, cache_write: int) -> float | None:
    p = _lookup(prices, model)
    if p is None:
        return None
    return (input * p["input"] + cache_write * p["cache_write"] + cache_read * p["cache_read"]
            + output * p["output"]) / 1e6


def _num(value: float, digits: int = 6) -> int | float:
    value = round(value, digits)
    return int(value) if value == int(value) else value


def _empty() -> dict:
    return {**{k: 0.0 for k in _COUNTS}, "cost_usd": 0.0}


def _add(bucket: dict, call, share: float, cost: float) -> None:
    bucket["calls"] += share
    bucket["failed_calls"] += share if call.failed else 0
    for k in ("input", "output", "cache_read", "cache_write"):
        bucket[k] += getattr(call, k) * share
    bucket["cost_usd"] += cost


def _finish(bucket: dict, unknown: bool = False) -> dict:
    out = {k: _num(bucket[k]) for k in _COUNTS}
    out["cost_usd"] = "unknown" if unknown else _num(bucket["cost_usd"], 8)   # finer than counts: bucket sums stay within 1e-6
    return out


def section(items: Iterable[tuple], prices: Prices) -> dict:
    total, phases, roles, models = _empty(), {}, {}, {}
    missing: set[str] = set()
    with_phase = False
    for call, share, phase, role in items:
        cost = 0.0
        name = FAILED if call.failed else call.model
        if not call.failed:
            c = model_cost(prices, call.model, call.input, call.output, call.cache_read, call.cache_write)
            if c is None:
                missing.add(call.model)
            else:
                cost = c * share
        groups = [(roles, role), (models, name)]
        if phase is not None:
            with_phase = True
            groups.append((phases, phase))
        for group, key in groups:
            _add(group.setdefault(key, _empty()), call, share, cost)
        _add(total, call, share, cost)
    out = {"totals": {**_finish(total), "cost_complete": not missing, "models_without_price": sorted(missing)}}
    if with_phase:
        out["by_phase"] = {k: _finish(v) for k, v in phases.items()}
    out["by_role"] = {k: _finish(v) for k, v in roles.items()}
    out["by_model"] = {k: _finish(v, unknown=k in missing) for k, v in models.items()}
    return out
