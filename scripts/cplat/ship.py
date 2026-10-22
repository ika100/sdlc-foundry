"""`ship`: take an approved spec unattended to a merged PR and a running `dev` (specs 066, 067; ADR-028).

/svc:ship does the judgement (plan, build, fix loops); this module keeps the run's state and does every step that
can be code: open the PR, wait for its checks, merge only when all of them passed, wait until `dev` runs the merge.
It needs no branch protection or auto-merge, so it works for private repos on GitHub Free.

  cplat ship start <spec> [--no-merge]   begin or resume; prints the state and the next step
  cplat ship status [--json]             the state of the current run
  cplat ship phase <phase>               record progress (plan, build, pr, land, deploy, done)
  cplat ship pr --title T --body-file F  push the feature branch and open (or reuse) its PR
  cplat ship land [--timeout S]          wait for the PR's checks; merge when every one passed, else print the failures
  cplat ship deploy [--timeout S] [--context C]   wait until dev runs the merged build (pin PR merged, Argo healthy)
  cplat ship escalate <reason>           a rule needs the user: stop here, the Stop hook lets the session end
  cplat ship finish                      end the run (archives the state)
  cplat ship gate [--max-blocks N]       Stop hook: keep an unfinished run going (reads the hook's JSON on stdin)

The state lives in `<git common dir>/cplat-ship.json`: local to the clone, shared by worktrees, never committed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import core
import spec as specmod
from core import PlatformError, run

PHASES = ["plan", "build", "pr", "land", "deploy", "done"]
STATE_FILE = "cplat-ship.json"
DEFAULT_MAX_BLOCKS = 8
FAILED = {"fail", "cancel"}           # `gh pr checks --json bucket` values that mean red
NO_CHECKS_GRACE = 300                 # seconds to wait for the first check to be reported


def gh(args: list[str], *, cwd: Path, check: bool = True) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args], cwd=cwd, check=check).stdout


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


def now() -> float:                   # tests replace this
    return time.time()


# ---------------- state ----------------

def state_path(repo: Path) -> Path:
    common = run(["git", "rev-parse", "--git-common-dir"], cwd=repo, check=False).stdout.strip()
    if not common:
        raise PlatformError(f"{repo} is not a git repository")
    base = Path(common) if Path(common).is_absolute() else repo / common
    return base / STATE_FILE


def load_state(repo: Path) -> dict | None:
    f = state_path(repo)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except ValueError:
        return None


def save_state(repo: Path, state: dict) -> None:
    state["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    state_path(repo).write_text(json.dumps(state, indent=2) + "\n")


def require_state(repo: Path) -> dict:
    st = load_state(repo)
    if not st:
        raise PlatformError("no ship run in this repo", hint="start one with `/svc:ship <spec>` (cplat ship start <spec>)")
    return st


def next_step(st: dict) -> str:
    """What the orchestrator does next, in words the Stop hook can hand back to the model."""
    sid, phase = st["spec"], st["phase"]
    return {
        "plan": f"plan the spec: follow /svc:plan {sid}, then `cplat ship phase build`",
        "build": f"build it: follow /svc:build {sid} (Phases 0–6) until every acceptance test passes and verification.md says pass, "
                 "then `cplat ship phase pr`",
        "pr": "open the PR: write the body to .git/PR_BODY.md, then `cplat ship pr --title <title> --body-file .git/PR_BODY.md`",
        "land": "wait for CI and merge: `cplat ship land`; on red checks fix the failures on the feature branch, push "
                "(`cplat ship pr ...` again) and land again",
        "deploy": "wait for dev: `cplat ship deploy`",
        "done": "nothing: the run is finished (`cplat ship finish`)",
    }[phase]


def describe(st: dict) -> str:
    lines = [f"ship {st['spec']}: phase {st['phase']}" + (f" — ESCALATED: {st['escalated']}" if st.get("escalated") else "")]
    for k in ("branch", "pr", "merge_sha", "deployed"):
        if st.get(k):
            lines.append(f"  {k}: {st[k]}")
    if st.get("fix_rounds"):
        lines.append(f"  CI fix rounds: {st['fix_rounds']}")
    lines.append(f"next: {next_step(st)}")
    return "\n".join(lines)


# ---------------- start / phase / escalate / finish ----------------

def start(repo: Path, ref: str, merge: bool) -> dict:
    sp = specmod.find(repo, ref)
    st = load_state(repo)
    if st and st["spec"] != sp.id and st["phase"] != "done" and not st.get("escalated"):
        raise PlatformError(f"another ship run is in progress: {st['spec']} (phase {st['phase']})",
                            hint="finish it, or end it with `cplat ship finish`")
    if st and st["spec"] == sp.id:
        st.pop("escalated", None)              # a re-run after an escalation resumes where it stopped
        st["blocks"] = 0
        save_state(repo, st)
        return st
    if sp.status in {"draft", "superseded"}:
        raise PlatformError(f"{sp.id} is '{sp.status}'; only an approved spec is shipped",
                            hint=f"answer its questions and approve it: `/svc:spec approve {sp.number}`")
    if sp.status == "done":
        phase = "pr"
    elif sp.plan and not specmod.check_plan(sp, *sp.plan):
        phase = "build"
    else:
        phase = "plan"
    st = {"spec": sp.id, "phase": phase, "merge": merge, "branch": f"feature/{sp.id}", "blocks": 0, "fix_rounds": 0,
          "started": dt.datetime.now().isoformat(timespec="seconds")}
    save_state(repo, st)
    return st


def set_phase(repo: Path, phase: str) -> dict:
    if phase not in PHASES:
        raise PlatformError(f"unknown phase '{phase}'", hint="one of " + ", ".join(PHASES))
    st = require_state(repo)
    st["phase"] = phase
    st["blocks"] = 0
    save_state(repo, st)
    return st


def escalate(repo: Path, reason: str) -> dict:
    st = require_state(repo)
    st["escalated"] = reason
    save_state(repo, st)
    return st


def finish(repo: Path) -> Path:
    f = state_path(repo)
    st = require_state(repo)
    done = f.with_name(f"cplat-ship-{st['spec']}-{dt.datetime.now():%Y%m%d%H%M%S}.json")
    f.rename(done)
    return done


# ---------------- pr / land ----------------

def open_pr(repo: Path, title: str, body_file: Path) -> dict:
    st = require_state(repo)
    branch = st["branch"]
    cur = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo).stdout.strip()
    if cur != branch:
        raise PlatformError(f"on '{cur}', expected the feature branch '{branch}'", hint=f"git switch {branch}")
    if not body_file.is_file():
        raise PlatformError(f"{body_file} does not exist", hint="write the PR body first (the /svc:build Phase 7 template)")
    if not re.match(r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)(\(.+\))?!?: .{1,72}$", title):
        raise PlatformError(f"PR title '{title}' is not a Conventional Commit (type(scope): text, at most 72 characters)")
    run(["git", "push", "-q", "-u", "origin", branch], cwd=repo)
    existing = json.loads(gh(["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], cwd=repo) or "[]")
    if existing:
        st["pr"] = existing[0]["url"]
    else:
        out = gh(["pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", str(body_file)], cwd=repo)
        st["pr"] = out.strip().splitlines()[-1]
    st["phase"] = "land"
    st["blocks"] = 0
    save_state(repo, st)
    return st


def checks(repo: Path, pr: str) -> list[dict]:
    out = gh(["pr", "checks", pr, "--json", "name,state,bucket,link"], cwd=repo, check=False)
    try:
        return json.loads(out or "[]")
    except ValueError:
        return []


def failure_logs(repo: Path, failed: list[dict], limit: int = 60) -> list[str]:
    """The tail of each failed check's log (GitHub Actions runs only)."""
    out: list[str] = []
    for c in failed:
        m = re.search(r"/actions/runs/(\d+)", c.get("link") or "")
        if not m:
            continue
        log = gh(["run", "view", m.group(1), "--log-failed"], cwd=repo, check=False)
        tail = [ln for ln in log.splitlines() if ln.strip()][-limit:]
        if tail:
            out += [f"--- {c['name']} (run {m.group(1)}) ---", *tail]
    return out


