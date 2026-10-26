"""Reading the run store (spec 087, ADR-032): parse store lines, dedupe, merge follow-ups, aggregate, render.

Pure functions without I/O. Tolerant of older schemas, unknown kinds and fields, and malformed lines: whatever is
missing counts as "unknown".
"""
from __future__ import annotations

import datetime
import json
import math
import statistics
from collections import Counter

import core
import escalation_rules
import feedback
import runs_usage_report

UNKNOWN = "unknown"
FILED_RESULTS = ("new", "+1", "suppressed", "pending")
TOP_REASONS = 10
PR_WAIT_RESULTS = ("green", "merged", "red", "budget-refused", "timeout", "no-checks", "closed", "merge-failed", "error")
RED_RESULTS = ("red", "budget-refused")
RED_CI = "red-ci"    # a reader's count, never an outcome in a record
TOP_RED_CHECKS = 5
MAX_UNCLASSIFIED = 20


def parse(texts: list[str]) -> tuple[list[dict], list[dict], int]:
    """Lines of the store files -> (records, follow-ups, malformed line count)."""
    records: list[dict] = []
    followups: list[dict] = []
    malformed = 0
    for text in texts:
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                obj = None
            if not isinstance(obj, dict):
                malformed += 1
            elif "followup" in obj:
                followups.append(obj)
            else:
                records.append(obj)
    return records, followups, malformed


def _ts(value) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else UNKNOWN


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _count_sorted(counter: Counter) -> dict:
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def pr_wait_result(record: dict) -> str | None:
    """None for a record whose kind is not pr-wait; "unrecorded" when it has no `pr_wait` dict; "unknown" when the
    dict has no string `result`; otherwise the result (an unlisted one is kept under its own name)."""
    if record.get("kind") != "pr-wait":
        return None
    section = record.get("pr_wait")
    if not isinstance(section, dict):
        return "unrecorded"
    result = section.get("result")
    return result.strip() if isinstance(result, str) and result.strip() else UNKNOWN


def count_outcome(record: dict) -> str:
    """The outcome a reader counts: RED_CI for kind pr-wait, outcome failed and a result in RED_RESULTS; otherwise
    _text(record["outcome"])."""
    outcome = _text(record.get("outcome"))
    if outcome == "failed" and pr_wait_result(record) in RED_RESULTS:
        return RED_CI
    return outcome


def red_check_names(record: dict) -> set[str]:
    """The distinct check names of a red or budget-refused pr-wait record (non-list and non-string entries skipped)."""
    if pr_wait_result(record) not in RED_RESULTS:
        return set()
    names = record["pr_wait"].get("checks")
    return {c for c in (names if isinstance(names, list) else []) if isinstance(c, str)}


def aggregate_pr_wait(kept: list[dict]) -> dict:
    results: Counter = Counter()
    checks: Counter = Counter()
    for r in kept:
        result = pr_wait_result(r)
        if result is None:
            continue
        results[result] += 1
        checks.update(red_check_names(r))
    ordered = {k: results.get(k, 0) for k in (*PR_WAIT_RESULTS, "unrecorded")}
    ordered.update({k: results[k] for k in sorted(results) if k not in ordered})
    top = sorted(checks.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_RED_CHECKS]
    return {"results": ordered, "red_checks": [{"check": c, "count": n} for c, n in top]}


class Unclassified(dict):
    """The `unclassified` figures; `more` (reasons beyond the cap) is for the text only and not a JSON key."""
    more = 0


def effective_escalation(record: dict) -> escalation_rules.Resolved | None:
    """None without an escalation dict; otherwise the cause as the current rules read it (spec 088, AC-088.21)."""
    esc = record.get("escalation")
    return escalation_rules.effective(esc) if isinstance(esc, dict) else None


