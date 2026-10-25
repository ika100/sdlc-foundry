"""The weekly retro report (spec 090, ADR-039): a pure function over run records, platform issues and agent metrics.

No I/O. `build` gives the `report.json` dict; the renderings are text for the maintainer (`render_text`,
`render_private`, committed to the private run store) and the public issue body (`render_public`: counts and
placeholders, never a repo, spec or store name).
"""
from __future__ import annotations

import datetime
import re
import statistics

import autoissue
import runs_report
import triage

SCHEMA = 1
OUTCOMES = ("done", "escalated", "failed", "abandoned")
CAUSES = ("platform", "code", "decision", "environment", "unknown")
RERUN_REASONS = ("stale", "stuck", "transient")
NO_DATA = "no data for this week"
SAFE = re.compile(r"^[a-z][a-z0-9:._/-]{0,39}$")    # vocabulary that may appear publicly (kinds, outcomes, phases)
MAX_RUN_IDS = 5
UNKNOWN = "unknown"
_SIGNATURE = re.compile(r"^Signature: (platform:[0-9a-f]{16})$", re.M)
_UTC = datetime.timezone.utc


# ---------------- weeks ----------------

def _week_str(d: datetime.date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def last_complete_week(today: datetime.date) -> str:
    return _week_str(today - datetime.timedelta(days=7))


def week_bounds(week: str) -> tuple[datetime.datetime, datetime.datetime]:
    m = re.fullmatch(r"(\d{4})-W(\d{2})", week)
    if not m:
        raise ValueError(f"not an ISO week: {week!r}")
    monday = datetime.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    start = datetime.datetime(monday.year, monday.month, monday.day, tzinfo=_UTC)
    return start, start + datetime.timedelta(days=7)


def previous_week(week: str) -> str:
    start, _ = week_bounds(week)
    return _week_str((start - datetime.timedelta(days=7)).date())


# ---------------- helpers ----------------

def _fig(cur, prev) -> dict:
    return {"current": cur, "previous": prev}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _text(v) -> str:
    return runs_report._text(v)


def _seconds(r: dict) -> float:
    a, b = runs_report._ts(r.get("started_at")), runs_report._ts(r.get("ended_at"))
    return float((b - a).total_seconds()) if a is not None and b is not None else 0.0


def _shape_of(r: dict) -> str:
    for e in runs_report._list(r.get("agents")):
        if isinstance(e, dict) and isinstance(e.get("shape"), str) and e["shape"] and e["shape"] != "none":
            return e["shape"]
    return UNKNOWN


def _outcome(r: dict) -> str:
    o = r.get("outcome")
    return o if o in OUTCOMES else UNKNOWN


def _cause(esc: dict) -> str:
    c = esc.get("cause")
    return c if c in CAUSES else UNKNOWN


def _escalation(r: dict) -> dict | None:
    e = r.get("escalation")
    return e if isinstance(e, dict) else None


def _reruns(r: dict) -> list[dict]:
    return [x if isinstance(x, dict) else {} for x in runs_report._list(r.get("reruns"))]


def _split(records: list[dict], week: str) -> tuple[list[dict], list[dict]]:
    """Dedupe by run_id (first wins), then the records of `week` and of the week before, in a fixed order."""
    seen: set = set()
    kept: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        rid = r.get("run_id")
        if rid is not None:
            if rid in seen:
                continue
            seen.add(rid)
        kept.append(r)
    kept.sort(key=lambda r: (str(r.get("ended_at") or ""), str(r.get("run_id") or "")))
    bounds = {"cur": week_bounds(week), "prev": week_bounds(previous_week(week))}
    out: dict[str, list[dict]] = {"cur": [], "prev": []}
    for r in kept:
        ended = runs_report._ts(r.get("ended_at"))
        if ended is None:
            continue
        for key, (a, b) in bounds.items():
            if a <= ended < b:
                out[key].append(r)
    return out["cur"], out["prev"]


# ---------------- build ----------------

def _runs(cur: list[dict], prev: list[dict]) -> dict:
    counts: dict[str, dict[str, list[int]]] = {}
    for i, group in enumerate((cur, prev)):
        for r in group:
            c = counts.setdefault(_text(r.get("kind")), {})
            c.setdefault(_outcome(r), [0, 0])[i] += 1
    seen_unknown = any(UNKNOWN in c for c in counts.values())
    names = OUTCOMES + ((UNKNOWN,) if seen_unknown else ())
    return {k: {o: _fig(*counts[k].get(o, [0, 0])) for o in names} for k in sorted(counts)}


def _phase_durations(group: list[dict]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in group:
        for p in runs_report._list(r.get("phases")):
            if not isinstance(p, dict):
                continue
            a, b = runs_report._ts(p.get("started_at")), runs_report._ts(p.get("ended_at"))
            if a is not None and b is not None:
                out.setdefault(_text(p.get("name")), []).append((b - a).total_seconds())
    return out


def _phases(cur: list[dict], prev: list[dict]) -> dict:
    c, p = _phase_durations(cur), _phase_durations(prev)
    out = {}
    for name in sorted(set(c) | set(p)):
        def stat(d, fn):
            return float(fn(d[name])) if d.get(name) else None
        out[name] = {"count": _fig(len(c.get(name, [])), len(p.get(name, []))),
                     "median_s": _fig(stat(c, statistics.median), stat(p, statistics.median)),
                     "max_s": _fig(stat(c, max), stat(p, max))}
    return out


def _ci(cur: list[dict], prev: list[dict]) -> dict:
    def rounds(g):
        return sum(r["ci_rounds"] for r in g if _num(r.get("ci_rounds")))

    def reruns(g):
        return sum(len(_reruns(r)) for r in g)

    def per(x, g):
        return round(x / len(g), 3) if g else None
    rc, rp, kc, kp = rounds(cur), rounds(prev), reruns(cur), reruns(prev)
    return {"rounds": _fig(rc, rp), "reruns": _fig(kc, kp),
            "rounds_per_run": _fig(per(rc, cur), per(rp, prev)), "reruns_per_run": _fig(per(kc, cur), per(kp, prev))}


def _escalations(cur: list[dict], prev: list[dict]) -> dict:
    out: dict = {}
    for cause in CAUSES:
        def inc(g):
            return [r for r in g if (e := _escalation(r)) is not None and _cause(e) == cause]
        c, p = inc(cur), inc(prev)
        groups: dict[str, list[dict]] = {}
        for r in c:
            groups.setdefault(_text(_escalation(r).get("reason")), []).append(r)
        ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), -sum(_seconds(r) for r in kv[1]), kv[0]))
        reasons = [{"rank": i, "reason": reason, "runs": len(rs), "duration_s": float(sum(_seconds(r) for r in rs)),
                    "run_ids": sorted({str(r.get("run_id")) for r in rs})[:MAX_RUN_IDS]}
                   for i, (reason, rs) in enumerate(ranked, 1)]
        out[cause] = {"count": _fig(len(c), len(p)), "reasons": reasons}
    return out