def land(repo: Path, timeout: float, interval: float) -> tuple[bool, list[str]]:
    """Wait until no check is pending. All green → merge (unless --no-merge). Returns (merged_or_green, report lines)."""
    st = require_state(repo)
    pr = st.get("pr")
    if not pr:
        raise PlatformError("the run has no PR yet", hint="cplat ship pr --title <title> --body-file .git/PR_BODY.md")
    state = json.loads(gh(["pr", "view", pr, "--json", "state,mergeCommit"], cwd=repo) or "{}")
    if state.get("state") == "MERGED":
        return _merged(repo, st, (state.get("mergeCommit") or {}).get("oid", ""), ["already merged"])
    if state.get("state") == "CLOSED":
        raise PlatformError(f"{pr} was closed without merging", hint="reopen it, or `cplat ship escalate 'PR closed'`")
    begin = now()
    while True:
        cs = checks(repo, pr)
        pending = [c for c in cs if c.get("bucket") == "pending"]
        if cs and not pending:
            break
        waited = now() - begin
        if not cs and waited > NO_CHECKS_GRACE:
            raise PlatformError(f"no CI checks were reported on {pr} after {NO_CHECKS_GRACE}s",
                                hint="is CI set up for pull requests, and is a runner online (vars.CI_RUNNER)? "
                                     "Merging without any check is never done automatically")
        if waited > timeout:
            raise PlatformError(f"checks on {pr} still pending after {int(timeout)}s: " + ", ".join(c["name"] for c in pending),
                                hint="run `cplat ship land` again later; a runner may be busy or offline")
        sleep(interval)
    failed = [c for c in cs if c.get("bucket") in FAILED]
    if failed:
        st["fix_rounds"] = st.get("fix_rounds", 0) + 1
        save_state(repo, st)
        lines = [f"RED: {len(failed)} of {len(cs)} check(s) failed on {pr}: " + ", ".join(c["name"] for c in failed)]
        return False, lines + failure_logs(repo, failed)
    lines = [f"GREEN: all {len(cs)} check(s) passed on {pr}"]
    if not st.get("merge", True):
        st["phase"] = "done"
        save_state(repo, st)
        return True, lines + ["not merged (--no-merge): merge the PR yourself, then run `/svc:ship` again to wait for dev"]
    res = run(["gh", "pr", "merge", pr, "--squash", "--delete-branch"], cwd=repo, check=False)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
        raise PlatformError(f"merging {pr} failed: {detail[0]}", hint="merge conflicts with main: rebase is a human decision; "
                                                                       "`cplat ship escalate 'merge failed'`")
    merged = json.loads(gh(["pr", "view", pr, "--json", "mergeCommit"], cwd=repo) or "{}")
    return _merged(repo, st, (merged.get("mergeCommit") or {}).get("oid", ""), lines + [f"merged {pr} (squash)"])