def aggregate_unclassified(kept: list[dict]) -> dict:
    unknown: Counter = Counter()
    total = by_rule = 0
    for r in kept:
        res = effective_escalation(r)
        if res is None:
            continue
        total += 1
        by_rule += res.source == "rule"
        if res.cause == UNKNOWN:
            unknown[_text(r["escalation"].get("reason"))] += 1
    count = sum(unknown.values())
    out = Unclassified(
        count=count, escalations=total, share=round(count / total, 3) if total else None, by_rule=by_rule,
        reasons=[{"reason": t, "count": n} for t, n in sorted(unknown.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_UNCLASSIFIED]])
    out.more = max(0, len(unknown) - MAX_UNCLASSIFIED)
    return out


def select(records: list[dict], *, since_days: int, repo: str | None, now: datetime.datetime) -> list[dict]:
    """Window, repo filter and run_id dedupe, shared by both reports."""
    cutoff = now - datetime.timedelta(days=since_days)
    # `until` is the day of `now` (the window prints it as a date): that whole day counts, later records do not
    upper = datetime.datetime.combine(now.date() + datetime.timedelta(days=1), datetime.time(), tzinfo=now.tzinfo)
    seen: set[str] = set()
    kept: list[dict] = []
    for r in records:
        rid = r.get("run_id")
        if rid is not None:
            if rid in seen:
                continue
            seen.add(rid)
        ended = _ts(r.get("ended_at"))
        if ended is not None and (ended < cutoff or ended >= upper):
            continue
        if repo is not None and r.get("repo") != repo:
            continue
        kept.append(r)
    return kept


def aggregate(records: list[dict], followups: list[dict], *, malformed: int, buffered: int, since_days: int,
              repo: str | None, store: str, now: datetime.datetime) -> dict:
    kept = select(records, since_days=since_days, repo=repo, now=now)

    follow = {(f.get("run_id"), f.get("signature")): f for f in sorted(followups, key=lambda f: str(f.get("at", "")))}
    kinds: dict[str, Counter] = {}
    durations: dict[str, list[float]] = {}
    causes: Counter = Counter()
    reasons: Counter = Counter()
    by_reason: Counter = Counter()
    by_check: Counter = Counter()
    filed: Counter = Counter({k: 0 for k in FILED_RESULTS})
    for r in kept:
        kinds.setdefault(_text(r.get("kind")), Counter())[count_outcome(r)] += 1
        for p in _list(r.get("phases")):
            if not isinstance(p, dict):
                continue
            a, b = _ts(p.get("started_at")), _ts(p.get("ended_at"))
            if a is not None and b is not None:
                durations.setdefault(_text(p.get("name")), []).append((b - a).total_seconds())
        esc = r.get("escalation")
        if isinstance(esc, dict):
            causes[effective_escalation(r).cause] += 1
            reasons[_text(esc.get("reason"))] += 1
        for rr in _list(r.get("reruns")):
            rr = rr if isinstance(rr, dict) else {}
            by_reason[_text(rr.get("reason"))] += 1
            by_check[_text(rr.get("check"))] += 1
        seen_sigs = set()
        for f in _list(r.get("filed")):
            if not isinstance(f, dict):
                continue
            sig = f.get("signature")
            seen_sigs.add(sig)
            upd = follow.get((r.get("run_id"), sig))
            filed[_text(upd.get("result") if upd else f.get("result"))] += 1
        for (rid, sig), upd in follow.items():
            if rid is not None and rid == r.get("run_id") and sig not in seen_sigs:
                filed[_text(upd.get("result"))] += 1
                seen_sigs.add(sig)

    phases = {}
    for name in sorted(durations):
        d = sorted(durations[name])
        phases[name] = {"count": len(d), "median_s": float(statistics.median(d)), "p90_s": float(d[math.ceil(0.9 * len(d)) - 1])}
    top = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_REASONS]
    out = {
        "window": {"since": (now.date() - datetime.timedelta(days=since_days)).isoformat(), "until": now.date().isoformat(),
                   "days": since_days, "repo": repo, "store": store, "records": len(kept), "malformed": malformed},
        "runs": {k: _count_sorted(kinds[k]) for k in sorted(kinds)},
        "phases": phases,
        "causes": _count_sorted(causes),
        "escalations": [{"reason": t, "count": n} for t, n in top],
        "reruns": {"by_reason": _count_sorted(by_reason), "by_check": _count_sorted(by_check)},
        "filed": dict(filed),
        "buffered": buffered,
        "usage": runs_usage_report.aggregate_usage(kept),
        "pr_wait": aggregate_pr_wait(kept),
        "unclassified": aggregate_unclassified(kept),
    }
    validation = aggregate_validation(kept)
    if validation["rules"]:   # spec 103: only when a run recorded a validation section
        out["validation"] = validation
    return out


