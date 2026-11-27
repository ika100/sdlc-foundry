"""Spec 223 (AC-223.7 to AC-223.9): `runs report` groups ship, build and fix runs into chains per spec or issue.

A chain is every record of one repo's spec or issue; an attempt is a chain record whose parent is not in the chain."""
from __future__ import annotations

import datetime
import math
import statistics

import runs_report

CHAIN_KINDS = ("ship", "product-ship", "build", "fix")


def _key(r: dict) -> tuple[str, str, str] | None:
    repo = runs_report._text(r.get("repo"))
    spec = r.get("spec")
    if spec not in (None, "", False):
        return repo, "spec", str(spec).strip()
    issue = r.get("issue")
    number = issue.get("number") if isinstance(issue, dict) else issue
    if isinstance(number, int) and not isinstance(number, bool) or isinstance(number, str) and number.strip():
        return repo, "issue", str(number).strip()
    return None


def _cost(r: dict) -> float | None:
    usage = r.get("usage")
    totals = usage.get("totals") if isinstance(usage, dict) else None
    cost = totals.get("cost_usd") if isinstance(totals, dict) else None
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or totals.get("cost_complete") is False:
        return None
    return float(cost)


def _sum(records: list[dict]) -> tuple[float, bool]:
    known = [_cost(r) for r in records]
    return sum(c for c in known if c is not None), all(c is not None for c in known)


def _order(r: dict) -> tuple:
    return (str(r.get("started_at") or ""), str(r.get("ended_at") or ""), str(r.get("run_id") or ""))


def _item(key: tuple[str, str, str], recs: list[dict], window_start: datetime.datetime) -> dict:
    by_id: dict[str, dict] = {}
    for r in sorted(recs, key=_order):
        rid = r.get("run_id")
        if isinstance(rid, str) and rid not in by_id:
            by_id[rid] = r
    records = list(by_id.values())
    attempts = [r for r in records if r.get("parent") not in by_id]
    parents = {rid: r.get("parent") for rid, r in by_id.items()}

    def root(rid: str) -> str:
        seen = set()
        while parents.get(rid) in by_id and rid not in seen:
            seen.add(rid)
            rid = parents[rid]
        return rid

    outcomes = [r.get("outcome") for r in attempts]
    first_done = next((i for i, o in enumerate(outcomes) if o == "done"), None)
    cost, complete = _sum(records)
    successful = outside = None
    if first_done is not None:
        top = attempts[first_done]["run_id"]
        family = [r for rid, r in by_id.items() if root(rid) == top]
        s_cost, s_complete = _sum(family)
        successful = s_cost if s_complete else None
        if complete and successful is not None and cost > 0:
            outside = math.floor(100 * (cost - successful) / cost + 0.5)
    starts = [t for t in (runs_report._ts(r.get("started_at")) for r in records) if t]
    return {
        "repo": key[0], "kind": key[1], "id": key[2], "attempts": len(attempts),
        "escalations": outcomes.count("escalated"), "abandons": outcomes.count("abandoned"), "failed": outcomes.count("failed"),
        "done": first_done is not None, "attempts_to_done": None if first_done is None else first_done + 1,
        "cost_usd": cost, "cost_complete": complete, "successful_cost_usd": successful, "outside_pct": outside,
        "partial": bool(starts) and min(starts) < window_start, "run_ids": list(by_id),
    }


def aggregate_chains(kept: list[dict], *, window_start: datetime.datetime) -> dict:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    unchained = 0
    for r in kept:
        if r.get("kind") not in CHAIN_KINDS or r.get("benchmark_of"):
            continue
        key = _key(r)
        if key is None:
            unchained += 1
        else:
            groups.setdefault(key, []).append(r)
    items = [_item(k, v, window_start) for k, v in sorted(groups.items())]
    done = [i for i in items if i["done"]]
    delivered = [i for i in done if i["cost_complete"]]
    successful = [i["successful_cost_usd"] for i in done if i["successful_cost_usd"] is not None]
    return {
        "items": items, "done": len(done), "open": len(items) - len(done),
        "median_attempts_to_done": statistics.median(i["attempts_to_done"] for i in done) if done else None,
        "cost_per_delivered": sum(i["cost_usd"] for i in delivered) / len(delivered) if delivered else None,
        "median_successful_cost": statistics.median(successful) if successful else None,
        "open_spend": sum(i["cost_usd"] for i in items if not i["done"]),
        "unchained": unchained,
    }


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _money(v) -> str:
    return "unknown" if v is None else f"${v:.2f}"


def _num(v) -> str:
    return "n/a" if v is None else f"{v:g}"


def chain_lines(chains: dict) -> list[str]:
    lines = ["Chains:" + ("" if chains["items"] else " none")]
    for i in chains["items"]:
        parts = [_plural(i["attempts"], "attempt"), _plural(i["escalations"], "escalation"), _plural(i["abandons"], "abandon"),
                 f"{i['failed']} failed"]
        parts.append(f"attempts to done: {i['attempts_to_done']}" if i["done"] else "not done")
        parts.append("chain cost " + (_money(i["cost_usd"]) if i["cost_complete"] else f">= {_money(i['cost_usd'])} +unknown"))
        if i["done"]:
            parts.append(f"successful run {_money(i['successful_cost_usd'])}")
            if i["outside_pct"] is not None:
                parts.append(f"spent outside the successful run: {i['outside_pct']}%")
        lines.append(f"  {i['repo']} {i['kind']} {i['id']}: " + ", ".join(parts) + (" (partial)" if i["partial"] else ""))
    if chains["items"]:
        lines.append(f"  done {chains['done']}, not done {chains['open']}; median attempts to done: "
                     f"{_num(chains['median_attempts_to_done'])}; cost per delivered item: {_money(chains['cost_per_delivered'])} "
                     f"(median successful run {_money(chains['median_successful_cost'])}); "
                     f"spend of chains not done: {_money(chains['open_spend'])}")
    lines.append(f"  unchained: {chains['unchained']}")
    return lines
