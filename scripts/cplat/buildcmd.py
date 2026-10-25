"""cplat build — /svc:build Phase 2: the schedule, the conflict-safe merge and the re-plan after a conflict (spec 094).

  cplat.py build schedule <spec> [--json]
  cplat.py build merge <spec> <task> <branch> [--helper PATH]...     exit 0 merged, 3 set aside, 4 escalate
  cplat.py build state <spec> [--json]
  cplat.py build replan-commit <spec>
  cplat.py build replan-abort <spec> --reason TEXT
  cplat.py build resolved <spec> <task>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import core
import replan
import runs
import runs_agents
import spec as specmod
from core import PlatformError


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return core.run(["git", "-C", str(repo), *args], check=False)


def _out(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _load(repo: Path, ref: str) -> tuple[specmod.Spec, list[dict]]:
    sp = specmod.find(repo, ref)
    if not sp.plan:
        raise PlatformError(f"{sp.id} has no plan.md", hint=f"run `/svc:plan {sp.number}`")
    return sp, [t for t in (sp.plan[0].get("tasks") or []) if isinstance(t, dict)]


# ---------------- schedule ----------------

def schedule(repo: Path, ref: str) -> dict:
    sp, tasks = _load(repo, ref)
    done = [t["id"] for t in tasks if t.get("done") and not t.get("repo")]
    gitops = [t["id"] for t in tasks if t.get("repo")]
    remaining = [t for t in tasks if not t.get("done") and not t.get("repo")]
    ids = {t["id"] for t in remaining}
    trimmed = [{**t, "depends_on": [d for d in (t.get("depends_on") or []) if d in ids]} for t in remaining]
    by_id = {t["id"]: t for t in remaining}
    order = [t["id"] for t in remaining]
    levels = []
    for level in specmod.topo_levels(trimmed) if trimmed else []:
        batches: list[dict] = []
        for tid in sorted(level, key=order.index):
            t = by_id[tid]
            files = set(t.get("files") or [])
            if t.get("parallel_safe"):
                target = next((b for b in batches if b["safe"] and not (b["files"] & files)), None)
                if target:
                    target["tasks"].append(tid)
                    target["files"] |= files
                    continue
            batches.append({"tasks": [tid], "files": files, "safe": bool(t.get("parallel_safe"))})
        levels.append([{"tasks": b["tasks"], "parallel": len(b["tasks"]) >= 2} for b in batches])
    hist = replan.history(repo, sp.id)
    open_ids = set(order)
    return {"spec": sp.id, "done": done, "gitops": gitops,
            "replanned": [t for t in replan.replanned_tasks(hist) if t in open_ids],
            "replans": len(hist), "cap": replan.CAP, "levels": levels}


def schedule_text(data: dict) -> str:
    rows = ["| Level | Batch | Tasks | Mode |", "|---|---|---|---|"]
    for i, level in enumerate(data["levels"], 1):
        for j, b in enumerate(level, 1):
            names = ", ".join(f"{t} (re-planned)" if t in data["replanned"] else t for t in b["tasks"])
            rows.append(f"| {i} | {j} | {names} | {'parallel' if b['parallel'] else 'sequential'} |")
    parts = []
    if data["done"]:
        parts.append("done: " + ", ".join(data["done"]))
    if data["gitops"]:
        parts.append("gitops: " + ", ".join(data["gitops"]))
    parts.append(f"re-plans: {data['replans']} of {data['cap']}")
    return "\n".join([*rows, " · ".join(parts)])


# ---------------- merge ----------------

def _partner(repo: Path, tasks: list[dict], task: str, pre: str, branch: str, paths: list[str]) -> str | None:
    mb = _out(repo, "merge-base", pre, branch)
    wanted = set(paths)
    if mb:
        log = _out(repo, "log", "--first-parent", "--format=%H%x1f%s", f"{mb}..{pre}")
        for ln in log.splitlines():                                              # (a) latest first
            sha, _, subject = ln.partition("\x1f")
            m = re.match(r"merge\((\S+?)\): ", subject)
            if m and m.group(1) != task and wanted & set(_out(repo, "diff", "--name-only", f"{sha}^1", sha).splitlines()):
                return m.group(1)
    best = runs_agents._partner(tasks, task, paths)                                # (b)
    if best:
        return best
    if mb:                                                                         # (c)
        ids = [t["id"] for t in tasks if t["id"] != task]
        log = _out(repo, "log", "--no-merges", "--format=%x1e%B", f"{mb}..{pre}", "--", *paths)
        for msg in log.split("\x1e"):
            for tid in ids:
                if re.search(rf"(?<![\w-]){re.escape(tid)}(?![\w-])", msg):
                    return tid
    return None


def merge(repo: Path, ref: str, task: str, branch: str, helpers: list[str]) -> int:
    sp, tasks = _load(repo, ref)
    entry = next((t for t in tasks if t.get("id") == task), None)
    if entry is None:
        raise PlatformError(f"{sp.id}: unknown task '{task}'")
    if entry.get("done"):
        raise PlatformError(f"{task} is done already")
    if entry.get("repo"):
        raise PlatformError(f"{task} is a gitops task; it is never merged here")
    if branch.startswith("-") or _git(repo, "rev-parse", "--verify", "-q", f"{branch}^{{commit}}").returncode != 0:
        raise PlatformError(f"branch '{branch}' does not exist")
    if _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0:
        raise PlatformError("a merge is in progress", hint="run `git merge --abort`")
    if _out(repo, "status", "--porcelain", "--untracked-files=no"):
        raise PlatformError("the working tree has uncommitted changes", hint="commit the previous task first")
    pre = _out(repo, "rev-parse", "HEAD")
    proc = _git(repo, *core.git_identity(repo), "merge", "--no-ff", "--signoff", "-m", f"merge({task}): {branch}", branch)
    merging = _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0
    if proc.returncode == 0 and not merging:
        try:
            runs_agents.merged(runs.current_run(repo), repo, task, pre, helpers)
        except Exception:  # noqa: BLE001  (recording never changes the result)
            pass
        replan.drop_pending(repo, sp.id, task)
        print(f"MERGED {task} {replan.short(_out(repo, 'rev-parse', 'HEAD'))}")
        return 0
    if not merging:
        last = (proc.stderr or proc.stdout).strip().splitlines()
        raise PlatformError(f"git merge failed: {last[-1] if last else 'exit ' + str(proc.returncode)}")
    paths = _out(repo, "diff", "--name-only", "--diff-filter=U").splitlines()
    _git(repo, "merge", "--abort")
    if (_out(repo, "rev-parse", "HEAD") != pre or _out(repo, "status", "--porcelain", "--untracked-files=no")
            or _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0):
        raise PlatformError("merge --abort did not restore the feature branch (a platform defect)")
    partner = _partner(repo, tasks, task, pre, branch, paths)
    verdict, hist = replan.decide(repo, sp.id, task)
    lines = [replan.conflict_line(task, partner, paths)]
    if verdict == "aside":
        replan.set_pending(repo, sp.id, task, {"with": partner, "paths": paths, "branch": branch, "at": pre})
        lines += replan.set_aside_lines(task, branch, pre, len(hist))
        code = 3
    else:
        lines.append(replan.escalate_again(task, partner, paths, hist) if verdict == "again"
                     else replan.escalate_cap(task, partner, paths, hist))
        code = 4
    try:
        runs_agents.conflict(runs.current_run(repo), repo, task, with_task=partner, paths=paths,
                             outcome="escalated", spec=sp.id)
    except Exception:  # noqa: BLE001
        pass
    print("\n".join(lines))
    return code


# ---------------- state ----------------

def state(repo: Path, ref: str, as_json: bool) -> int:
    sp, tasks = _load(repo, ref)
    done = {t.get("id") for t in tasks if t.get("done")}
    hist = replan.history(repo, sp.id)
    pend = replan.pending(repo, sp.id)
    replans = [{"sha": h["sha"], "subject": h["subject"],
                "tasks": [{**t, "merged": t["task"] in done} for t in h["tasks"]]} for h in hist]
    pending: list[dict] = [{"task": t, "with": e.get("with"), "paths": e.get("paths") or [], "branch": e.get("branch")}
               for t, e in pend.items()]
    if as_json:
        print(json.dumps({"spec": sp.id, "cap": replan.CAP, "count": len(hist), "replans": replans, "pending": pending},
                         indent=2))
        return 0
    lines = [f"re-plans: {len(hist)} of {replan.CAP}"]
    for r in replans:
        for t in r["tasks"]:
            lines.append(f"  {replan.short(r['sha'])} {t['task']}: {', '.join(t['paths'])} (collided with "
                         f"{replan._who(t['with'])}) — re-run {'merged cleanly' if t['merged'] else 'pending'}")
    for p in pending:
        lines.append(f"pending: {p['task']} with {replan._who(p['with'])}: {', '.join(p['paths'])} (branch {p['branch']})")
    print("\n".join(lines))
    return 0


# ---------------- CLI ----------------

def main(argv: list[str]) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".")
    common.add_argument("spec")
    ap = argparse.ArgumentParser(prog="cplat build", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("schedule", "state"):
        sub.add_parser(name, parents=[common]).add_argument("--json", action="store_true")
    p = sub.add_parser("merge", parents=[common])
    p.add_argument("task")
    p.add_argument("branch")
    p.add_argument("--helper", action="append", default=[])
    sub.add_parser("replan-commit", parents=[common])
    sub.add_parser("replan-abort", parents=[common]).add_argument("--reason", required=True)
    sub.add_parser("resolved", parents=[common]).add_argument("task")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()

    if ns.cmd == "schedule":
        data = schedule(repo, ns.spec)
        print(json.dumps(data, indent=2) if ns.json else schedule_text(data))
        return 0
    if ns.cmd == "merge":
        return merge(repo, ns.spec, ns.task, ns.branch, ns.helper)
    if ns.cmd == "state":
        return state(repo, ns.spec, ns.json)
    if ns.cmd == "replan-commit":
        errs = replan.check_amended(repo, ns.spec)
        if errs:
            sid = specmod.find(repo, ns.spec).id
            for e in errs:
                print(f"ERROR: {sid}: {e}")
            print(f"{len(errs)} error(s)")
            return 1
        sha = replan.commit(repo, ns.spec)
        sid = specmod.find(repo, ns.spec).id
        last = replan.history(repo, sid)
        names = ", ".join(t["task"] for t in last[-1]["tasks"]) if last else ""
        print(f"RE-PLANNED {names} in {replan.short(sha)} (re-plans: {len(last)} of {replan.CAP})")
        print(schedule_text(schedule(repo, ns.spec)))
        return 0
    if ns.cmd == "replan-abort":
        print(replan.abort(repo, ns.spec, ns.reason))
        return 0
    print(replan.resolve(repo, ns.spec, ns.task))
    return 0