def aggregate_validation(kept: list[dict]) -> dict:
    """Spec 103: decisions per rule and misses per rule over the `validation` sections of the runs."""
    rules: dict[str, Counter] = {}
    misses: Counter = Counter()
    for r in kept:
        v = r.get("validation")
        if not isinstance(v, dict):
            continue
        for c in _list(v.get("checks")):
            if isinstance(c, dict):
                rules.setdefault(_text(c.get("rule")), Counter())[_text(c.get("decision"))] += 1
        for m in _list(v.get("misses")):
            if isinstance(m, dict):
                misses[_text(m.get("rule"))] += 1
    return {"rules": {k: {d: rules[k].get(d, 0) for d in ("run", "reused", "skipped")} for k in sorted(rules)},
            "misses": _count_sorted(misses)}


def _dur(seconds: float) -> str:
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 60}m {s % 60:02d}s"


def _pairs(counts: dict) -> str:
    return ", ".join(f"{k} {n}" for k, n in counts.items()) or "none"


def _unclassified_lines(u: dict) -> list[str]:
    if not u["escalations"]:
        return ["Unclassified escalations: none"]
    pct = (200 * u["count"] + u["escalations"]) // (2 * u["escalations"])   # floor(100 * n / m + 0.5)
    lines = [f"Unclassified escalations: {u['count']} of {u['escalations']} ({pct}%)", f"  classified by rule: {u['by_rule']}"]
    lines += [f"  {x['count']}  {x['reason']}" for x in u["reasons"]]
    more = getattr(u, "more", 0)
    if more:
        lines.append(f"  … and {more} more")
    return lines


def render_text(agg: dict) -> str:
    w = agg["window"]
    lines = [f"Runs {w['since']} to {w['until']} ({w['days']} days) in {w['store']}" + (f", repo {w['repo']}" if w["repo"] else "")
             + f": {w['records']} record(s); {w['malformed']} malformed line(s) skipped",
             "Runs per kind and outcome:"]
    lines += [f"  {kind}: {_pairs(outcomes)}" for kind, outcomes in agg["runs"].items()] or ["  none"]
    pw = agg["pr_wait"]
    lines.append("pr-wait results: " + (", ".join(f"{k} {n}" for k, n in pw["results"].items()) if any(pw["results"].values()) else "none"))
    lines.append("Red checks: " + (", ".join(f"{c['check']} {c['count']}" for c in pw["red_checks"]) or "none"))
    lines.append("Phases (median / p90):")
    lines += [f"  {n}: {_dur(p['median_s'])} / {_dur(p['p90_s'])} (n={p['count']})" for n, p in agg["phases"].items()] or ["  none"]
    lines.append(f"Escalations per cause: {_pairs(agg['causes'])}")
    lines.append("Top escalation reasons:")
    lines += [f"  {e['count']}  {e['reason']}" for e in agg["escalations"]] or ["  none"]
    lines += _unclassified_lines(agg["unclassified"])
    lines.append(f"Reruns by reason: {_pairs(agg['reruns']['by_reason'])}")
    lines.append(f"Reruns by check: {_pairs(agg['reruns']['by_check'])}")
    lines.append("Filed issues: " + ", ".join(f"{k} {n}" for k, n in agg["filed"].items()))
    lines += runs_usage_report.render_usage_lines(agg["usage"])
    validation = agg.get("validation") or {}
    if validation.get("rules"):
        lines.append("Validation checks per rule: " + "; ".join(
            f"{rule} " + ", ".join(f"{d} {n}" for d, n in counts.items()) for rule, counts in validation["rules"].items()))
        lines.append(f"Validation misses per rule: {_pairs(validation['misses'])}")
    lines.append(f"Buffered locally, not included: {agg['buffered']} record(s) (cplat runs flush)")
    return "\n".join(lines)


