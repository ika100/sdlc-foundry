"""`cplat platform runs benchmark system-ship [--reset-first] [--plugins DIR] [--repeat N] [--model M]` (spec 156): one fixed
system spec shipped with `/system:ship <spec> --until repos` through `cplat headless` on a fixed sample system (a gitops repo
and three components, benchmark/tasks.json `system-ship`). Each run is a `benchmark` record with per-repo numbers; every sample
repo is reset to its pinned revision afterwards. The sample differs from the journey's system on purpose (AC-156.6).

The folders are siblings in one folder (`--dir`, default <state dir>/benchmark/system-ship/), as `/system:ship` clones a component
next to its gitops repo; Claude Code must trust each of them (a trusted parent folder does not count).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import statistics
from pathlib import Path

import runs
import runs_bench as rb
import transcripts
import usage_cost
from core import PlatformError

WORKFLOW = "system-ship"
ACTIVE_GAP_S = 120.0     # calls closer than this count as one stretch of agent work


def _calls(sessions: list[transcripts.Session], start: datetime.datetime, end: datetime.datetime) -> list[transcripts.Call]:
    return [c for s in sessions for c in s.calls if start <= c.at <= end]


def _span(calls: list[transcripts.Call]) -> float:
    return (max(c.at for c in calls) - min(c.at for c in calls)).total_seconds() if calls else 0.0


def _active(calls: list[transcripts.Call]) -> float:
    """Seconds of agent work: the gaps between consecutive calls, each gap counted only when shorter than ACTIVE_GAP_S."""
    at = sorted(c.at for c in calls)
    return sum(g for g in ((b - a).total_seconds() for a, b in zip(at, at[1:])) if g < ACTIVE_GAP_S)


def _parallel(calls: list[transcripts.Call]) -> int:
    """The most subagents at work at the same time (each from its first to its last call)."""
    spans: dict[str, list[datetime.datetime]] = {}
    for c in calls:
        if c.agent is not None:
            spans.setdefault(c.agent, []).append(c.at)
    edges = sorted([(min(v), 1) for v in spans.values()] + [(max(v), -1) for v in spans.values()], key=lambda e: (e[0], -e[1]))
    best = cur = 0
    for _, step in edges:
        cur += step
        best = max(best, cur)
    return best


def _criteria(clone: Path, parent: str) -> int:
    """Criteria of the repo spec the system ship wrote (its `parent:` is the system spec)."""
    for spec in sorted((clone / "docs" / "specs").glob("*/spec.md")):
        try:
            text = spec.read_text()
        except OSError:
            continue
        if re.search(rf"^parent:\s*{re.escape(parent)}\s*$", text, re.M):
            return len(re.findall(r"^- \*\*AC-\d+\.\d+\*\*", text, re.M))
    return 0


def repo_numbers(name: str, sessions: list[transcripts.Session], clone: Path, parent: str,
                 start: datetime.datetime, end: datetime.datetime) -> dict:
    calls = _calls(sessions, start, end)
    cost = usage_cost.section([(c, 1.0, None, c.role) for c in calls], usage_cost.load_prices())["totals"]
    return {"repo": name, "wall_s": round(_span(calls)), "agent_s": round(_active(calls)),
            "tokens": sum(c.input + c.output + c.cache_read + c.cache_write for c in calls),
            "cost_usd": cost.get("cost_usd"), "sessions": len({s.session_id for s in sessions if any(start <= c.at <= end for c in s.calls)}),
            "criteria": _criteria(clone, parent) if parent else 0, "parallel_subagents": _parallel(calls)}


def run_numbers(per_repo: list[dict], wall_s: float) -> dict:
    """AC-156.4: the whole run, and the overlap: the components' wall clocks summed over the run's (1.0 = one at a time)."""
    comps = [r for r in per_repo if not r.get("gitops")]
    costs = [r["cost_usd"] for r in per_repo if isinstance(r.get("cost_usd"), (int, float))]
    return {"wall_s": round(wall_s), "tokens": sum(r["tokens"] for r in per_repo),
            "cost_usd": round(sum(costs), 2) if costs else None,
            "overlap": round(sum(r["wall_s"] for r in comps) / wall_s, 2) if wall_s and comps else None}


def spread(values: list[float]) -> dict | None:
    return {"median": statistics.median(values), "low": min(values), "high": max(values), "runs": len(values)} if values else None


def compare(a: dict | None, b: dict | None) -> str:
    """AC-156.5: a difference of medians smaller than the larger spread is no gain."""
    if not a or not b:
        return "no comparison (a side has no done run)"
    diff = b["median"] - a["median"]
    width = max(a["high"] - a["low"], b["high"] - b["low"])
    if a["runs"] < 2 or b["runs"] < 2:
        return f"{diff:+.0f}, from fewer than 2 runs per side: not a result"
    if abs(diff) <= width:
        return f"{diff:+.0f}: within the spread ({width:.0f})"
    return f"{diff:+.0f}: beyond the spread ({width:.0f})"


def _project_dir(clone: Path) -> Path:
    import runs_usage
    return runs_usage.projects_root() / transcripts.cwd_slug(clone)


def _merged_since(repo: str, keep: dict) -> bool:
    try:
        prs = json.loads(rb._ok(["gh", "pr", "list", "--repo", repo, "--state", "merged", "--json", "number", "--limit", "20"]) or "[]")
    except (ValueError, RuntimeError):
        return False
    return any(isinstance(p, dict) and isinstance(p.get("number"), int) and p["number"] > keep.get("newest_pr", 0) for p in prs or [])


def _commit_spec_and_plan(task: dict, clone: Path) -> None:
    """On the branch `/system:plan` leaves them on, so the run's publish phase merges them as it would for a person."""
    rb._ok(["git", "checkout", "-q", "-b", f"docs/spec-{task['spec_id']}"], clone)
    spec = clone / "docs" / "specs" / task["spec_id"] / "spec.md"
    plan = clone / "docs" / "plan" / f"{task['spec_id']}.md"
    for src, dst in ((task["spec_file"], spec), (task["plan_file"], plan)):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rb.BENCH_DIR / src, dst)
    rb._ok(["git", "add", "docs"], clone)
    rb._ok(["git", *rb.GIT_IDENTITY, "commit", "-m", f"docs(spec): {task['spec_id']} and its plan (benchmark)"], clone)


