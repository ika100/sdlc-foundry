"""Usage in reports (spec 099, ADR-035): the `usage` view of `cplat platform runs report`, `--benchmarks` and the `runs usage` text.

Pure functions without I/O, tolerant of records without or with odd `usage` sections.
"""
from __future__ import annotations

import datetime
import statistics
from collections import Counter

import runs_report

GROUPS = ("delivered", "failed", "escalated", "abandoned", "gate_failed")
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write")
LOWER_BOUND = "Output cost is a lower bound: output tokens are taken as the transcripts report them."


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _median(values: list):
    if not values:
        return None
    m = statistics.median(values)
    return int(m) if float(m).is_integer() and all(isinstance(v, int) for v in values) else m


def _totals(rec: dict) -> dict | None:
    usage = rec.get("usage")
    totals = usage.get("totals") if isinstance(usage, dict) else None
    return totals if isinstance(totals, dict) else None


def _tokens(totals: dict) -> int:
    return int(sum(_num(totals.get(f)) for f in TOKEN_FIELDS))


def _group(items: list[dict]) -> dict:
    tokens = [_tokens(t) for t in items]
    costs = [_num(t.get("cost_usd")) for t in items]
    return {"runs": len(items), "tokens": sum(tokens), "tokens_median": _median(tokens),
            "cost_usd": sum(costs), "cost_usd_median": _median(costs),
            "cost_incomplete": sum(1 for t in items if t.get("cost_complete") is False)}


def _gate_failed(rec: dict) -> bool:
    gates = rec.get("gates")
    return isinstance(gates, dict) and any(v == "failed" for v in gates.values())


def _excluded(rec: dict) -> bool:
    return rec.get("kind") == "benchmark" or bool(rec.get("benchmark_of"))


def aggregate_usage(records: list[dict]) -> dict:
    buckets: dict[str, dict[str, list[dict]]] = {}
    no_usage: Counter = Counter()
    tables: set[str] = set()
    for r in records:
        if _excluded(r):
            continue
        kind = runs_report._text(r.get("kind"))
        by_group = buckets.setdefault(kind, {g: [] for g in GROUPS})
        totals = _totals(r)
        if totals is None:
            no_usage[kind] += 1
            continue
        table = r["usage"].get("price_table")
        if isinstance(table, str):
            tables.add(table)
        outcome = runs_report._text(r.get("outcome"))
        if outcome == "done":
            by_group["gate_failed" if _gate_failed(r) else "delivered"].append(totals)
        elif outcome in GROUPS:
            by_group[outcome].append(totals)
    kinds = {k: {**{g: _group(buckets[k][g]) for g in GROUPS}, "no_usage": no_usage[k]} for k in sorted(buckets)}
    return {"price_tables": sorted(tables), "kinds": kinds}


def _money(x) -> str:
    return "unknown" if x is None else f"${_num(x):.2f}"


def _group_text(name: str, g: dict) -> str:
    if not g["runs"]:
        return f"{name} 0"
    text = f"{name} {g['runs']}, {g['tokens']} tokens (median {g['tokens_median']}), {_money(g['cost_usd'])} (median {_money(g['cost_usd_median'])})"
    return text + (f", cost incomplete in {g['cost_incomplete']}" if g["cost_incomplete"] else "")


def render_usage_lines(agg_usage: dict) -> list[str]:
    tables = ", ".join(agg_usage["price_tables"]) or "none"
    lines = [f"Usage per kind (estimate, prices of {tables}; output as reported, output cost is a lower bound):"]
    for kind, groups in agg_usage["kinds"].items():
        lines.append(f"  {kind}: " + "; ".join(_group_text(g.replace("_", "-"), groups[g]) for g in GROUPS)
                     + f"; no usage data {groups['no_usage']}")
    if not agg_usage["kinds"]:
        lines.append("  none")
    return lines


# ---------------- benchmarks ----------------

def plugins_label(info: dict) -> str:
    return f"local {str(info.get('commit') or '')[:7]}" + ("+dirty" if info.get("dirty") else "")


