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

UNKNOWN = "unknown"
FILED_RESULTS = ("new", "+1", "suppressed", "pending")
TOP_REASONS = 10


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


def aggregate(records: list[dict], followups: list[dict], *, malformed: int, buffered: int, since_days: int,
              repo: str | None, store: str, now: datetime.datetime) -> dict:
    cutoff = now - datetime.timedelta(days=since_days)
    seen: set[str] = set()
    kept: list[dict] = []
    for r in records:
        rid = r.get("run_id")
        if rid is not None:
            if rid in seen:
                continue
            seen.add(rid)
        ended = _ts(r.get("ended_at"))
        if ended is not None and ended < cutoff:
            continue
        if repo is not None and r.get("repo") != repo:
            continue
        kept.append(r)

    follow = {(f.get("run_id"), f.get("signature")): f for f in sorted(followups, key=lambda f: str(f.get("at", "")))}
    kinds: dict[str, Counter] = {}
    durations: dict[str, list[float]] = {}
    causes: Counter = Counter()
    reasons: Counter = Counter()
    by_reason: Counter = Counter()
    by_check: Counter = Counter()
    filed: Counter = Counter({k: 0 for k in FILED_RESULTS})
    for r in kept:
        kinds.setdefault(_text(r.get("kind")), Counter())[_text(r.get("outcome"))] += 1
        for p in _list(r.get("phases")):
            if not isinstance(p, dict):
                continue
            a, b = _ts(p.get("started_at")), _ts(p.get("ended_at"))
            if a is not None and b is not None:
                durations.setdefault(_text(p.get("name")), []).append((b - a).total_seconds())
        esc = r.get("escalation")
        if isinstance(esc, dict):
            causes[_text(esc.get("cause"))] += 1
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
    return {
        "window": {"since": (now.date() - datetime.timedelta(days=since_days)).isoformat(), "until": now.date().isoformat(),
                   "days": since_days, "repo": repo, "store": store, "records": len(kept), "malformed": malformed},
        "runs": {k: _count_sorted(kinds[k]) for k in sorted(kinds)},
        "phases": phases,
        "causes": _count_sorted(causes),
        "escalations": [{"reason": t, "count": n} for t, n in top],
        "reruns": {"by_reason": _count_sorted(by_reason), "by_check": _count_sorted(by_check)},
        "filed": dict(filed),
        "buffered": buffered,
    }


def _dur(seconds: float) -> str:
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 60}m {s % 60:02d}s"


def _pairs(counts: dict) -> str:
    return ", ".join(f"{k} {n}" for k, n in counts.items()) or "none"


def render_text(agg: dict) -> str:
    w = agg["window"]
    lines = [f"Runs {w['since']} to {w['until']} ({w['days']} days) in {w['store']}" + (f", repo {w['repo']}" if w["repo"] else "")
             + f": {w['records']} record(s); {w['malformed']} malformed line(s) skipped",
             "Runs per kind and outcome:"]
    lines += [f"  {kind}: {_pairs(outcomes)}" for kind, outcomes in agg["runs"].items()] or ["  none"]
    lines.append("Phases (median / p90):")
    lines += [f"  {n}: {_dur(p['median_s'])} / {_dur(p['p90_s'])} (n={p['count']})" for n, p in agg["phases"].items()] or ["  none"]
    lines.append(f"Escalations per cause: {_pairs(agg['causes'])}")
    lines.append("Top escalation reasons:")
    lines += [f"  {e['count']}  {e['reason']}" for e in agg["escalations"]] or ["  none"]
    lines.append(f"Reruns by reason: {_pairs(agg['reruns']['by_reason'])}")
    lines.append(f"Reruns by check: {_pairs(agg['reruns']['by_check'])}")
    lines.append("Filed issues: " + ", ".join(f"{k} {n}" for k, n in agg["filed"].items()))
    lines.append(f"Buffered locally, not included: {agg['buffered']} record(s) (cplat runs flush)")
    return "\n".join(lines)