def _repos(task: dict) -> list[dict]:
    sys_ = task["system"]
    return [{**sys_["gitops"], "gitops": True}] + [dict(c) for c in sys_["components"]]


def prepare(task: dict, base: Path, reset_first: bool) -> dict[str, dict]:
    """Clone (or reuse) every sample repo, check trust, reset what is off its pin; returns name → {repo, rev, clone, keep}."""
    out: dict[str, dict] = {}
    for r in _repos(task):
        repo, rev = r["repo"], r["rev"]
        url, name = f"https://github.com/{repo}", repo.split("/", 1)[1]
        clone = base / name
        try:
            now = rb._remote_main(url)
        except RuntimeError as e:
            raise PlatformError(f"sample repo {repo} cannot be reached: {e}") from None
        if now != rev and not reset_first:
            raise PlatformError(f"sample repo {repo}: main is at {now[:7] or 'nothing'}, not the pinned {rev[:7]}",
                                hint=f"cplat platform runs benchmark {WORKFLOW} --reset-first")
        try:
            rb._prepare(url, rev, {}, clone, spec=False)
            if not rb.trusted(clone):
                raise PlatformError(f"the benchmark folder {clone} is not trusted in Claude Code, so its permission rules would be ignored",
                                    hint=f"cd {clone} && claude   (accept the trust dialog, then /exit), and run the benchmark again")
            if now != rev or reset_first:          # also the branches and PRs a stopped run left behind
                rb.reset_sample(repo, rev, clone)
            keep = rb.snapshot(repo, clone)
        except RuntimeError as e:
            raise PlatformError(f"sample repo {repo} could not be prepared: {e}") from None
        out[name] = {"repo": repo, "rev": rev, "clone": clone, "keep": keep, "gitops": bool(r.get("gitops"))}
    return out


SESSION_WAIT_S = 3600.0


def wait_for_sessions(gitops: Path, limit: float = SESSION_WAIT_S, interval: float = 20.0) -> list[str]:
    """The repo sessions a system ship started keep running after it ends escalated (spec 155, AC-155.6): wait for them, and
    stop what still runs after `limit`, before the sample repos are reset under them. Returns the repos it had to stop."""
    import os
    import signal
    import time

    import appship_proc
    import appship_state
    try:
        st = appship_state.load_state(gitops)
        if st is None:                                   # finished: the newest archived state
            done = sorted(appship_state.state_path(gitops).parent.glob("cplat-app-ship-*-[0-9]*.json"))
            st = json.loads(done[-1].read_text()) if done else {}
    except Exception:  # noqa: BLE001
        st = {}
    pids = {rid: (e.get("proc") or {}).get("pid") for rid, e in (st.get("repos") or {}).items() if (e.get("proc") or {}).get("pid")}
    end = time.monotonic() + limit
    while any(appship_proc.alive(p) for p in pids.values()) and time.monotonic() < end:
        time.sleep(interval)
    stopped = [rid for rid, p in pids.items() if appship_proc.alive(p)]
    for rid in stopped:
        try:
            os.killpg(pids[rid], signal.SIGTERM)       # the session runs in its own process group (start_new_session)
        except OSError:
            pass
    return stopped