# ---------------- agent report (spec 089) ----------------

ROLE_METRICS = {"architect": ("out_of_plan", "merge_conflicts", "replans"),
                "coder": ("fix_rounds", "red_ci", "findings", "refused_test_diffs"),
                "quality": ("refused_test_diffs",), "tester": ("tester_events",)}
FIX_CAUSES = ("lint/type", "test", "ci", "verification")
SEVERITIES = ("not met", "partial", "deviation")
TESTER_REASONS = ("untraced", "wrong failure")
FEW_RUNS = 5
TOP_CAUSES = 3


def _r(x: float) -> float:
    return round(x, 3)


def _s(value) -> str:
    return feedback.redact(str(value))[:200]


def _pattern(path) -> str:
    path = str(path)
    parent, _, name = path.rpartition("/")
    dot = name.rfind(".")
    suffix = name[dot:] if dot > 0 else ""
    if suffix:
        return f"{parent}/*{suffix}" if parent else f"*{suffix}"
    return f"{parent}/*" if parent else "*"


def _labels(ev: dict) -> list[str]:
    k = ev.get("kind")
    if k == "out-of-plan":
        return [f"out-of-plan {_pattern(ev.get('path'))}"]
    if k == "merge-conflict":
        return [f"merge-conflict {p}" for p in sorted({_pattern(x) for x in _list(ev.get("paths"))})]
    if k == "fix-round":
        return [f"fix-round {ev.get('cause')}"]
    if k == "red-ci":
        return [f"red-ci {ev.get('check')}"]
    if k == "finding":
        return [f"{ev.get('severity')} {ev.get('criterion') or ev.get('task')}"]
    if k == "refused-test-diff":
        return [f"refused-test-diff {ev.get('file')}"]
    if k == "tester":
        return [f"{ev.get('reason')} {ev.get('criterion') if ev.get('reason') == 'untraced' else ev.get('test')}"]
    return []


def _avg(total: float, runs: int) -> float | None:
    return _r(total / runs) if runs else None


def _metrics(role: str, group: list[tuple[dict, list[dict]]]) -> dict:
    """group: [(record, events of the row's entries in it)]. Per-metric averages over the runs that measured it."""
    def measured(metric):
        return [evs for r, evs in group if metric in _list((r.get("agent_metrics") or {}).get("measured"))]

    def count(evs, kind, **where):
        return sum(1 for e in evs if e.get("kind") == kind and all(e.get(k) == v for k, v in where.items()))

    out: dict = {}
    for metric in ROLE_METRICS.get(role, ()):
        runs_ = measured(metric)
        n = len(runs_)
        if metric == "out_of_plan":
            out[metric] = {"runs": n, "avg": _avg(sum(count(e, "out-of-plan") for e in runs_), n)}
        elif metric == "merge_conflicts":
            total = sum(count(e, "merge-conflict") for e in runs_)
            res = sum(count(e, "merge-conflict", outcome="resolved") for e in runs_)
            out[metric] = {"runs": n, "avg": _avg(total, n), "resolved_share": _r(res / total) if total else None}
        elif metric == "replans":
            out[metric] = {"runs": n, "avg": _avg(sum(count(e, "re-plan") for e in runs_), n)}
        elif metric == "fix_rounds":
            out[metric] = {"runs": n, "avg": _avg(sum(count(e, "fix-round") for e in runs_), n),
                           "by_cause": {c: _avg(sum(count(e, "fix-round", cause=c) for e in runs_), n) for c in FIX_CAUSES}}
        elif metric == "red_ci":
            out[metric] = {"runs": n, "avg": _avg(sum(count(e, "red-ci") for e in runs_), n)}
        elif metric == "findings":
            def sev(p, s_):
                return _avg(sum(count(e, "finding", **{"pass": p, "severity": s_}) for e in runs_), n)
            out[metric] = {"runs": n,
                           "avg": _avg(sum(count(e, "finding", **{"pass": "first"}) for e in runs_), n),
                           "by_severity": {s_: sev("first", s_) for s_ in SEVERITIES},
                           "after_fix": {"avg": _avg(sum(count(e, "finding", **{"pass": "after fix"}) for e in runs_), n),
                                         "by_severity": {s_: sev("after fix", s_) for s_ in SEVERITIES}}}
        elif metric == "refused_test_diffs":
            out[metric] = {"runs": n, "avg": _avg(sum(count(e, "refused-test-diff") for e in runs_), n)}
        elif metric == "tester_events":
            out[metric] = {"runs": n, "avg": _avg(sum(count(e, "tester") for e in runs_), n),
                           "by_reason": {t: _avg(sum(count(e, "tester", reason=t) for e in runs_), n) for t in TESTER_REASONS}}
    return out