def _rerun_view(cur: list[dict], prev: list[dict]) -> dict:
    def reasons(g):
        n: dict[str, int] = {}
        for r in g:
            for x in _reruns(r):
                k = x.get("reason") if x.get("reason") in RERUN_REASONS else UNKNOWN
                n[k] = n.get(k, 0) + 1
        return n
    c, p = reasons(cur), reasons(prev)
    names = RERUN_REASONS + ((UNKNOWN,) if UNKNOWN in c or UNKNOWN in p else ())
    by_reason = {k: _fig(c.get(k, 0), p.get(k, 0)) for k in names}

    def checks(g):
        n: dict[str, list] = {}
        for r in g:
            for x in _reruns(r):
                e = n.setdefault(_text(x.get("check")), [0, set()])
                e[0] += 1
                e[1].add(str(r.get("run_id")))
        return n
    cc, pc = checks(cur), checks(prev)
    ranked = sorted(cc, key=lambda k: (-cc[k][0], k))
    by_check = [{"rank": i, "check": k, "count": _fig(cc[k][0], pc.get(k, [0])[0]), "run_ids": sorted(cc[k][1])[:MAX_RUN_IDS]}
                for i, k in enumerate(ranked, 1)]
    return {"by_reason": by_reason, "by_check": by_check}


def _repos(cur: list[dict], prev: list[dict]) -> tuple[dict, list[dict]]:
    def per_week(g):
        shapes: dict[str, dict[str, int]] = {}
        for r in g:
            if isinstance(r.get("repo"), str) and r["repo"]:
                s = shapes.setdefault(r["repo"], {})
                sh = _shape_of(r)
                s[sh] = s.get(sh, 0) + 1
        return {repo: min(s, key=lambda k: (-s[k], k)) for repo, s in shapes.items()}, {repo: sum(s.values()) for repo, s in shapes.items()}
    (cs, cn), (ps, _) = per_week(cur), per_week(prev)
    c_by, p_by = {}, {}
    for shape in cs.values():
        c_by[shape] = c_by.get(shape, 0) + 1
    for shape in ps.values():
        p_by[shape] = p_by.get(shape, 0) + 1
    by_shape = {k: _fig(c_by.get(k, 0), p_by.get(k, 0)) for k in sorted(set(c_by) | set(p_by))}
    lst = [{"repo": repo, "shape": cs[repo], "runs": cn[repo]} for repo in sorted(cs)]
    return by_shape, lst