def reset_all(repos: dict[str, dict]) -> tuple[str, str | None]:
    notes = []
    for name, r in repos.items():
        try:
            rb.reset_sample(r["repo"], r["rev"], r["clone"], r["keep"])
        except Exception as e:  # noqa: BLE001
            notes.append(f"{name}: {type(e).__name__}: {e}"[:200])
    return ("failed", "; ".join(notes)) if notes else ("done", None)


def one_run(task: dict, base: Path, ns: argparse.Namespace, n: int) -> dict:
    repos = prepare(task, base, ns.reset_first)
    gitops = next(r for r in repos.values() if r["gitops"])
    _commit_spec_and_plan(task, gitops["clone"])
    plugin_flags, plugin_info = rb.plugin_args(ns.plugins, gitops["clone"]) if ns.plugins else ([], None)
    platform = Path(ns.plugins).resolve().parent if ns.plugins else None
    model_flags = ["--model", ns.model] if ns.model else []
    rid = runs.start("benchmark", repo=gitops["repo"], mode="headless")
    if rid:                               # the usage section reads every sample folder's sessions (one project dir each)
        import runs_usage
        for r in repos.values():
            runs_usage.register(rid, mode="own", project_dir=str(_project_dir(r["clone"])))
    started = runs.utcnow()
    outcome, check = "failed", None
    try:
        runs.phase(rid, f"benchmark:{WORKFLOW}")
        out = rb._run_headless(["--repo", str(gitops["clone"]), "--max-runs", str(task["max_runs"]),
                                "--max-minutes", str(task["max_minutes"]), *model_flags, *plugin_flags, task["prompt"]], rid, platform)
        wait_for_sessions(gitops["clone"])
        missing = [r["repo"] for r in repos.values() if not r["gitops"] and not _merged_since(r["repo"], r["keep"])]
        if out != "done":
            check = "the system ship did not finish"
        elif missing:
            check = "no new merged PR in " + ", ".join(missing)
        else:
            outcome = "done"
    finally:
        ended = runs.utcnow()
        parent = f"{gitops['repo']}:{task['spec_id']}"
        per_repo = []
        for name, r in repos.items():
            sessions = transcripts.read_project_dir(_project_dir(r["clone"]), since=started, deadline=lambda: False)
            per_repo.append({**repo_numbers(name, sessions, r["clone"], "" if r["gitops"] else parent, started, ended),
                             "gitops": r["gitops"]})
        whole = run_numbers(per_repo, (ended - started).total_seconds())
        runs.phase(rid, "benchmark:reset")
        reset, note = reset_all(repos)
        runs.finish(rid, outcome, fields={
            "benchmark": {"workflow": WORKFLOW, "task_version": task["task_version"], "sample_repo": gitops["repo"],
                          "sample_rev": gitops["rev"], "reset": reset, "reset_note": note, "result_check": check,
                          "arm": "baseline", "plugins": plugin_info, "coordinator_model": ns.model or "settings",
                          "system": {**whole, "repos": per_repo}}})
    if reset == "failed":
        raise PlatformError(f"reset of the sample system failed: {note}; the benchmark record was written",
                            hint=f"cplat platform runs benchmark {WORKFLOW} --reset-first")
    return {"outcome": outcome, "check": check, **whole, "repos": per_repo, "plugins": plugin_info}


def _minutes(s: float) -> str:
    return f"{s / 60:.1f} min"


def report(results: list[dict]) -> list[str]:
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"run {i}: {r['outcome']}, {_minutes(r['wall_s'])}, {r['tokens']} tokens, est. USD {r['cost_usd']}, "
                     f"overlap {r['overlap']}" + (f"; {r['check']}" if r["check"] else ""))
        for p in r["repos"]:
            lines.append(f"  {p['repo']:<24} wall {_minutes(p['wall_s'])}, agents {_minutes(p['agent_s'])}, {p['tokens']} tokens, "
                         f"{p['sessions']} session(s), {p['criteria']} criteria, {p['parallel_subagents']} subagent(s) at once")
    done = [r for r in results if r["outcome"] == "done"]
    for key, label in (("wall_s", "wall clock (s)"), ("tokens", "tokens")):
        s = spread([float(r[key]) for r in done])
        if s:
            lines.append(f"{label}: median {s['median']:.0f}, spread {s['low']:.0f} to {s['high']:.0f} over {s['runs']} done run(s)")
    return lines