def aggregate_benchmarks(records: list[dict], *, since_days: int, repo: str | None, store: str,
                         now: datetime.datetime, malformed: int) -> dict:
    kept = runs_report.select(records, since_days=since_days, repo=repo, now=now)
    cells: dict[tuple[str, str, str, str, str], list[dict]] = {}
    tables: set[str] = set()
    for r in kept:
        if r.get("kind") != "benchmark":
            continue
        table = r["usage"].get("price_table") if isinstance(r.get("usage"), dict) else None
        if isinstance(table, str):
            tables.add(table)
        b = r.get("benchmark") if isinstance(r.get("benchmark"), dict) else {}
        label = plugins_label(b.get("plugins")) if isinstance(b.get("plugins"), dict) else "installed"
        model = b.get("coordinator_model") if isinstance(b.get("coordinator_model"), str) else "unknown"  # before spec 100
        arm = b.get("arm") if isinstance(b.get("arm"), str) and b.get("arm") else "baseline"   # before spec 107
        cells.setdefault((runs_report._text(b.get("workflow")), runs_report._text(r.get("platform_version")), label, model, arm),
                         []).append(r)
    out: dict[str, dict] = {}
    for (workflow, version, label, model, arm) in sorted(cells):
        rs = cells[(workflow, version, label, model, arm)]
        done = [t for t in map(_totals, (r for r in rs if r.get("outcome") == "done")) if t is not None]
        rest = [t for t in map(_totals, (r for r in rs if r.get("outcome") != "done")) if t is not None]
        g, f = _group(done), _group(rest)
        key = (version if label == "installed" else f"{version} [{label}]") + f" ({model}) {{{arm}}}"
        out.setdefault(workflow, {})[key] = {
            "coordinator_model": model, "runs": len(rs), "done": len(done),
            "tokens_median": g["tokens_median"], "cost_usd_median": g["cost_usd_median"],   # over done runs only
            "not_done": {"runs": len(rest), "tokens_median": f["tokens_median"], "cost_usd_median": f["cost_usd_median"]}
            if rest else None,
            "outcomes": runs_report._count_sorted(Counter(runs_report._text(r.get("outcome")) for r in rs))}
    return {
        "window": {"since": (now.date() - datetime.timedelta(days=since_days)).isoformat(), "until": now.date().isoformat(),
                   "days": since_days, "repo": repo, "store": store, "records": len(kept), "malformed": malformed},
        "price_tables": sorted(tables),
        "benchmarks": out,
    }


def render_benchmarks_text(agg: dict) -> str:
    w = agg["window"]
    lines = [f"Benchmarks {w['since']} to {w['until']} ({w['days']} days) in {w['store']}"
             + (f", repo {w['repo']}" if w.get("repo") else "")
             + f": {w['records']} record(s); {w['malformed']} malformed line(s) skipped",
             f"Cost is an estimate (prices of {', '.join(agg.get('price_tables') or []) or 'none'}); "
             "output as reported, output cost is a lower bound."]
    for workflow, versions in agg["benchmarks"].items():
        for version, row in versions.items():
            nd = row["not_done"]
            median = (f"median of {row['done']} done {round(row['tokens_median'])} tokens, "
                      f"{_money(row['cost_usd_median'])} (est.)" if row["done"] else "no done run")
            lines.append(f"  {workflow} {version}: {row['runs']} run(s), {median}, "
                         f"outcomes {runs_report._pairs(row['outcomes'])}"
                         + (f"; not done: {nd['runs']} run(s), median {round(nd['tokens_median'])} tokens, "
                            f"{_money(nd['cost_usd_median'])} (est.)" if nd else ""))
    if not agg["benchmarks"]:
        lines.append("  none")
    return "\n".join(lines)


# ---------------- `runs usage` text ----------------

def _row(label: str, b: dict) -> str:
    cost = b.get("cost_usd")
    cost_s = "unknown" if cost == "unknown" else f"{_num(cost):.4f}"
    return (f"{label:<24}{b.get('calls', 0):>7}{b.get('failed_calls', 0):>8}{b.get('input', 0):>12}{b.get('output', 0):>22}"
            f"{b.get('cache_read', 0):>13}{b.get('cache_write', 0):>13}{cost_s:>18}")


def render_section(header: str, usage: dict, *, phases: bool) -> str:
    totals = usage.get("totals") or {}
    lines = [header, f"Costs are an estimate from the price table of {usage.get('price_table')}.",
             f"{'':<24}{'calls':>7}{'failed':>8}{'input':>12}{'output (as reported)':>22}{'cache read':>13}{'cache write':>13}{'cost USD (est.)':>18}",
             _row("total", totals)]
    blocks = (("By phase:", "by_phase"),) * phases + (("By role:", "by_role"), ("By model:", "by_model"))
    for title, key in blocks:
        lines.append(title)
        lines += [_row("  " + str(name), b) for name, b in (usage.get(key) or {}).items()]
    lines.append(LOWER_BOUND)
    missing = totals.get("models_without_price") or []
    if missing:
        lines.append(f"Cost incomplete: no price for {', '.join(missing)}.")
    return "\n".join(lines)
