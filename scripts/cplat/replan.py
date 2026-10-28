"""Spec 094: the rules of a re-plan after a merge conflict. A library for `cplat component build` (buildcmd.py).

The re-plan history is the git history of the feature branch: every amended plan is one commit with `Replan-Spec` and
`Replan-Task` trailers. Only the conflicts of the current batch that have no re-plan commit yet are kept in
`<git common dir>/cplat-replan.json` (local, never committed).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import core
import runs
import runs_agents
import spec as specmod
import yaml
from core import PlatformError

CAP = 3
PENDING_FILE = "cplat-replan.json"
KEPT_KEYS = ("files", "depends_on", "parallel_safe")
_TRAILER = re.compile(r"^(\S+) with=(\S+) branch=(\S+) paths=(.*)$")
_MISSING = object()


# ---------------- git ----------------

def _git(repo: Path, *args: str, check: bool = True, strip: bool = True) -> str:
    proc = core.run(["git", "-C", str(repo), *args], check=False)
    if check and proc.returncode != 0:
        last = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise PlatformError(f"git {args[0]} failed: {last[-1] if last else 'exit ' + str(proc.returncode)}")
    return proc.stdout.strip() if strip else proc.stdout.rstrip("\n")


def short(sha: str) -> str:
    return sha[:7]


def _load(repo: Path, ref: str) -> specmod.Spec:
    sp = specmod.find(repo, ref)
    if not sp.plan:
        raise PlatformError(f"{sp.id} has no plan.md", hint=f"run `/component:plan {sp.number}`")
    return sp


def _tasks(sp: specmod.Spec) -> list[dict]:
    return [t for t in ((sp.plan or ({}, ""))[0].get("tasks") or []) if isinstance(t, dict)]


def _rel_dir(repo: Path, sp: specmod.Spec) -> str:
    return str(sp.dir.relative_to(repo))


# ---------------- history ----------------

def history(repo: Path, spec_id: str) -> list[dict]:
    """The re-plan commits of this spec since its `start building` commit, oldest first."""
    out = _git(repo, "log", "--format=%H%x1f%s%x1f%(trailers:unfold,only)%x1e", "HEAD")
    start = f"docs(spec): start building {spec_id}"
    found: list[dict] = []
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        sha, subject, trailers = parts[0].strip(), parts[1], parts[2]
        if subject == start:
            break
        lines = [ln.strip() for ln in trailers.splitlines() if ln.strip()]
        if f"Replan-Spec: {spec_id}" not in lines:
            continue
        tasks = []
        for ln in lines:
            if not ln.startswith("Replan-Task:"):
                continue
            m = _TRAILER.match(ln.split(":", 1)[1].strip())
            if m:
                tasks.append({"task": m.group(1), "with": None if m.group(2) == "-" else m.group(2),
                              "paths": [p for p in m.group(4).split(",") if p], "branch": m.group(3)})
        found.append({"sha": sha, "subject": subject, "tasks": tasks})
    return list(reversed(found))


def replanned_tasks(hist: list[dict]) -> list[str]:
    seen: list[str] = []
    for h in hist:
        for t in h["tasks"]:
            if t["task"] not in seen:
                seen.append(t["task"])
    return seen


def last_entry(hist: list[dict], task: str) -> tuple[dict, dict] | None:
    for h in reversed(hist):
        for t in h["tasks"]:
            if t["task"] == task:
                return h, t
    return None


# ---------------- pending conflicts ----------------

def _pending_path(repo: Path) -> Path:
    common = core.git_dir(repo)
    if common is None:
        raise PlatformError(f"{repo} is not a git repository")
    return common / PENDING_FILE


def _read_all(repo: Path) -> dict:
    try:
        data = json.loads(_pending_path(repo).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, PlatformError):
        return {}


def _write_all(repo: Path, data: dict) -> None:
    path = _pending_path(repo)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def pending(repo: Path, spec_id: str) -> dict[str, dict]:
    entries = _read_all(repo).get(spec_id)
    return entries if isinstance(entries, dict) else {}


def set_pending(repo: Path, spec_id: str, task: str, entry: dict) -> None:
    data = _read_all(repo)
    data.setdefault(spec_id, {})[task] = entry
    _write_all(repo, data)


def drop_pending(repo: Path, spec_id: str, task: str) -> None:
    data = _read_all(repo)
    if task in (data.get(spec_id) or {}):
        del data[spec_id][task]
        if not data[spec_id]:
            del data[spec_id]
        _write_all(repo, data)


def clear_pending(repo: Path, spec_id: str) -> None:
    data = _read_all(repo)
    if spec_id in data:
        del data[spec_id]
        _write_all(repo, data)


# ---------------- budget and messages ----------------

def decide(repo: Path, spec_id: str, task: str) -> tuple[str, list[dict]]:
    hist = history(repo, spec_id)
    if last_entry(hist, task):
        return "again", hist
    if len(hist) >= CAP:
        return "cap", hist
    return "aside", hist


def _who(partner: str | None) -> str:
    return partner or "unknown task"


def conflict_line(task: str, partner: str | None, paths: list[str]) -> str:
    return f"CONFLICT {task} with {_who(partner)}: {', '.join(paths)}"


def set_aside_lines(task: str, branch: str, pre: str, count: int) -> list[str]:
    return [f"SET ASIDE {task}: branch {branch} is kept for the re-run; the feature branch is unchanged at {short(pre)}",
            f"NEXT: merge the rest of the batch, then re-plan (build re-plans used: {count} of {CAP})"]


def escalate_again(task: str, partner: str | None, paths: list[str], hist: list[dict]) -> str:
    found = last_entry(hist, task)
    assert found is not None
    h, before = found
    return (f"ESCALATE: {task} conflicted again after its re-plan: now with {_who(partner)} on {', '.join(paths)}; "
            f"before with {_who(before['with'])} on {', '.join(before['paths'])}; "
            f"re-plan commit {short(h['sha'])} \"{h['subject']}\". "
            "A task is re-planned once. Conflicts are never resolved by hand.")


def escalate_cap(task: str, partner: str | None, paths: list[str], hist: list[dict]) -> str:
    commits = "; ".join(f"{short(h['sha'])} \"{h['subject']}\"" for h in hist)
    return (f"ESCALATE: the cap of {CAP} re-plans per build was reached; {task} conflicts with {_who(partner)} "
            f"on {', '.join(paths)}. Earlier re-plan commits: {commits}. Conflicts are never resolved by hand.")


# ---------------- the amended plan ----------------

def _same(a: object, b: object) -> bool:
    return a == b


def check_amended(repo: Path, spec_id: str) -> list[str]:
    """Steps 1-4 of `replan-commit`, in order; the first failing step ends the check."""
    sp = _load(repo, spec_id)
    if not pending(repo, sp.id):
        return ["nothing to re-plan: no pending conflict"]
    rel_dir = _rel_dir(repo, sp)
    plan_rel = f"{rel_dir}/plan.md"
    changed = []
    for ln in _git(repo, "status", "--porcelain", "--untracked-files=all", strip=False).splitlines():
        p = ln[3:].split(" -> ")[-1].strip().strip('"')
        if p and p != plan_rel:
            changed.append(p)
    if changed:
        return [f"the re-plan may change only plan.md; also changed: {', '.join(changed)}"]
    shown = core.run(["git", "-C", str(repo), "show", f"HEAD:{plan_rel}"], check=False)
    m = specmod.FRONT.match(shown.stdout) if shown.returncode == 0 else None
    if not m:
        return [f"{plan_rel} is not readable at HEAD"]
    try:
        old = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        return [f"{plan_rel} at HEAD is not valid YAML: {e}"]
    new = sp.plan[0] if sp.plan else {}
    errs: list[str] = []
    for k in sorted((set(old) | set(new)) - {"tasks"}):
        if not _same(old.get(k, _MISSING), new.get(k, _MISSING)):
            errs.append(f"{k} changed")
    old_t = {t.get("id"): t for t in (old.get("tasks") or []) if isinstance(t, dict)}
    new_t = {t.get("id"): t for t in (new.get("tasks") or []) if isinstance(t, dict)}
    added = [i for i in new_t if i not in old_t]
    removed = [i for i in old_t if i not in new_t]
    if added:
        errs.append("tasks added: " + ", ".join(map(str, added)))
    if removed:
        errs.append("tasks removed: " + ", ".join(map(str, removed)))
    for tid, o in old_t.items():
        n = new_t.get(tid)
        if n is None:
            continue
        if o.get("done"):
            if o != n:
                errs.append(f"task {tid} is done and changed")
            continue
        for k in sorted((set(o) | set(n)) - set(KEPT_KEYS)):
            if not _same(o.get(k, _MISSING), n.get(k, _MISSING)):
                errs.append(f"task {tid}: {k} changed (only files, depends_on and parallel_safe of tasks that are not "
                            "done may change)")
    if errs:
        return errs
    return specmod.check(sp)


def _plan_order(sp: specmod.Spec, tasks: list[str]) -> list[str]:
    ids = [t.get("id") for t in _tasks(sp)]
    return sorted(tasks, key=lambda t: ids.index(t) if t in ids else len(ids))


def commit(repo: Path, spec_id: str) -> str:
    """Commit the amended plan (only plan.md), clear the pending conflicts and record the re-plan. Returns the sha."""
    sp = _load(repo, spec_id)
    pend = pending(repo, sp.id)
    if not pend:
        raise PlatformError("nothing to re-plan: no pending conflict")
    order = _plan_order(sp, list(pend))
    files: list[str] = []
    for t in order:
        for p in pend[t].get("paths") or []:
            if p not in files:
                files.append(p)
    subject = f"chore(plan): {sp.id} re-plan {', '.join(order)} after a merge conflict"
    body = (f"Conflicting files: {', '.join(files)}\n"
            "Re-planned: " + ", ".join(f"{t} (collided with {_who(pend[t].get('with'))})" for t in order))
    trailers = [f"Replan-Spec: {sp.id}"]
    for t in order:
        e = pend[t]
        trailers.append(f"Replan-Task: {t} with={e.get('with') or '-'} branch={e.get('branch')} "
                        f"paths={','.join(e.get('paths') or [])}")
    plan_rel = f"{_rel_dir(repo, sp)}/plan.md"
    _git(repo, "add", "--", plan_rel)
    _git(repo, *core.git_identity(repo), "commit", "-q", "-s", "-m", subject, "-m", body, "-m", "\n".join(trailers),
         "--", plan_rel)
    sha = _git(repo, "rev-parse", "HEAD")
    clear_pending(repo, sp.id)
    try:
        rid = runs.current_run(repo)
        runs_agents.replan(rid, repo, order[0])
        for t in order[1:]:
            runs_agents.conflict_outcome(rid, repo, t, "re-planned")
    except Exception:  # noqa: BLE001  (recording never changes the result)
        pass
    return sha


def _record_outcome(repo: Path, tasks: list[str], outcome: str) -> None:
    try:
        rid = runs.current_run(repo)
        for t in tasks:
            runs_agents.conflict_outcome(rid, repo, t, outcome)
    except Exception:  # noqa: BLE001
        pass


def abort(repo: Path, spec_id: str, reason: str) -> str:
    """Restore the last committed plan, record `escalated`, forget the pending conflicts; return the ESCALATE line."""
    sp = _load(repo, spec_id)
    rel_dir = _rel_dir(repo, sp)
    tasks = _plan_order(sp, list(pending(repo, sp.id)))
    _git(repo, "checkout", "HEAD", "--", rel_dir)
    for p in _git(repo, "ls-files", "--others", "--exclude-standard", "--", rel_dir).splitlines():
        try:
            (repo / p).unlink()
        except OSError:
            pass
    _record_outcome(repo, tasks, "escalated")
    clear_pending(repo, sp.id)
    what = f"the re-plan of {', '.join(tasks)}" if tasks else "the re-plan"
    return (f"ESCALATE: {what} failed: {reason.strip().rstrip('.')}. The plan stays at "
            f"{short(_git(repo, 'rev-parse', 'HEAD'))}. Conflicts are never resolved by hand.")


def resolve(repo: Path, spec_id: str, task: str) -> str:
    """After the re-run of a re-planned task is merged and done: remove its set-aside branch and worktree."""
    sp = _load(repo, spec_id)
    found = last_entry(history(repo, sp.id), task)
    if found is None:
        return f"{task} was not re-planned"
    entry = found[1]
    plan_task = next((t for t in _tasks(sp) if t.get("id") == task), None)
    if plan_task is None or not plan_task.get("done"):
        raise PlatformError(f"{task} is not done", hint="finish the re-run first: `cplat spec task-done`")
    branch = entry["branch"]
    wt_path = None
    path = None
    for ln in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if ln.startswith("worktree "):
            path = ln[len("worktree "):]
        elif ln == f"branch refs/heads/{branch}" and path:
            wt_path = path
    if wt_path:
        core.run(["git", "-C", str(repo), "worktree", "remove", "--force", wt_path], check=False)
    core.run(["git", "-C", str(repo), "worktree", "prune"], check=False)
    gone = core.run(["git", "-C", str(repo), "branch", "-D", branch], check=False).returncode != 0
    _record_outcome(repo, [task], "resolved")
    drop_pending(repo, sp.id, task)
    head = f"RESOLVED {task}: " + (f"branch {branch} was already gone" if gone else f"removed branch {branch}")
    return head + (f" and worktree {wt_path}" if wt_path else "")
