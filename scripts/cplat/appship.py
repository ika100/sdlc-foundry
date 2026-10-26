"""`cplat system ship` — /system:ship: ship a whole product spec across the repos of its plan (spec 097, ADR-042).

Run in the gitops-app repo (`--repo DIR`, default `.`). State: <git dir>/cplat-app-ship.json (never committed).

  cplat system ship start <spec> [--max N] [--context C] [--budget KEY=VALUE]   refuse or begin/resume; prints phase, repo table and the next step
  cplat system ship status [--json]                        the state and what the scheduler does next
  cplat system ship phase <plan|publish|repos|complete|done>
  cplat system ship publish [--timeout S]                  spec and plan on main: PR merged on green checks (nothing to do when they are)
  cplat system ship next [--json]                          which repos start, run, wait, escalated; the action
  cplat system ship repo start <id>                        mark running; prints the clone path (the entry: its worktree on compose/<spec>)
  cplat system ship repo result <id>                       read the clone's finished ship, evaluate the gate (exit 1: escalated)
  cplat system ship repo escalate <id> <reason> --cause C  a repo that escalated before its ship existed (open questions)
  cplat system ship entry pr <id> --title T --body-file F  push the entry's branch and open (or reuse) its PR
  cplat system ship entry land <id> [--timeout S]          wait for all checks, merge through the merge slot
  cplat system ship complete [--timeout S]                 spec done + plan completed through a PR merged on green; prints the report
  cplat system ship escalate <reason> --cause C            end the run escalated
  cplat system ship finish                                 archive the state (an unrecorded run is recorded abandoned)
  cplat system ship gate [--max-blocks N]                  Stop hook (reads the hook's JSON on stdin)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import appship_merge
import appship_report
import appship_sched
import appship_state as state
import budget
import core
import ship
import spec as specmod
from core import PlatformError, run

DEFAULT_TIMEOUT = 3600
INTERVAL = 20


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd=repo, check=check).stdout.strip()


def say(lines: list[str]) -> None:
    print("\n".join(lines))


def show(st: dict) -> None:
    lines = state.describe(st).splitlines()
    say([*lines[:-1], *appship_report.state_table(st), lines[-1]])


# ---------------- gitops-app PRs ----------------

def open_pr(repo: Path, branch: str, title: str, body: str) -> str:
    existing = json.loads(ship.gh(["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], cwd=repo) or "[]")
    if existing:
        return existing[0]["url"]
    out = ship.gh(["pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body], cwd=repo)
    return out.strip().splitlines()[-1]


def red_reason(what: str, pr: str, lines: list[str]) -> str:
    m = re.search(r"failed on \S+: (.*)$", lines[0]) if lines else None
    return f"{what} {pr} is red: {m.group(1) if m else (lines[0] if lines else 'checks failed')}"


def _switch(repo: Path, branch: str) -> None:
    have = run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], cwd=repo, check=False).returncode == 0
    git(repo, "switch", "-q", branch) if have else git(repo, "switch", "-q", "-c", branch)


def _land_main(repo: Path) -> None:
    git(repo, "switch", "-q", "main")
    git(repo, "pull", "-q", "--ff-only", "origin", "main")


def _guard_clean(repo: Path, allowed: list[str]) -> None:
    other = [ln[3:] for ln in run(["git", "status", "--porcelain"], cwd=repo).stdout.splitlines()
             if not any(ln[3:].strip('"').startswith(a) for a in allowed)]
    if other:
        raise PlatformError("the working tree holds other changes: " + ", ".join(other[:5]),
                            hint="commit or stash them first; the run only publishes the product spec and plan")


def publish(repo: Path, timeout: float) -> tuple[bool, list[str]]:
    st = state.require_state(repo)
    sid = st["spec"]
    paths = [f"docs/specs/{sid}", f"docs/plan/{sid}.md"]
    git(repo, "fetch", "-q", "origin")
    on_main = all(run(["git", "cat-file", "-e", f"origin/main:{p}"], cwd=repo, check=False).returncode == 0
                  for p in (f"docs/specs/{sid}/spec.md", paths[1]))
    same = run(["git", "diff", "--quiet", "origin/main", "--", *paths], cwd=repo, check=False).returncode == 0 \
        and not git(repo, "status", "--porcelain", "--", *paths)
    if on_main and same:
        state.set_phase(repo, "repos")
        return True, ["spec and plan are on main"]
    _guard_clean(repo, paths)
    branch = f"docs/spec-{sid}"
    _switch(repo, branch)
    git(repo, "add", "--", *paths)
    if run(["git", "diff", "--cached", "--quiet"], cwd=repo, check=False).returncode != 0:
        git(repo, *core.git_identity(repo), "commit", "-q", "-s", "-m", f"docs(spec): {sid} — product spec and plan")
    git(repo, "push", "-q", "-u", "origin", branch)
    acs = len(specmod.find(repo, sid).active_acs())
    repos = ", ".join(r["id"] for r in state.plan_repos(repo, sid))
    pr = open_pr(repo, branch, f"docs(spec): {sid} — product spec and plan",
                 f"## Summary\n\nThe product spec and plan of {sid} ({acs} acceptance criteria), published by `/system:ship` before "
                 f"any repo starts.\n\nRepos: {repos}\n")
    ok, lines = appship_merge.land(repo, pr, "publish", timeout, INTERVAL)
    if not ok:
        reason = red_reason("spec/plan PR", pr, lines)
        state.escalate(repo, reason, "code")
        return False, [reason, *lines]
    _land_main(repo)
    state.set_phase(repo, "repos")
    return True, [f"spec and plan merged: {pr}", *lines]


# ---------------- the gitops entry ----------------

def entry_pr(repo: Path, repo_id: str, title: str, body_file: Path) -> str:
    st = state.require_state(repo)
    wt = Path((st["repos"].get(repo_id) or {}).get("clone") or "")
    if not wt.is_dir():
        raise PlatformError(f"{repo_id} has no worktree yet", hint=f"cplat system ship repo start {repo_id}")
    if not body_file.is_file():
        raise PlatformError(f"{body_file} does not exist", hint="write the PR body first")
    ship.check_title(title)
    git(wt, "fetch", "-q", "origin")
    if int(git(wt, "rev-list", "--count", "origin/main..HEAD") or 0) == 0:
        raise PlatformError("the entry branch has no commit ahead of origin/main", hint="commit the entry's changes in the worktree first")
    branch = git(wt, "branch", "--show-current")
    git(wt, "push", "-q", "-u", "origin", branch)
    existing = json.loads(ship.gh(["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], cwd=wt) or "[]")
    if existing:
        pr = existing[0]["url"]
    else:
        pr = ship.gh(["pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", str(body_file)],
                     cwd=wt).strip().splitlines()[-1]
    state.update(repo, lambda s: s["repos"][repo_id].__setitem__("pr", pr))
    return pr


def entry_land(repo: Path, repo_id: str, timeout: float) -> tuple[bool, list[str]]:
    st = state.require_state(repo)
    cur = st["repos"].get(repo_id) or {}
    pr = cur.get("pr")
    if not pr:
        raise PlatformError(f"{repo_id} has no PR", hint=f"cplat system ship entry pr {repo_id} --title T --body-file F")
    ok, lines = appship_merge.land(repo, pr, repo_id, timeout, INTERVAL)
    if not ok:
        appship_sched.escalate_repo(repo, repo_id, red_reason("gitops entry PR", pr, lines), "code")
        return False, lines
    wt = Path(cur.get("clone") or "")
    if wt.is_dir():
        run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=False)

    def change(s: dict) -> None:
        s["repos"][repo_id].update(state="passed", gate="entry", fix_rounds=0, human_steps=[])
    state.update(repo, change)
    return True, lines


# ---------------- complete ----------------

def complete(repo: Path, timeout: float) -> tuple[bool, list[str]]:
    st = state.require_state(repo)
    sid = st["spec"]
    open_ = [i for i, r in st["repos"].items() if r.get("state") not in state.PASSED]
    if open_:
        raise PlatformError("repos not past their gate: " + ", ".join(open_), hint="cplat system ship next --json")
    _guard_clean(repo, [])
    branch = f"docs/done-{sid}"
    _switch(repo, branch)
    sp = specmod.find(repo, sid)
    if sp.status == "approved":
        specmod.set_status(sp, "building", None)
        sp = specmod.find(repo, sid)
    if sp.status == "building":
        specmod.set_status(sp, "done", None if sp.meta.get("shape") == "gitops-app" else "product shipped by /system:ship",
                           unverified=sp.meta.get("shape") != "gitops-app")
    plan = {r["id"]: r for r in state.plan_repos(repo, sid)}
    for rid in st["repos"]:
        if rid in plan and not plan[rid].get("done"):
            run(["devbox", "run", "--", "uv", "run", "scripts/plan.py", "done", sid, rid], cwd=repo)
    specmod.write_index(repo)
    git(repo, "add", "-A")
    if run(["git", "diff", "--cached", "--quiet"], cwd=repo, check=False).returncode != 0:
        git(repo, *core.git_identity(repo), "commit", "-q", "-s", "-m", f"docs(spec): {sid} done")
    git(repo, "push", "-q", "-u", "origin", branch)
    pr = open_pr(repo, branch, f"docs(spec): {sid} done",
                 f"## Summary\n\nEvery repo of {sid} passed its gate; the spec is `done` and the plan completed (`/system:ship`).\n")
    ok, lines = appship_merge.land(repo, pr, "complete", timeout, INTERVAL)
    if not ok:
        reason = red_reason("completion PR", pr, lines)
        state.escalate(repo, reason, "code")
        return False, [reason, *lines]
    _land_main(repo)
    steps = state.plan_meta(repo, sid).get("human_steps") or []
    state.set_phase(repo, "done")
    st = state.require_state(repo)
    return True, appship_report.final_report(st, str(sp.meta.get("title") or sid), steps)


# ---------------- CLI ----------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat system ship", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("spec")
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--context", default=None)
    p.add_argument("--budget", action="append", default=[], metavar="KEY=VALUE",
                   help="replace a limit of the product's budget (ship defaults times the plan's repos; spec 102)")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("phase")
    p.add_argument("phase", choices=state.PHASES)
    p = sub.add_parser("publish")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p = sub.add_parser("next")
    p.add_argument("--json", action="store_true")
    r = sub.add_parser("repo").add_subparsers(dest="rcmd", required=True)
    p = r.add_parser("start")
    p.add_argument("id")
    p = r.add_parser("result")
    p.add_argument("id")
    p = r.add_parser("escalate")
    p.add_argument("id")
    p.add_argument("reason")
    p.add_argument("--cause", default=None)
    e = sub.add_parser("entry").add_subparsers(dest="ecmd", required=True)
    p = e.add_parser("pr")
    p.add_argument("id")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", required=True)
    p = e.add_parser("land")
    p.add_argument("id")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p = sub.add_parser("complete")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p = sub.add_parser("escalate")
    p.add_argument("reason", nargs="+")
    p.add_argument("--cause", default=None)
    sub.add_parser("finish")
    p = sub.add_parser("gate")
    p.add_argument("--max-blocks", type=int, default=state.DEFAULT_MAX_BLOCKS)
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()

    if ns.cmd == "gate":
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        try:
            hook = json.loads(raw) if raw.strip() else {}
        except ValueError:
            hook = {}
        answer = state.gate(Path(hook.get("cwd") or repo), hook, ns.max_blocks)
        if answer:
            print(json.dumps(answer))
        return 0
    if ns.cmd == "start":
        st = state.start(repo, ns.spec, ns.max, ns.context, ns.budget)
        show(st)
        if line := budget.limits_line(st.get("run_id")):
            print(line)
        return 0
    if ns.cmd == "status":
        st = state.require_state(repo)
        if ns.json:
            print(json.dumps({**st, "next": state.next_step(st), "scheduler": appship_sched.next_action(repo, st)}, indent=2))
        else:
            show(st)
        return 0
    if ns.cmd == "phase":
        show(state.set_phase(repo, ns.phase))
        return 0
    if ns.cmd == "publish":
        ok, lines = publish(repo, ns.timeout)
        say(lines)
        return 0 if ok else 1
    if ns.cmd == "next":
        action = appship_sched.next_action(repo, state.require_state(repo))
        if ns.json:
            print(json.dumps(action, indent=2))
        else:
            say([f"action: {action['action']}"] + [f"start {s['id']} ({s['shape']}) in {s['clone']}" for s in action["start"]]
                + [f"running {i}" for i in action["running"]] + [f"blocked {b['id']} (waits for {', '.join(b['waits_for'])})"
                                                                   for b in action["blocked"]]
                + [f"escalated {i}" for i in action["escalated"]])
        return 0
    if ns.cmd == "repo":
        if ns.rcmd == "start":
            print(appship_sched.start_repo(repo, ns.id))
            return 0
        if ns.rcmd == "escalate":
            appship_sched.escalate_repo(repo, ns.id, ns.reason, ns.cause)
            print(f"{ns.id}: escalated ({ns.reason})")
            return 0
        st = state.require_state(repo)
        ok, lines = appship_sched.result(repo, ns.id, st.get("context"))
        say(lines)
        return 0 if ok else 1
    if ns.cmd == "entry":
        if ns.ecmd == "pr":
            print(f"PR: {entry_pr(repo, ns.id, ns.title, Path(ns.body_file))}")
            return 0
        ok, lines = entry_land(repo, ns.id, ns.timeout)
        say(lines)
        return 0 if ok else 1
    if ns.cmd == "complete":
        ok, lines = complete(repo, ns.timeout)
        say(lines)
        return 0 if ok else 1
    if ns.cmd == "escalate":
        st = state.escalate(repo, " ".join(ns.reason), ns.cause)
        say([f"product ship {st['spec']}: escalated ({st['escalated']}); the session may stop. Resume with /system:ship {st['spec']}",
             *appship_report.state_table(st)])
        return 0
    if ns.cmd == "finish":
        print(f"product ship ended; state archived to {state.finish(repo)}")
        return 0
    return 2