def _label_names(issue: dict) -> set[str]:
    return {str(x.get("name")) if isinstance(x, dict) else str(x) for x in issue.get("labels") or []}


def _issues(auto_issues: list[dict], week: str) -> list[dict]:
    start, end = week_bounds(week)
    out = []
    for i in auto_issues:
        labels = _label_names(i)
        m = _SIGNATURE.search(str(i.get("body") or ""))
        if "auto-filed" not in labels or not m:
            continue
        stamps = [runs_report._ts(i.get("created_at"))]
        for c in i.get("comments") or []:
            if isinstance(c, dict) and str(c.get("body") or "").startswith("**Occurrence "):
                stamps.append(runs_report._ts(c.get("created_at")))
        stamps = [s for s in stamps if s is not None]
        in_week = sum(1 for s in stamps if start <= s < end)
        if not in_week:
            continue
        out.append({"number": i["number"], "title": str(i.get("title") or ""), "url": str(i.get("url") or ""),
                    "state": str(i.get("state") or "open"), "routed": bool(labels & triage.DECISION_LABELS),
                    "occurrences_week": in_week, "occurrences_total": len(stamps), "signature": m.group(1)})
    out.sort(key=lambda x: (-x["occurrences_week"], x["number"]))
    return out


def _diff(cur, prev):
    if isinstance(cur, dict):
        return {k: _diff(v, prev.get(k) if isinstance(prev, dict) else None) for k, v in cur.items()}
    if _num(cur) and _num(prev):
        return round(cur - prev, 3)
    return None


def _agents(cur: list[dict], prev: list[dict], week: str, store: str) -> dict:
    start, end = week_bounds(week)

    def agg(g, now):
        return runs_report.aggregate_agents(g, malformed=0, buffered=0, since_days=7, repo=None, agent=None, shape=None,
                                            by_version=False, store=store, now=now)
    ident = lambda r: (r["agent"], r["shape"], r["model"])  # noqa: E731
    before = {ident(r): r for r in agg(prev, start)["rows"]}
    rows = []
    for r in agg(cur, end)["rows"]:
        p = before.get(ident(r))
        rows.append({"agent": r["agent"], "shape": r["shape"], "model": r["model"], "model_ids": r["model_ids"],
                     "runs": _fig(r["runs"], p["runs"] if p else 0), "few_runs": r["few_runs"],
                     "incomplete_runs": r["incomplete_runs"], "metrics": r["metrics"],
                     "previous": p["metrics"] if p else None, "diff": _diff(r["metrics"], p["metrics"] if p else None),
                     "top_causes": r["top_causes"]})
    return {"rows": rows}


def _alias(names: list[str], prefix: str) -> dict[str, str]:
    return {n: (n if SAFE.match(n) else f"{prefix}{i}") for i, n in enumerate(sorted(names), 1)}


def _leaves(tree, path=""):
    if isinstance(tree, dict):
        for k, v in tree.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif _num(tree):
        yield path, tree


def _index(rep: dict, side: str = "current") -> dict:
    """The evidence index (`ref -> number`) of one side of the figures: the covered week, or the week before."""
    ev: dict = {}

    def put(ref, value):
        if value is not None:
            ev[ref] = value
    put("records", rep["records"][side])
    kinds = _alias(list(rep["runs"]), "kind")
    for kind, outs in rep["runs"].items():
        for o, f in outs.items():
            put(f"runs.{kinds[kind]}.{o}", f[side])
    names = _alias(list(rep["phases"]), "phase")
    for name, st in rep["phases"].items():
        for k in ("count", "median_s", "max_s"):
            put(f"phases.{names[name]}.{k}", st[k][side])
    for k, f in rep["ci"].items():
        put(f"ci.{k}", f[side])
    for cause, e in rep["escalations"].items():
        put(f"escalations.{cause}", e["count"][side])
        if side == "current":
            for r in e["reasons"]:
                put(f"escalations.{cause}.reason{r['rank']}", r["runs"])
    for k, f in rep["reruns"]["by_reason"].items():
        put(f"reruns.{k}", f[side])
    for c in rep["reruns"]["by_check"]:
        put(f"reruns.check{c['rank']}", c["count"][side])
    for shape, f in rep["repos"]["by_shape"].items():
        put(f"repos.{shape}", f[side])
    if side == "current":
        for i in rep["issues"]:
            put(f"issues.#{i['number']}", i["occurrences_week"])
    for r in rep["agents"]["rows"]:
        base = f"agents.{r['agent']}|{r['shape']}|{r['model']}"
        put(f"{base}.runs", r["runs"][side])
        tree = r["metrics"] if side == "current" else r["previous"]
        for path, v in _leaves(tree or {}):
            put(f"{base}.{path}", v)
    return ev