def _rework(metrics: dict) -> float:
    total = sum((m.get("avg") or 0) for m in metrics.values())
    total += ((metrics.get("findings") or {}).get("after_fix") or {}).get("avg") or 0
    return _r(total)


def _top_causes(group: list[tuple[dict, list[dict]]]) -> list[dict]:
    counts: Counter = Counter()
    latest: dict[str, tuple] = {}
    for r, evs in group:
        key = (str(r.get("ended_at") or ""), str(r.get("run_id") or ""))
        for e in evs:
            for lab in _labels(e):
                lab = _s(lab)
                counts[lab] += 1
                if lab not in latest or key > latest[lab][0]:
                    latest[lab] = (key, r.get("run_id"))
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_CAUSES]
    return [{"cause": lab, "count": n, "run_id": latest[lab][1]} for lab, n in top]


def _vkey(v):
    try:
        return (0, core.vtuple(v), "")
    except (ValueError, AttributeError):
        return (1, (), str(v))


def aggregate_agents(records: list[dict], *, malformed: int, buffered: int, since_days: int, repo: str | None,
                     agent: str | None, shape: str | None, by_version: bool, store: str, now: datetime.datetime) -> dict:
    kept = select(records, since_days=since_days, repo=repo, now=now)
    groups: dict[tuple, dict] = {}
    for r in kept:
        entries = [e for e in _list(r.get("agents")) if isinstance(e, dict)
                   and all(isinstance(e.get(f), str) for f in ("agent", "shape", "model"))]
        version = (r.get("platform_version") if isinstance(r.get("platform_version"), str) else UNKNOWN) if by_version else None
        per_key: dict[tuple, list[dict]] = {}
        ids: dict[tuple, list[str]] = {}
        for e in entries:
            a = e["agent"]
            if agent is not None and (a != agent if ":" in agent else a.rpartition(":")[2] != agent):
                continue
            if shape is not None and e["shape"] != shape:
                continue
            k = (a, e["shape"], e["model"], version)
            per_key.setdefault(k, []).extend(x for x in _list(e.get("events")) if isinstance(x, dict))
            if isinstance(e.get("model_id"), str):
                ids.setdefault(k, []).append(e["model_id"])
        for k, evs in per_key.items():
            g = groups.setdefault(k, {"group": [], "ids": set()})
            g["group"].append((r, evs))
            g["ids"].update(ids.get(k, []))
    rows = []
    for (a, sh, model, version), g in groups.items():
        group = g["group"]
        metrics = _metrics(a.rpartition(":")[2], group)
        rows.append({
            "agent": _s(a), "shape": _s(sh), "model": _s(model), "platform_version": version,
            "model_ids": sorted(_s(i) for i in g["ids"]),
            "runs": len(group), "few_runs": len(group) < FEW_RUNS,
            "incomplete_runs": sum(1 for r, _ in group if (r.get("agent_metrics") or {}).get("complete") is False),
            "rework": _rework(metrics), "metrics": metrics, "top_causes": _top_causes(group),
        })
    ident = lambda r: (r["agent"], r["shape"], r["model"])  # noqa: E731
    if by_version:
        worst: dict[tuple, float] = {}
        for r in rows:
            worst[ident(r)] = max(worst.get(ident(r), 0.0), r["rework"])
        rows.sort(key=lambda r: (-worst[ident(r)], *ident(r), _vkey(r["platform_version"])))
    else:
        rows.sort(key=lambda r: (-r["rework"], *ident(r)))
    return {
        "window": {"since": (now.date() - datetime.timedelta(days=since_days)).isoformat(), "until": now.date().isoformat(),
                   "days": since_days, "repo": repo, "agent": agent, "shape": shape, "by_version": by_version,
                   "store": store, "records": len(kept), "malformed": malformed},
        "rows": rows,
        "buffered": buffered,
    }