def stored(task_version: int, since_days: int) -> dict[str, dict]:
    """AC-156.5: the done records of this task version in the run store, per plugins tree: spreads of wall clock and tokens."""
    import runs_report
    import runs_usage_report
    slug = runs.configured_repo()
    if slug is None:
        raise PlatformError("no run store configured (CPLAT_RUNS_REPO is not set)", hint="cplat platform runs init <owner/name>")
    today = runs.utcnow().date()
    files = runs.open_store(slug).read([today - datetime.timedelta(days=n) for n in range(since_days, -1, -1)])
    groups: dict[str, dict[str, list[float]]] = {}
    for r in runs_report.parse([text for _, text in files])[0]:
        b = r.get("benchmark") if isinstance(r.get("benchmark"), dict) else {}
        s = b.get("system") if isinstance(b.get("system"), dict) else None
        if r.get("outcome") != "done" or b.get("workflow") != WORKFLOW or b.get("task_version") != task_version or not s:
            continue
        label = runs_usage_report.plugins_label(b["plugins"]) if isinstance(b.get("plugins"), dict) else "installed"
        g = groups.setdefault(label, {"wall_s": [], "tokens": [], "ended": []})
        g["wall_s"].append(float(s.get("wall_s") or 0))
        g["tokens"].append(float(s.get("tokens") or 0))
        g["ended"].append(str(r.get("ended_at") or ""))
    return {k: {"wall_s": spread(v["wall_s"]), "tokens": spread(v["tokens"]), "last": max(v["ended"])} for k, v in groups.items()}


def stored_report(groups: dict[str, dict]) -> list[str]:
    order = sorted(groups, key=lambda k: groups[k]["last"])
    lines = [f"{k}: wall clock median {groups[k]['wall_s']['median'] / 60:.1f} min ({groups[k]['wall_s']['low'] / 60:.1f} to "
             f"{groups[k]['wall_s']['high'] / 60:.1f}), tokens median {groups[k]['tokens']['median']:.0f}, {groups[k]['wall_s']['runs']} run(s)"
             for k in order]
    if len(order) >= 2:
        a, b = groups[order[-2]], groups[order[-1]]
        lines.append(f"{order[-1]} against {order[-2]}: wall clock (s) {compare(a['wall_s'], b['wall_s'])}; "
                     f"tokens {compare(a['tokens'], b['tokens'])}")
    return lines or ["no done system-ship benchmark records for this task version"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog=f"cplat platform runs benchmark {WORKFLOW}", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset-first", action="store_true", help="put every sample repo back to its pinned revision before starting")
    ap.add_argument("--model", help="coordinator model (sonnet, opus, haiku); else the settings files")
    ap.add_argument("--plugins", metavar="DIR", help="run with the plugins in DIR (this worktree's plugins/) instead of the installed ones")
    ap.add_argument("--dir", default=os.environ.get("CPLAT_BENCH_SYSTEM_DIR"),
                    help="the folder that holds the four sample clones, each trusted in Claude Code "
                         "(default $CPLAT_BENCH_SYSTEM_DIR, else <state dir>/benchmark/system-ship)")
    ap.add_argument("--repeat", type=int, default=1, help="runs in a row, each recorded on its own (spec 156: 3 to judge a change)")
    ap.add_argument("--report", action="store_true", help="run nothing: the stored records per plugins tree, median and spread")
    ap.add_argument("--since", type=int, default=30, help="--report: days of records (default 30)")
    ns = ap.parse_args(argv)
    if ns.repeat < 1:
        raise PlatformError("--repeat needs at least 1")
    task = json.loads((rb.BENCH_DIR / "tasks.json").read_text())["workflows"][WORKFLOW]
    if ns.report:
        for line in stored_report(stored(task["task_version"], ns.since)):
            print(line)
        return 0
    base = Path(ns.dir).expanduser() if ns.dir else runs.state_dir() / "benchmark" / WORKFLOW
    results = [one_run(task, base, ns, n) for n in range(ns.repeat)]
    print(f"benchmark {WORKFLOW} v{task['task_version']}" + (f", plugins {results[0]['plugins'].get('commit', '')[:7]}"
                                                             if results[0].get("plugins") else ", installed plugins"))
    for line in report(results):
        print(line)
    return 0 if all(r["outcome"] == "done" for r in results) else 1