def _merged(repo: Path, st: dict, sha: str, lines: list[str]) -> tuple[bool, list[str]]:
    st["merge_sha"] = sha
    st["phase"] = "deploy"
    st["blocks"] = 0
    save_state(repo, st)
    run(["git", "switch", "-q", "main"], cwd=repo, check=False)
    run(["git", "pull", "-q", "--ff-only"], cwd=repo, check=False)
    return True, lines


# ---------------- deploy ----------------

def gitops_apps(repo: Path) -> list[str]:
    f = repo / ".platform-app.yml"
    return re.findall(r"^\s*-\s*([^\s#]+/[^\s#]+)", f.read_text(), re.M) if f.is_file() else []


def service_name(repo: Path) -> str:
    url = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/][^/]+/(.+?)(?:\.git)?$", url)
    return m.group(1) if m else repo.name


def deploy(repo: Path, timeout: float, interval: float, context: str | None) -> tuple[bool, list[str]]:
    """Wait for each gitops-app's pin PR for the merge commit (spec 062) to merge, then for Argo to report it healthy."""
    import shapecmd
    st = require_state(repo)
    if st["phase"] == "done":
        return True, ["already done"]
    if not shapecmd.route(repo)["deployable"]:
        return _done(repo, st, ["not deployable (library): nothing to deploy"])
    apps = gitops_apps(repo)
    if not apps:
        return _done(repo, st, ["no .platform-app.yml: this repo is not linked to a gitops-app, so dev is not pinned "
                                "automatically; compose it with /gitops:compose and link it (spec 062)"])
    sha = st.get("merge_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise PlatformError("the run has no merge commit", hint="land the PR first: cplat ship land")
    svc, short = service_name(repo), sha[:7]
    branch = f"pin/dev-{svc}-{short}"
    lines: list[str] = []
    begin = now()
    pending = list(apps)
    while pending:
        for app in list(pending):
            prs = json.loads(gh(["pr", "list", "-R", app, "--state", "all", "--head", branch, "--json", "number,state,url"],
                                cwd=repo, check=False) or "[]")
            pr = prs[0] if prs else None
            if pr and pr["state"] == "MERGED":
                lines.append(f"{app}: dev pinned to {svc}:sha-{short} ({pr['url']})")
                pending.remove(app)
            elif pr and pr["state"] == "CLOSED":
                raise PlatformError(f"{app}: the pin PR {pr['url']} was closed without merging (a newer build superseded it, "
                                    "or its CI failed)", hint="read the PR's comments; `cplat ship escalate 'pin failed'`")
        if not pending:
            break
        if now() - begin > timeout:
            raise PlatformError(f"no merged pin PR {branch} after {int(timeout)}s in: {', '.join(pending)}",
                                hint="check the service's CI on main (docker-publish, pin-dev: is GITOPS_TOKEN set?) "
                                     "and the gitops-app's pin-dev workflow")
        sleep(interval)
    if context:
        health = argo_health(context, f"{svc}-dev", timeout - (now() - begin), interval)
        lines.append(f"Argo CD {svc}-dev: {health}")
        if health != "Synced/Healthy":
            raise PlatformError(f"{svc}-dev is {health} after the pin", hint=f"/shared:status --context {context} in the gitops-app repo")
    else:
        lines.append("Argo health not checked (pass --context <kube-context>)")
    st["deployed"] = f"sha-{short}"
    return _done(repo, st, lines)


def argo_health(context: str, app: str, timeout: float, interval: float) -> str:
    begin = now()
    state = "missing"
    while True:
        p = run(["kubectl", "--context", context, "-n", "argocd", "get", "application", app, "-o", "json"], check=False)
        if p.returncode == 0:
            s = json.loads(p.stdout).get("status", {})
            state = f"{s.get('sync', {}).get('status', '?')}/{s.get('health', {}).get('status', '?')}"
            if state == "Synced/Healthy" or s.get("health", {}).get("status") == "Degraded":
                return state
        if now() - begin > max(timeout, 0):
            return state
        sleep(interval)


def _done(repo: Path, st: dict, lines: list[str]) -> tuple[bool, list[str]]:
    st["phase"] = "done"
    st["blocks"] = 0
    save_state(repo, st)
    return True, lines


# ---------------- Stop hook ----------------

def gate(repo: Path, hook_input: dict, max_blocks: int, run_tests: bool = True) -> dict | None:
    """None lets the session stop; a dict is the hook's JSON answer ({"decision": "block", "reason": …})."""
    try:
        st = load_state(repo)
    except PlatformError:
        return None
    if not st or st.get("escalated") or st["phase"] == "done":
        return None
    if st.get("blocks", 0) >= max_blocks:
        st["escalated"] = f"gave up after {max_blocks} attempts to stop in phase {st['phase']}"
        save_state(repo, st)
        return {"systemMessage": f"ship {st['spec']}: stopped after {max_blocks} blocked stops in phase {st['phase']}; "
                                 "resume with /svc:ship " + st["spec"]}
    st["blocks"] = st.get("blocks", 0) + 1
    save_state(repo, st)
    reason = [f"The ship run of {st['spec']} is not finished (phase {st['phase']}, stop attempt {st['blocks']}/{max_blocks}).",
              f"Next: {next_step(st)}."]
    if st["phase"] == "build" and run_tests:
        reason += build_status(repo, st["spec"])
    reason.append("Keep going. Only if a rule needs the user (merge conflict, a changed acceptance test, a CRITICAL finding, "
                  "a decision the spec does not answer) or the user asked you to stop: run "
                  "`cplat ship escalate '<reason>'`, then stop.")
    return {"decision": "block", "reason": "\n".join(reason)}


def build_status(repo: Path, spec_id: str) -> list[str]:
    """Trace and fast tests, so the model sees exactly what is still red."""
    out: list[str] = []
    tr = run([sys.executable, str(Path(__file__).with_name("cplat.py")), "spec", "trace", spec_id], cwd=repo, check=False, timeout=120)
    if tr.returncode != 0:
        out.append("Criteria without a test:\n" + "\n".join(ln for ln in tr.stdout.splitlines() if ln.startswith("MISS")))
    if not (repo / "devbox.json").is_file():
        return out
    try:
        t = run(["devbox", "run", "test-fast"], cwd=repo, check=False, timeout=900)
    except PlatformError as e:
        return out + [f"`devbox run test-fast` did not finish: {e}"]
    if t.returncode != 0:
        tail = [ln for ln in (t.stdout + t.stderr).splitlines() if ln.strip()][-30:]
        out.append("`devbox run test-fast` is red:\n" + "\n".join(tail))
    else:
        out.append("`devbox run test-fast` is green.")
    return out


# ---------------- CLI ----------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat ship", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("spec")
    p.add_argument("--no-merge", action="store_true", help="stop at a green PR; you merge")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("phase")
    p.add_argument("phase", choices=PHASES)
    p = sub.add_parser("pr")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", required=True)
    p = sub.add_parser("land")
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--interval", type=float, default=20)
    p = sub.add_parser("deploy")
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--interval", type=float, default=20)
    p.add_argument("--context", help="kube context: also wait for Argo CD to report <service>-dev Synced/Healthy")
    p = sub.add_parser("escalate")
    p.add_argument("reason", nargs="+")
    sub.add_parser("finish")
    p = sub.add_parser("gate")
    p.add_argument("--max-blocks", type=int, default=DEFAULT_MAX_BLOCKS)
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()

    if ns.cmd == "gate":
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        try:
            hook = json.loads(raw) if raw.strip() else {}
        except ValueError:
            hook = {}
        cwd = Path(hook.get("cwd") or repo)
        answer = gate(cwd, hook, ns.max_blocks)
        if answer:
            print(json.dumps(answer))
        return 0
    if ns.cmd == "start":
        print(describe(start(repo, ns.spec, not ns.no_merge)))
        return 0
    if ns.cmd == "status":
        st = require_state(repo)
        print(json.dumps({**st, "next": next_step(st)}, indent=2) if ns.json else describe(st))
        return 0
    if ns.cmd == "phase":
        print(describe(set_phase(repo, ns.phase)))
        return 0
    if ns.cmd == "pr":
        st = open_pr(repo, ns.title, Path(ns.body_file))
        print(f"PR: {st['pr']}\n{describe(st)}")
        return 0
    if ns.cmd == "land":
        ok, lines = land(repo, ns.timeout, ns.interval)
        print("\n".join(lines))
        return 0 if ok else 1
    if ns.cmd == "deploy":
        ok, lines = deploy(repo, ns.timeout, ns.interval, ns.context)
        print("\n".join(lines))
        return 0 if ok else 1
    if ns.cmd == "escalate":
        st = escalate(repo, " ".join(ns.reason))
        print(f"ship {st['spec']}: escalated ({st['escalated']}); the session may stop. Resume with /svc:ship {st['spec']}")
        return 0
    if ns.cmd == "finish":
        print(f"ship run ended; state archived to {finish(repo)}")
        return 0
    return 2