def _a(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def render_agents_text(agg: dict) -> str:
    w = agg["window"]
    head = (f"Agents {w['since']} to {w['until']} ({w['days']} days) in {w['store']}"
            + (f", repo {w['repo']}" if w.get("repo") else "") + (f", agent {w['agent']}" if w.get("agent") else "")
            + (f", shape {w['shape']}" if w.get("shape") else "")
            + f": {w['records']} record(s); {w['malformed']} malformed line(s) skipped")
    lines = [head]
    for r in agg["rows"]:
        m = r["metrics"]
        title = f"{r['agent']} {r['shape']} {r['model']}" + (f" {r['platform_version']}" if r.get("platform_version") else "")
        lines.append(f"{title}: {r['runs']} run(s)" + (", few runs" if r["few_runs"] else "")
                     + (f", {r['incomplete_runs']} incomplete" if r["incomplete_runs"] else "") + f", rework {r['rework']:.2f}")
        if "out_of_plan" in m:
            share = m["merge_conflicts"]["resolved_share"]
            pct = "n/a" if share is None else f"{round(share * 100)}%"
            lines.append(f"  out-of-plan files {_a(m['out_of_plan']['avg'])} · merge conflicts {_a(m['merge_conflicts']['avg'])} "
                         f"(resolved {pct}) · re-plans {_a(m['replans']['avg'])}")
        elif "fix_rounds" in m:
            fr, f = m["fix_rounds"], m["findings"]
            lines.append(f"  fix rounds {_a(fr['avg'])} (" + ", ".join(f"{c} {_a(fr['by_cause'][c])}" for c in FIX_CAUSES)
                         + f") · red-CI rounds {_a(m['red_ci']['avg'])} · findings {_a(f['avg'])} ("
                         + ", ".join(f"{s_} {_a(f['by_severity'][s_])}" for s_ in SEVERITIES)
                         + f"; after fix {_a(f['after_fix']['avg'])}) · refused test diffs {_a(m['refused_test_diffs']['avg'])}")
        elif "tester_events" in m:
            t = m["tester_events"]
            lines.append(f"  tester events {_a(t['avg'])} (" + ", ".join(f"{x} {_a(t['by_reason'][x])}" for x in TESTER_REASONS) + ")")
        elif "refused_test_diffs" in m:
            lines.append(f"  refused test diffs {_a(m['refused_test_diffs']['avg'])}")
        causes = "; ".join(f"{c['count']}× {c['cause']} ({c['run_id']})" for c in r["top_causes"]) or "none"
        lines.append(f"  causes: {causes}")
    if not agg["rows"]:
        lines.append("  none")
    lines.append(f"Buffered locally, not included: {agg['buffered']} record(s) (cplat runs flush)")
    return "\n".join(lines)