def _evidence(rep: dict) -> dict:
    return _index(rep, "current")


def previous_index(report: dict) -> dict:
    """The same refs with the previous week's value, where the report has one."""
    return _index(report, "previous")


def build(records: list[dict], *, auto_issues: list[dict], open_issues: list[dict], specs: list[dict], week: str, store: str,
          generated_at: str, malformed: int = 0) -> dict:
    cur, prev = _split(records, week)
    start, end = week_bounds(week)
    by_shape, repo_list = _repos(cur, prev)
    specs_seen = sorted({r["spec"] for r in cur + prev if isinstance(r.get("spec"), str) and r["spec"]})
    issues = _issues(auto_issues, week)
    agents = _agents(cur, prev, week, store)
    no_data = [name for name, empty in (("runs", not cur), ("agents", not agents["rows"]), ("issues", not issues)) if empty]
    rep: dict = {
        "schema": SCHEMA, "week": week, "since": start.date().isoformat(), "until": (end - datetime.timedelta(days=1)).date().isoformat(),
        "previous_week": previous_week(week), "generated_at": generated_at, "store": store,
        "records": {"current": len(cur), "previous": len(prev), "malformed": malformed},
        "repos": {"by_shape": by_shape, "list": repo_list, "specs": specs_seen},
        "runs": _runs(cur, prev), "phases": _phases(cur, prev), "ci": _ci(cur, prev),
        "escalations": _escalations(cur, prev), "reruns": _rerun_view(cur, prev),
        "issues": issues, "agents": agents, "no_data": no_data,
        "context": {"specs": specs, "open_issues": open_issues},
    }
    rep["evidence"] = _evidence(rep)
    return rep


# ---------------- names ----------------

