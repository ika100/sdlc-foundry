"""`cplat system ship` — /system:ship: ship a whole product spec across the repos of its plan (spec 097, ADR-042).

Run in the gitops-app repo (`--repo DIR`, default `.`). State: <git dir>/cplat-app-ship.json (never committed).

  cplat system ship start <spec> [--max N] [--context C] [--budget KEY=VALUE] [--until repos]
                                                           refuse or begin/resume; prints phase, repo table and the next step
                                                           (--until repos: stop done after the repos, before land; no cluster)
  cplat system ship status [--json]                        the state and what the scheduler does next
  cplat system ship phase <plan|publish|repos|complete|done>
  cplat system ship publish [--timeout S]                  spec and plan on main: PR merged on green checks (nothing to do when they are)
  cplat system ship next [--json]                          which repos start, run, wait, escalated; the action
  cplat system ship repo start <id>                        mark running; prints the clone path (the entry: its worktree on compose/<spec>);
                                                           a component repo gets its spec from the plan and its own headless
                                                           `/component:ship` session (spec 155)
  cplat system ship repo result <id>                       read the clone's finished ship, evaluate the gate (exit 1: escalated)
  cplat system ship repo escalate <id> <reason> --cause C  a repo that escalated before its ship existed (open questions)
  cplat system ship entry pr <id> --title T [--body-file F]  push the entry's branch and open (or reuse) its PR
                                                           (no file: a body from the plan's gitops operations)
  cplat system ship entry land <id> [--timeout S]          wait for all checks, merge through the merge slot
  cplat system ship land [--timeout S] [--wait-timeout S]  spec 144: merge the one dev PR, Argo CD once, every dev smoke,
                                                           staging in one PR (exit 2: Argo CD timeout, run it again)
  cplat system ship complete [--timeout S]                 spec done + plan completed through a PR merged on green; prints the report
  cplat system ship escalate <reason> --cause C            end the run escalated
  cplat system ship finish                                 archive the state (an unrecorded run is recorded abandoned)
  cplat system ship gate                                   Stop hook (reads the hook's JSON on stdin)
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
import pr_rules
import runs
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
    title = pr_rules.fit(title)
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
        git(repo, *core.git_identity(repo), "commit", "-q", "-s", "-m", pr_rules.fit(f"docs(spec): {sid} — product spec and plan"))
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

def entry_body(repo: Path, st: dict, repo_id: str, wt: Path) -> str:
    """The entry PR's body when no file is given: the plan's gitops operations and the commits (a headless session may
    not write a file outside the worktree, and the worktree lives in the git dir)."""
    entry = next((r for r in state.plan_repos(repo, st["spec"]) if r["id"] == repo_id), {})
    ops = "\n".join(f"- `{json.dumps(op, sort_keys=True)}`" for op in entry.get("gitops") or []) or "- (none listed in the plan)"
    log = git(wt, "log", "--format=- %s", "origin/main..HEAD")
    return (f"## Summary\n\nThe gitops part of system spec {st['spec']} (`/system:ship`).\n\n## Operations of the plan\n\n{ops}\n\n"
            f"## Commits\n\n{log}\n")


def entry_pr(repo: Path, repo_id: str, title: str, body_file: Path | None) -> str:
    st = state.require_state(repo)
    wt = Path((st["repos"].get(repo_id) or {}).get("clone") or "")
    if not wt.is_dir():
        raise PlatformError(f"{repo_id} has no worktree yet", hint=f"cplat system ship repo start {repo_id}")
    if body_file is not None and not body_file.is_file():
        raise PlatformError(f"{body_file} does not exist", hint="write the PR body first, or leave out --body-file")
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
        body = ["--body-file", str(body_file)] if body_file is not None else ["--body", entry_body(repo, st, repo_id, wt)]
        pr = ship.gh(["pr", "create", "--base", "main", "--head", branch, "--title", title, *body], cwd=wt).strip().splitlines()[-1]
    state.update(repo, lambda s: s["repos"][repo_id].__setitem__("pr", pr))
    return pr


def entry_land(repo: Path, repo_id: str, timeout: float) -> tuple[bool, list[str]]:
    st = state.require_state(repo)
    cur = st["repos"].get(repo_id) or {}
    pr = cur.get("pr")
    if not pr:
        raise PlatformError(f"{repo_id} has no PR", hint=f"cplat system ship entry pr {repo_id} --title T --body-file F")
    if st.get("joint"):
        return _entry_green(repo, st, repo_id, pr, timeout)
    ok, lines = appship_merge.land(repo, pr, repo_id, timeout, INTERVAL)
    if not ok:
        appship_sched.escalate_repo(repo, repo_id, red_reason("gitops entry PR", pr, lines), "code")
        return False, lines
    wt = Path(cur.get("clone") or "")
    if wt.is_dir():
        run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=False)
    more, steps = install_operators(repo, st.get("context"))
    lines += more

    def change(s: dict) -> None:
        s["repos"][repo_id].update(state="passed", gate="entry", fix_rounds=0, human_steps=steps)
    state.update(repo, change)
    return True, lines


def _entry_green(repo: Path, st: dict, repo_id: str, pr: str, timeout: float) -> tuple[bool, list[str]]:
    """Spec 144 (decision 4): in a joint run the entry PR is the dev PR: green checks pass the entry, nothing is merged."""
    view = json.loads(ship.gh(["pr", "view", pr, "--json", "state,isDraft"], cwd=repo) or "{}")
    if view.get("isDraft"):
        ship.gh(["pr", "ready", pr], cwd=repo, check=False)
    status, cs, failed = ship.wait_checks(ship.CheckWatch(repo, pr, ship.QUEUE_TIMEOUT, st.get("run_id")), timeout, INTERVAL)
    if status == "red":
        lines = ship.red(repo, pr, cs, failed)
        appship_sched.escalate_repo(repo, repo_id, red_reason("gitops entry PR", pr, lines), "code")
        return False, lines

    def change(s: dict) -> None:
        s["repos"][repo_id].update(state="passed", gate="entry", fix_rounds=0)
        s["joint_pr"] = pr
    state.update(repo, change)
    return True, [f"gitops entry PR {pr} is green; it stays open and lands dev with the builds of the components "
                  "(`cplat system ship land`, spec 144)"]


LOCAL_CONTEXT = re.compile(r"k3d-[a-z0-9-]+-local")   # the cluster `devbox run cluster-up` makes


def install_operators(repo: Path, context: str | None) -> tuple[list[str], list[str]]:
    """Spec 142 (AC-142.2): after the gitops entry merged a change under operators/, apply the operators. A cluster that
    already runs the Argo CD application platform-operators gets them from git (#522). Otherwise, on the local cluster of
    `devbox run cluster-up` the run applies operators/root.yaml itself (`devbox run bootstrap`); on any other cluster it
    is a human step. Returns (lines, human steps). `main` is pulled first, so bootstrap never applies a stale checkout."""
    _land_main(repo)
    changed = git(repo, "diff", "--name-only", "HEAD~1", "HEAD", check=False).splitlines()
    if not any(f.startswith("operators/") for f in changed) or not (repo / "operators" / "root.yaml").is_file():
        return [], []
    cmd = f"KUBE_CONTEXT={context or '<context>'} devbox run bootstrap"
    if context and run(["kubectl", "--context", context, "-n", "argocd", "get", "application", "platform-operators",
                        "-o", "name"], check=False, timeout=60).returncode == 0:
        # #522: operators/root.yaml is applied, so Argo CD syncs the new files under operators/apps from git
        return [f"operators changed: the Argo CD application platform-operators on {context} syncs them from git"], []
    if not (context and LOCAL_CONTEXT.fullmatch(context)):
        return [f"operators changed: apply them once on the cluster: {cmd}"], [f"apply the new operators: {cmd} (in {repo.name})"]
    res = run(["devbox", "run", "bootstrap"], cwd=repo, check=False, env={"KUBE_CONTEXT": context}, timeout=1800)
    if res.returncode == 0:
        return [f"operators changed: applied them on the local cluster {context} ({cmd})"], []
    tail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["no output"]
    return [f"operators changed, but applying them on {context} failed: {tail[0]}"], [f"apply the new operators: {cmd} (in {repo.name})"]


# ---------------- complete ----------------

def complete(repo: Path, timeout: float) -> tuple[bool, list[str]]:
    st = state.require_state(repo)
    sid = st["spec"]
    open_ = [i for i, r in st["repos"].items() if r.get("state") not in state.PASSED]
    if open_:
        raise PlatformError("repos not past their gate: " + ", ".join(open_), hint="cplat system ship next --json")
    if st.get("until") == "repos":                 # spec 156 (AC-156.3): nothing landed, so the spec is not done
        state.set_phase(repo, "done")
        return True, [f"product ship {sid}: stopped after the repos (--until repos); nothing landed, the spec stays "
                      f"'{specmod.find(repo, sid).status}'", *appship_report.state_table(state.require_state(repo))]
    import appship_joint
    if appship_joint.needs_land(st):
        raise PlatformError(f"the dev PR {st['joint_pr']} has not landed yet", hint="cplat system ship land")
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
        git(repo, *core.git_identity(repo), "commit", "-q", "-s", "-m", pr_rules.fit(f"docs(spec): {sid} done"))
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
    runs.set_section(st.get("run_id"), "decisions", appship_report.decision_count(st))   # spec 141 (AC-141.3)
    return True, appship_report.final_report(st, str(sp.meta.get("title") or sid), steps)


# ---------------- CLI ----------------

def show_next(action: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(action, indent=2))
        return
    say([f"action: {action['action']}"] + [f"start {s['id']} ({s['shape']}) in {s['clone']}" for s in action["start"]]
        + [f"running {i}" for i in action["running"]] + [f"blocked {b['id']} (waits for {', '.join(b['waits_for'])})"
                                                           for b in action["blocked"]]
        + [f"escalated {i}" for i in action["escalated"]])


def _next_wait(repo: Path, ns: argparse.Namespace) -> int:
    """`next --wait` (spec 143): counts toward the system ship run."""
    import shipwait
    import waits

    def body() -> tuple[int, str]:
        code, action, lines = shipwait.next_wait(repo, ns.timeout, ns.json, ns.interval)
        if action is not None:
            show_next(action, ns.json)
        else:
            say(lines)
        return code, waits.RESULTS[code]
    return waits.record(repo, "system ship next --wait", body)


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
    p.add_argument("--until", choices=state.UNTIL, default=None,
                   help="stop the run done after every repo passed, before land: no cluster needed (benchmarks, spec 156)")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("phase")
    p.add_argument("phase", choices=state.PHASES)
    p = sub.add_parser("publish")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p = sub.add_parser("next")
    p.add_argument("--json", action="store_true")
    p.add_argument("--wait", action="store_true", help="block while the action is `wait` (spec 143)")
    p.add_argument("--timeout", type=float, default=540.0)
    p.add_argument("--interval", type=float, default=10.0, help=argparse.SUPPRESS)
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
    p.add_argument("--body-file", default=None, help="the PR body (default: the plan's gitops operations and the commits)")
    p = e.add_parser("land")
    p.add_argument("id")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p = sub.add_parser("land", help="merge the one dev PR, wait for Argo CD, smoke dev, promote staging (spec 144)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--wait-timeout", type=float, default=540.0, help="the Argo CD wait (exit 2 when it runs out)")
    p.add_argument("--interval", type=float, default=INTERVAL, help=argparse.SUPPRESS)
    p = sub.add_parser("complete")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p = sub.add_parser("escalate")
    p.add_argument("reason", nargs="+")
    p.add_argument("--cause", default=None)
    sub.add_parser("finish")
    p = sub.add_parser("gate")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()

    if ns.cmd == "gate":
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        try:
            hook = json.loads(raw) if raw.strip() else {}
        except ValueError:
            hook = {}
        answer = state.gate(Path(hook.get("cwd") or repo), hook)
        if answer:
            print(json.dumps(answer))
        return 0
    if ns.cmd == "start":
        st = state.start(repo, ns.spec, ns.max, ns.context, ns.budget, ns.until)
        show(st)
        if st.get("joint") is False:
            import appship_joint
            print(appship_joint.LEGACY_LINE)
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
    if ns.cmd == "next" and ns.wait:
        return _next_wait(repo, ns)
    if ns.cmd == "next":
        show_next(appship_sched.next_action(repo, state.require_state(repo)), ns.json)
        return 0
    if ns.cmd == "repo":
        if ns.rcmd == "start":
            print(appship_sched.start_repo(repo, ns.id))
            proc = state.require_state(repo)["repos"].get(ns.id, {}).get("proc")
            if proc:                                  # spec 155: the repo ships in its own session
                print(f"{ns.id}: ship session started (pid {proc['pid']}, log {proc['log']}); next: cplat system ship next --wait")
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
            print(f"PR: {entry_pr(repo, ns.id, ns.title, Path(ns.body_file) if ns.body_file else None)}")
            return 0
        ok, lines = entry_land(repo, ns.id, ns.timeout)
        say(lines)
        return 0 if ok else 1
    if ns.cmd == "land":
        import appship_joint
        code, lines = appship_joint.land(repo, ns.timeout, ns.wait_timeout, ns.interval, min(ns.interval, 10.0))
        say(lines)
        return code
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