def private_names(report: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    for r in report.get("repos", {}).get("list", []):
        names[r["repo"]] = "<repo>"
    for s in report.get("repos", {}).get("specs", []):
        names[s] = "<spec>"
    if report.get("store"):
        names[report["store"]] = "<run-store>"
    return names


def leaks(text: str, report: dict) -> list[str]:
    low = text.lower()
    return [n for n in private_names(report) if n and n.lower() in low]


# ---------------- rendering ----------------

def _a(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _n(x) -> str:
    return "n/a" if x is None else str(x)


def _d(x) -> str:
    return "n/a" if x is None else runs_report._dur(x)


def _cell(f: dict, fmt=_n) -> str:
    return f"{fmt(f['current'])} (prev {fmt(f['previous'])})"


AGENT_COLUMNS = {
    "architect": (("out_of_plan", "out-of-plan files"), ("merge_conflicts", "merge conflicts"), ("replans", "re-plans")),
    "coder": (("fix_rounds", "fix rounds"), ("red_ci", "red-CI rounds"), ("findings", "findings"),
              ("findings.after_fix", "findings after fix"), ("refused_test_diffs", "refused test diffs")),
    "quality": (("refused_test_diffs", "refused test diffs"),),
    "tester": (("tester_events", "tester events"),),
}


def _avg_of(tree: dict | None, path: str):
    node = tree
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node.get("avg") if isinstance(node, dict) else None


def _agent_cell(row: dict, path: str) -> str:
    cur = _avg_of(row["metrics"], path)
    prev = _avg_of(row["previous"], path) if row["previous"] is not None else None
    diff = _avg_of(row["diff"], path) if row["diff"] is not None else None
    if prev is None:
        return f"{_a(cur)} (prev n/a)"
    return f"{_a(cur)} (prev {_a(prev)}, {'n/a' if diff is None else f'{diff:+.2f}'})"


def _render(report: dict, proposals_md: str | None, public: bool) -> str:
    r = report
    kinds = _alias(list(r["runs"]), "kind") if public else {k: k for k in r["runs"]}
    phases = _alias(list(r["phases"]), "phase") if public else {k: k for k in r["phases"]}
    nd = set(r["no_data"])
    none = NO_DATA
    n = r["records"]["current"]
    head = f"Weekly retro {r['week']} ({r['since']} to {r['until']}): "
    head += f"{n} run(s) in {len(r['repos']['list'])} repo(s)" if n else "no runs this week"
    out = [head]
    if proposals_md:
        out.append(proposals_md.rstrip("\n"))

    out.append("## Phases (median / longest)")
    if "runs" in nd or not r["phases"]:
        out.append(none)
    else:
        out += ["| phase | runs | median | longest |", "|---|---|---|---|"]
        for name, p in r["phases"].items():
            out.append(f"| {phases[name]} | {_cell(p['count'])} | {_cell(p['median_s'], _d)} | {_cell(p['max_s'], _d)} |")

    out.append("## Runs")
    if "runs" in nd or not r["runs"]:
        out.append(none)
    else:
        cols = list(next(iter(r["runs"].values())))
        out += ["| kind | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
        for kind, outs in r["runs"].items():
            out.append(f"| {kinds[kind]} | " + " | ".join(_cell(outs[c]) for c in cols) + " |")

    out.append("## Repos per shape")
    if "runs" in nd:
        out.append(none)
    else:
        out += ["| shape | repos |", "|---|---|"]
        out += [f"| {s} | {_cell(f)} |" for s, f in r["repos"]["by_shape"].items()]
        if not public:
            out += ["", "| repo | shape | runs |", "|---|---|---|"]
            out += [f"| {x['repo']} | {x['shape']} | {x['runs']} |" for x in r["repos"]["list"]]

    out.append("## CI")
    if "runs" in nd:
        out.append(none)
    else:
        ci = r["ci"]
        out.append(f"CI rounds per run {_cell(ci['rounds_per_run'], _a)} · reruns per run {_cell(ci['reruns_per_run'], _a)} · "
                   f"rounds {_cell(ci['rounds'])} · reruns {_cell(ci['reruns'])}")

    out.append("## Escalations")
    if "runs" in nd:
        out.append(none)
    else:
        for cause, e in r["escalations"].items():
            out.append(f"{cause}: {_cell(e['count'])}")
            for x in e["reasons"]:
                label = f"reason {x['rank']}" if public else x["reason"]
                out.append(f"  {x['rank']}. {label} — {x['runs']} run(s), {_d(x['duration_s'])} ({', '.join(x['run_ids'])})")

    out.append("## Reruns")
    if "runs" in nd:
        out.append(none)
    else:
        out.append("by reason: " + ", ".join(f"{k} {_cell(f)}" for k, f in r["reruns"]["by_reason"].items()))
        for x in r["reruns"]["by_check"]:
            label = f"check {x['rank']}" if public else x["check"]
            out.append(f"  {x['rank']}. {label} — {_cell(x['count'])} ({', '.join(x['run_ids'])})")

    out.append("## Platform issues")
    if "issues" in nd:
        out.append(none)
    else:
        out += ["| issue | title | this week | total | state | routed |", "|---|---|---|---|---|---|"]
        for i in r["issues"]:
            out.append(f"| #{i['number']} | {' '.join(i['title'].split())} | {i['occurrences_week']} | {i['occurrences_total']} | "
                       f"{i['state']} | {'yes' if i['routed'] else 'no'} |")

    out.append("## Agents")
    if "agents" in nd:
        out.append(none)
    else:
        roles: dict[str, list[dict]] = {}
        for row in r["agents"]["rows"]:
            roles.setdefault(row["agent"].rpartition(":")[2], []).append(row)
        for role, rows in roles.items():
            cols = AGENT_COLUMNS.get(role, ())
            out += [f"### {role}", "| agent | shape | model | runs | " + " | ".join(label for _, label in cols) + " |",
                    "|---" * (4 + len(cols)) + "|"]
            for row in rows:
                runs = _cell(row["runs"]) + (", few runs" if row["few_runs"] else "")
                out.append(f"| {row['agent']} | {row['shape']} | {row['model']} | {runs} | "
                           + " | ".join(_agent_cell(row, path) for path, _ in cols) + " |")
            if not public:
                for row in rows:
                    causes = "; ".join(f"{c['count']}× {c['cause']} ({c['run_id']})" for c in row["top_causes"]) or "none"
                    out.append(f"{row['agent']} on {row['shape']} causes: {causes}")

    out += ["---", f"_Generated by `cplat retro` (spec 090) at {r['generated_at']}. Repos appear as counts per shape, runs by run id._"]
    body = "\n".join(out) + "\n"
    if public:
        body = autoissue.scrub(body, private_names(report))
    return body


def render_text(report: dict) -> str:
    return _render(report, None, False)


def render_private(report: dict, proposals_md: str) -> str:
    return _render(report, proposals_md, False)


def render_public(report: dict, proposals_md: str) -> str:
    return _render(report, proposals_md, True)
