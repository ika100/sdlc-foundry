"""`ship`: take an approved spec unattended to a merged PR and a running `dev` (specs 066, 067; ADR-028).

/component:ship does the judgement (plan, build, fix loops); this module keeps the run's state and does every step that
can be code: open the PR, wait for its checks, merge only when all of them passed, wait until `dev` runs the merge.
It needs no branch protection or auto-merge, so it works for private repos on GitHub Free.

  cplat component ship start <spec> [--no-merge] [--system-dir DIR] [--budget KEY=VALUE]   begin or resume; prints the state, the budget and the next step
                                         (--system-dir: /system:ship only, links the run to a system ship, spec 097)
  cplat component ship status [--json]             the state of the current run
  cplat component ship phase <phase>               record progress (plan, build, pr, land, deploy, done)
  cplat component ship pr --title T --body-file F  run `devbox run ci`, push the feature branch and open (or reuse) its PR
  cplat component ship gitops prepare <task>       a checkout of a gitops task's repo on spec/<spec>-<task> (spec 076)
  cplat component ship gitops pr <task> --title T --body-file F   push it and open (or reuse) its draft PR
  cplat component ship land [--timeout S]          wait for the PR's checks (the first red one ends the wait, stuck runs are rerun
                                         once); all green → merge the before-merge gitops PRs, then the PR
  cplat component ship deploy [--timeout S] [--context C]   wait until dev runs the merged build (pin PR merged, Argo healthy),
                                         then merge the after-release gitops PRs and wait for every app they name
  cplat component ship escalate <reason>           a rule needs the user: stop here, the Stop hook lets the session end
  cplat component ship finish                      end the run (archives the state)
  cplat component ship gate                        Stop hook: keep an unfinished run going (reads the hook's JSON on stdin)

The state lives in `<git common dir>/cplat-ship.json`: local to the clone, shared by worktrees, never committed.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import re
import sys
import time
from pathlib import Path

import autoissue
import budget
import cluster
import core
import escalation_rules
import feedback
import model
import runs
import smoke
import spec as specmod
import staging_deploy
import stopgate
from core import PlatformError, run

PHASES = ["plan", "build", "pr", "land", "deploy", "done"]
STATE_FILE = "cplat-ship.json"
FAILED = {"fail", "cancel"}           # `gh pr checks --json bucket` values that mean red
NO_CHECKS_GRACE = 300                 # seconds to wait for the first check to be reported
QUEUE_TIMEOUT = 300                   # seconds a run may have only queued jobs before it is cancelled and rerun
RERUN_GRACE = 120                     # seconds a check cancelled for a rerun is not counted as red
QUEUED = {"QUEUED", "PENDING", "WAITING", "REQUESTED"}   # `gh pr checks` states of a job no runner took yet
# spec 079: log lines of a red job that mean the network or a registry failed, not the change; such a job is rerun once
TRANSIENT = re.compile(r"Failed to read artifact descriptor|Could not resolve (dependencies|host)|Could not transfer artifact|"
                       r"\b50[234] (Bad Gateway|Service Unavailable|Gateway Time-?out)\b|HTTP (status )?50[234]\b|"
                       r"invalid response status 429|connection reset|Connection reset by peer|TLS handshake timeout|i/o timeout|ETIMEDOUT|ECONNRESET",
                       re.I)


def gh(args: list[str], *, cwd: Path, check: bool = True) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args], cwd=cwd, check=check).stdout


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


def now() -> float:                   # tests replace this
    return time.time()


def say(line: str) -> None:           # progress while waiting (tests replace this)
    print(line, flush=True)


# ---------------- state ----------------

def state_path(repo: Path) -> Path:
    base = core.git_dir(repo)
    if base is None:
        raise PlatformError(f"{repo} is not a git repository")
    return base / STATE_FILE


def load_state(repo: Path) -> dict | None:
    f = state_path(repo)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except ValueError:
        return None


def _utc_iso(local_iso: str | None) -> str | None:
    try:
        return dt.datetime.fromisoformat(local_iso).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def _ensure_run(repo: Path, st: dict) -> str | None:
    """The state's run_id; a run without one (or whose active record is gone and not yet recorded) is (re)started."""
    rid = st.get("run_id")
    if rid and (st.get("recorded") or runs.active(rid) is not None):
        return rid
    st["run_id"] = runs.start("ship", repo=runs.repo_slug(repo), spec=st.get("spec"), run_id=rid,
                              started_at=_utc_iso(st.get("started")), parent=(st.get("product") or {}).get("run_id"))
    return st["run_id"]


def _record(repo: Path, st: dict) -> None:
    """Spec 087: phases and the one end record of a ship run. Never raises."""
    rid = _ensure_run(repo, st)
    if not rid or st.get("recorded"):
        return
    runs.phase(rid, st["phase"])
    if st.get("escalated"):
        runs.finish(rid, "escalated", escalation={"reason": st["escalated"], "cause": st.get("cause") or "unknown"})
        st["recorded"] = True
    elif st["phase"] == "done":
        runs.finish(rid, "done")
        st["recorded"] = True


def save_state(repo: Path, state: dict) -> None:
    try:
        _record(repo, state)
    except Exception:  # noqa: BLE001  (recording never changes a run)
        pass
    state["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    state_path(repo).write_text(json.dumps(state, indent=2) + "\n")


def require_state(repo: Path) -> dict:
    st = load_state(repo)
    if not st:
        raise PlatformError("no ship run in this repo", hint="start one with `/component:ship <spec>` (cplat component ship start <spec>)")
    return st


def next_step(st: dict) -> str:
    """What the orchestrator does next, in words the Stop hook can hand back to the model."""
    sid, phase = st["spec"], st["phase"]
    return {
        "plan": f"plan the spec: follow /component:plan {sid}, then `cplat component ship phase build`",
        "build": f"build it: follow /component:build {sid} (Phases 0–6) until every acceptance test passes and verification.md says pass, "
                 "then `cplat component ship phase pr`. Gitops tasks (plan tasks with `repo:`): `cplat component ship gitops prepare <task>`, "
                 "change and commit in that checkout, then `cplat component ship gitops pr <task> --title <title> --body-file <file>`",
        "pr": "open the PR: write the body to .pr-body.md, then `cplat component ship pr --title <title> --body-file .pr-body.md`",
        "land": "wait for CI and merge: `cplat component ship land`; on red checks fix the failures on the feature branch, push "
                "(`cplat component ship pr ...` again) and land again",
        "deploy": "wait for dev: `cplat component ship deploy`",
        "done": "nothing: the run is finished (`cplat component ship finish`)",
    }[phase]


def describe(st: dict) -> str:
    lines = [f"ship {st['spec']}: phase {st['phase']}" + (f" — ESCALATED: {st['escalated']}" if st.get("escalated") else "")]
    lines.append(f"  session: {st['owner']}" if st.get("owner")
                 else f"  session: none (resume with /component:ship {st['spec']} to own the run)")
    for k in ("branch", "pr", "merge_sha", "deployed"):
        if st.get(k):
            lines.append(f"  {k}: {st[k]}")
    if (st.get("smoke") or {}).get("row"):
        lines.append(f"  smoke: {st['smoke']['row']}")
    if (st.get("staging") or {}).get("row"):
        row = f"  staging: {st['staging']['row']}"
        if (st["staging"].get("smoke") or {}).get("row"):
            row += f"; smoke {st['staging']['smoke']['row']}"
        lines.append(row)
    if st.get("fix_rounds"):
        lines.append(f"  CI fix rounds: {st['fix_rounds']}")
    lines.append(f"next: {next_step(st)}")
    return "\n".join(lines)


# ---------------- start / phase / escalate / finish ----------------

def product_link(product: Path) -> dict:
    """Spec 097: the product run a repo ship belongs to (parent record, default kube context, gitops merge slot)."""
    import appship_state
    pst = appship_state.load_state(product)
    if not pst:
        raise PlatformError(f"no product ship run in {product}", hint="start it in the gitops-app repo: /system:ship <spec>")
    return {"dir": str(product), "run_id": pst.get("run_id"), "context": pst.get("context")}


def _open_budget(repo: Path, st: dict, options: dict) -> None:
    """Spec 102: a ship run is a root (one budget per run tree) unless it runs under headless or a product ship."""
    budget.open_root(st.get("run_id"), budget.work_key(repo, st["spec"], st["spec"]), options=options, repo=repo)


def _record_shape(st: dict) -> None:
    """Spec 123: the shape the run was started for, on the run record. Never raises."""
    if st.get("shape"):
        runs.set_section(st.get("run_id"), "shape", st["shape"])


def start(repo: Path, ref: str, merge: bool, take_over: bool = False, product: Path | None = None,
          budget_options: list[str] | dict | None = None) -> dict:
    import shapecmd
    shape = shapecmd.resolve(repo)             # spec 123: a declaration error stops here, before any state changes
    options = budget.parse_options(budget_options)
    link = product_link(product) if product else None
    sp = specmod.find(repo, ref)
    st = load_state(repo)
    if st and st["spec"] != sp.id and st["phase"] != "done" and not st.get("escalated"):
        if not take_over:
            raise PlatformError(f"another ship run is in progress: {st['spec']} (phase {st['phase']})",
                                hint="finish it, or end it with `cplat component ship finish`, or take it over: "
                                     f"cplat component ship start {sp.id} --take-over")
    if sp.meta.get("tracks"):                  # spec 082: refuse an issue another branch is building
        import claim
        for note in claim.claim(repo, sp.meta["tracks"], f"feature/{sp.id}", take_over=take_over, what=f"ship {sp.id}"):
            say(note)
    if st and st["spec"] == sp.id:
        if st.get("escalated"):                # spec 087: a resumed escalated run is a new run
            old = st.get("run_id")
            st["run_id"] = runs.start("ship", repo=runs.repo_slug(repo), spec=st["spec"], resumes=old,
                                      parent=link["run_id"] if link else None)
            st["recorded"] = False
        if link:
            st["product"] = link
        st.pop("escalated", None)              # a re-run after an escalation resumes where it stopped
        st.pop("cause", None)
        stopgate.claim(st, stopgate.session_of_env())
        if shape:
            st["shape"] = shape
        save_state(repo, st)
        _record_shape(st)
        runs.link_parent(st.get("run_id"))
        _open_budget(repo, st, options)
        return st
    if sp.status in {"draft", "superseded"}:
        raise PlatformError(f"{sp.id} is '{sp.status}'; only an approved spec is shipped",
                            hint=f"answer its questions and approve it: `/component:spec approve {sp.number}`")
    if shape != "platform" and missing_gitops_token(repo):
        raise PlatformError("this repo is linked to a gitops-app, but the secret GITOPS_TOKEN is not set: dev would never "
                            "be pinned (spec 077)", hint=GITOPS_TOKEN_FIX.format(slug=service_slug(repo)))
    if sp.status == "done":
        phase = "pr"
    elif sp.plan and not specmod.check_plan(sp, *sp.plan):
        phase = "build"
    else:
        phase = "plan"
    if st and st["spec"] != sp.id and st["phase"] != "done" and not st.get("escalated") and not st.get("recorded"):
        runs.finish(st.get("run_id"), "abandoned")   # take-over: only after every check that can still refuse
    st = {"spec": sp.id, "phase": phase, "merge": merge, "branch": f"feature/{sp.id}", "fix_rounds": 0,
          "started": dt.datetime.now().isoformat(timespec="seconds"), "recorded": False}
    stopgate.claim(st, stopgate.session_of_env())
    if link:
        st["product"] = link
    if shape:
        st["shape"] = shape
    save_state(repo, st)
    _record_shape(st)
    runs.link_parent(st.get("run_id"))
    _open_budget(repo, st, options)
    return st


def on_branch(repo: Path, branch: str) -> str:
    """Switch to the run's feature branch before the merge: the existing local one, else the remote one, else a new one
    from the current HEAD. Code, so a coordinator never improvises it (a refused `git checkout -B` stopped a headless ship)."""
    def git(*args: str):
        return run(["git", *args], cwd=repo, check=False)
    if git("branch", "--show-current").stdout.strip() == branch:
        return f"branch: {branch}"
    if git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        args, how = ["switch", branch], "switched to"
    elif git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}").returncode == 0:
        args, how = ["switch", "-c", branch, "--track", f"origin/{branch}"], "switched to (tracking origin)"
    else:
        args, how = ["switch", "-c", branch], "created"
    p = git(*args)
    if p.returncode != 0:
        raise PlatformError(f"cannot switch to {branch}: {(p.stderr or p.stdout).strip()}",
                            hint=f"commit or stash local changes, then rerun; or `git switch {branch}` yourself")
    return f"branch: {how} {branch}"


GITOPS_TOKEN_FIX = ("create a fine-grained token with Contents read and write on the gitops-app repo, then: "
                    "gh secret set GITOPS_TOKEN -R {slug}")


def missing_gitops_token(repo: Path) -> bool:
    """True only when the repo is linked and `gh secret list` worked and has no GITOPS_TOKEN (unknown → False)."""
    if not gitops_apps(repo):
        return False
    out = gh(["secret", "list", "--json", "name"], cwd=repo, check=False)
    try:
        names = {x["name"] for x in json.loads(out)}
    except (ValueError, TypeError, KeyError):
        return False
    return "GITOPS_TOKEN" not in names


def set_phase(repo: Path, phase: str) -> dict:
    if phase not in PHASES:
        raise PlatformError(f"unknown phase '{phase}'", hint="one of " + ", ".join(PHASES))
    st = require_state(repo)
    st["phase"] = phase
    save_state(repo, st)
    if phase != "done" and (limit := budget.check(st.get("run_id"), "phase end")):   # spec 102: a safe point
        reason = budget_stop(repo, st, limit, "phase end")
        raise PlatformError(reason, hint=f"stop here; resume with /component:ship {st['spec']}, raising the limit if you want "
                                         f"(--budget {limit}=N)")
    return st


def budget_stop(repo: Path, st: dict, limit: str, point: str) -> str:
    """Spec 102: record the stop in the run's `budget` section and escalate the ship (cause decision). Returns the reason."""
    reason = budget.stop(st.get("run_id"), limit, point, st.get("phase"))
    if not st.get("escalated"):
        escalate(repo, reason, "decision", stage=st.get("phase"))
    return reason


ESCALATION_CAUSES = ("platform", "code", "decision", "environment")
_ALLOWED = ", ".join(ESCALATION_CAUSES)


def _coerce_cause(cause: str | None) -> tuple[str, str | None]:
    """(cause, message): anything outside ESCALATION_CAUSES is `unknown` with a message (spec 088, AC-088.3)."""
    if cause in ESCALATION_CAUSES:
        return cause, None
    if cause is None or not str(cause).strip() or str(cause).strip() == "unknown":
        return "unknown", f"cause missing: recorded as unknown; allowed causes: {_ALLOWED}"
    return "unknown", f"cause '{cause}' is missing or not known: recorded as unknown; allowed causes: {_ALLOWED}"


def _file_platform_failure(repo: Path, st: dict, reason: str, command: str | None, evidence: str, report: list[str]) -> None:
    """File or +1 the failure before save_state ends the run record. Never raises (AC-088.12)."""
    try:
        rid = _ensure_run(repo, st)
        cmd = command or "/component:ship"
        names = autoissue.private_names(runs.repo_slug(repo), st.get("spec"), st.get("branch"))
        draft = autoissue.Draft(
            kind="platform",
            signature=autoissue.signature("platform", cmd, st.get("phase") or "none", reason, names=names),
            reason=reason, command=cmd, phase=st.get("phase") or "none", evidence=feedback.tail(evidence),
            run_id=rid, shape=st.get("shape") or core.read_stamp(repo).get("shape", "none"), names=names,
            environment=feedback.diagnostics(repo))
        report.extend(autoissue.file(draft, run_id=rid).lines)
    except Exception as e:  # noqa: BLE001  (an escalation always completes)
        report.append(f"issue: not filed: {type(e).__name__}: {e}")


def escalate(repo: Path, reason: str, cause: str | None = None, *, command: str | None = None, evidence: str = "",
             report: list[str] | None = None, stage: str | None = None) -> dict:
    st = require_state(repo)
    report = report if report is not None else []
    cause, message = _coerce_cause(cause)
    if message:
        report.append(message)
    if cause == "unknown":                     # AC-088.15: a missing or unknown cause is classified by the reason
        classified = escalation_rules.message(escalation_rules.resolve(None, reason))
        if classified:
            report.append(classified)
    st["escalated"] = reason
    st["cause"] = cause
    if cause == "platform":
        _file_platform_failure(repo, st, reason, command, evidence, report)
    budget.snapshot(repo, stage or st.get("phase") or "none", evidence or reason, [])   # spec 102: local only
    save_state(repo, st)
    try:
        tracks = specmod.find(repo, st["spec"]).meta.get("tracks") or []
    except PlatformError:
        tracks = []
    if tracks:                                 # spec 082: a stopped run does not keep the issue
        import claim
        claim.release(repo, tracks, f"ship {st['spec']} escalated: {reason}")
    return st


def finish(repo: Path) -> Path:
    f = state_path(repo)
    st = require_state(repo)
    if not st.get("recorded"):
        runs.finish(st.get("run_id"), "abandoned")
    done = f.with_name(f"cplat-ship-{st['spec']}-{dt.datetime.now():%Y%m%d%H%M%S}.json")
    f.rename(done)
    return done


# ---------------- pr / land ----------------

def run_ci(repo: Path) -> None:
    """Spec 075: `devbox run ci` (the gates of the CI workflow, in its order) must be green before anything is pushed."""
    f = repo / "devbox.json"
    if not f.is_file() or '"ci"' not in f.read_text():
        return
    say("running `devbox run ci` before pushing …")
    res = run(["devbox", "run", "ci"], cwd=repo, check=False, timeout=3600)
    if res.returncode != 0:
        try:
            import validate
            validate.record_final_gate(repo)   # spec 103: a check the loop skipped or reused that is red now is a miss
        except Exception:  # noqa: BLE001  (recording never changes the gate)
            pass
        tail = [ln for ln in (res.stdout + res.stderr).splitlines() if ln.strip()][-40:]
        raise PlatformError("`devbox run ci` is red; nothing was pushed:\n" + "\n".join(tail),
                            hint="hand the failure to the coder agent, commit the fix, then `cplat component ship pr` again")


def open_pr(repo: Path, title: str, body_file: Path) -> dict:
    st = require_state(repo)
    branch = st["branch"]
    cur = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo).stdout.strip()
    if cur != branch:
        raise PlatformError(f"on '{cur}', expected the feature branch '{branch}'", hint=f"git switch {branch}")
    if not body_file.is_file():
        raise PlatformError(f"{body_file} does not exist", hint="write the PR body first (the /component:build Phase 7 template)")
    check_title(title)
    missing = [t["id"] for t in gitops_tasks(repo, st) if not st.get("gitops", {}).get(t["id"], {}).get("pr")]
    if missing:
        raise PlatformError(f"gitops task(s) without a PR: {', '.join(missing)}",
                            hint="cplat component ship gitops prepare <task>, change and commit there, then cplat component ship gitops pr <task> ...")
    run_ci(repo)
    run(["git", "push", "-q", "-u", "origin", branch], cwd=repo)
    existing = json.loads(gh(["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], cwd=repo) or "[]")
    if existing:
        st["pr"] = existing[0]["url"]
    else:
        out = gh(["pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", str(body_file)], cwd=repo)
        st["pr"] = out.strip().splitlines()[-1]
    st["phase"] = "land"
    save_state(repo, st)
    return st


def check_title(title: str) -> None:
    if not re.match(r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)(\(.+\))?!?: .{1,72}$", title):
        raise PlatformError(f"PR title '{title}' is not a Conventional Commit (type(scope): text, at most 72 characters)")


def checks(repo: Path, pr: str) -> list[dict]:
    out = gh(["pr", "checks", pr, "--json", "name,state,bucket,link"], cwd=repo, check=False)
    try:
        return json.loads(out or "[]")
    except ValueError:
        return []


def run_of(check: dict) -> tuple[str, str] | None:
    """(owner/repo, run id) of a GitHub Actions check, from its link."""
    m = re.search(r"github\.com/([^/]+/[^/]+)/actions/runs/(\d+)", check.get("link") or "")
    return (m.group(1), m.group(2)) if m else None


def failure_logs(repo: Path, failed: list[dict], limit: int = 60) -> list[str]:
    """The tail of each failed check's log (GitHub Actions runs only)."""
    out: list[str] = []
    for c in failed:
        r = run_of(c)
        if not r:
            continue
        log = gh(["run", "view", r[1], "-R", r[0], "--log-failed"], cwd=repo, check=False)
        tail = [ln for ln in log.splitlines() if ln.strip()][-limit:]
        if tail:
            out += [f"--- {c['name']} (run {r[1]}) ---", *tail]
    return out


class CheckWatch:
    """One PR's checks across polls (spec 072): each conclusion is reported once, a red check ends the wait at once,
    and a stale run (check in progress, run completed) or a stuck one (only queued jobs for `queue_timeout`) is healed
    once; the second time it is an error."""

    def __init__(self, repo: Path, pr: str, queue_timeout: float, run_id: str | None = None):
        self.repo, self.pr, self.queue_timeout, self.run_id = repo, pr, queue_timeout, run_id
        self.reported: dict[str, str] = {}
        self.queued_since: dict[tuple[str, str], float] = {}
        self.stale_seen: dict[tuple[str, str], int] = {}
        self.healed: dict[tuple[str, str], tuple[str, float]] = {}   # run → (stale | queued, when)
        self.head: str | None = None                                  # the PR head commit being watched
        self.run_sha: dict[str, str | None] = {}                      # run id → the commit it ran on
        self.run_workflow: dict[str, str | None] = {}                 # run id → its workflow (database id)
        self.refused: str | None = None                               # spec 102: the budget refused a rerun
        self.refused_checks: list[dict] = []

    def conflicting(self) -> bool:
        """GitHub starts no pull_request workflow while a PR conflicts with its base (#221): its green is not CI's."""
        out = gh(["pr", "view", self.pr, "--json", "mergeable"], cwd=self.repo, check=False)
        try:
            return json.loads(out or "{}").get("mergeable") == "CONFLICTING"
        except ValueError:
            return False

    def head_sha(self) -> str | None:
        out = gh(["pr", "view", self.pr, "--json", "headRefOid"], cwd=self.repo, check=False)
        try:
            return json.loads(out or "{}").get("headRefOid") or None
        except (ValueError, AttributeError):
            return None

    def _sha_of(self, c: dict) -> str | None:
        r = run_of(c)
        if not r:
            return None
        if r[1] not in self.run_sha:
            out = gh(["run", "view", r[1], "-R", r[0], "--json", "headSha"], cwd=self.repo, check=False)
            wf = gh(["run", "view", r[1], "-R", r[0], "--json", "workflowDatabaseId"], cwd=self.repo, check=False)
            try:
                self.run_sha[r[1]] = json.loads(out or "{}").get("headSha") or None
            except (ValueError, AttributeError):
                self.run_sha[r[1]] = None
            try:
                w = json.loads(wf or "{}").get("workflowDatabaseId")
                self.run_workflow[r[1]] = str(w) if w else None
            except (ValueError, AttributeError):
                self.run_workflow[r[1]] = None
        return self.run_sha[r[1]]

    def _newest_runs(self, cs: list[dict]) -> list[dict]:
        """Of several runs of one workflow on the same commit only the newest counts: an older one was superseded
        (concurrency cancel-in-progress), and its cancelled or failed checks say nothing about the PR."""
        newest: dict[tuple[str, str], int] = {}
        for c in cs:
            r = run_of(c)
            wf = self.run_workflow.get(r[1]) if r else None
            if r and wf:
                key = (r[0], wf)
                newest[key] = max(newest.get(key, 0), int(r[1]))
        out = []
        for c in cs:
            r = run_of(c)
            wf = self.run_workflow.get(r[1]) if r else None
            if r and wf and int(r[1]) < newest[(r[0], wf)]:
                continue
            out.append(c)
        return out

    def _current(self) -> list[dict]:
        """Only the checks of the PR's current head commit; a new head starts the watch over (a fresh push
        must not be judged by the previous commit's checks)."""
        head = self.head_sha()
        if head and self.head and head != self.head:
            self.reported.clear()
            self.queued_since.clear()
            self.stale_seen.clear()
            self.healed.clear()
        if head:
            self.head = head
        cs = checks(self.repo, self.pr)
        shas = [self._sha_of(c) for c in cs]
        if head:
            cs = [c for c, sha in zip(cs, shas) if sha in (None, head)]
        return self._newest_runs(cs)

    def _runs_pending(self) -> bool:
        """A workflow run of the head commit that has not completed: a queued run reports no checks at all, so the
        checks of the other workflows (CodeQL) alone would look green (#269)."""
        if not self.head:
            return False
        m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/", self.pr)
        out = gh(["run", "list", "--commit", self.head, "--json", "status", "-L", "50"] + (["-R", m.group(1)] if m else []),
                 cwd=self.repo, check=False)
        try:
            return any(r.get("status") != "completed" for r in json.loads(out or "[]"))
        except (ValueError, AttributeError):
            return False

    def _own_cancel(self, c: dict) -> bool:
        """A check of a run this watch just reran (stuck queue cancelled, or a transient failure) is not red yet."""
        h = self.healed.get(run_of(c) or ("", ""))
        if not h or now() - h[1] >= RERUN_GRACE:
            return False
        return (h[0] == "queued" and c.get("bucket") == "cancel") or (h[0] == "transient" and c.get("bucket") in FAILED)

    def _transient(self, failed: list[dict]) -> list[dict]:
        """Rerun, once per run, the failed jobs of a run whose log shows a transient error (spec 079); returns the rest."""
        final = []
        for c in failed:
            r = run_of(c)
            if not r or r in self.healed:
                final.append(c)
                continue
            log = gh(["run", "view", r[1], "-R", r[0], "--log-failed"], cwd=self.repo, check=False)
            hit = TRANSIENT.search("\n".join(log.splitlines()[-80:]))
            if not hit:
                final.append(c)
                continue
            if not budget.allow_rerun(self.run_id):
                self.refused = budget.REFUSED_RERUN
                final.append(c)
                continue
            say(f"  rerun    run {r[1]}: {c['name']} failed on a transient error ({hit.group(0)})")
            gh(["run", "rerun", r[1], "-R", r[0], "--failed"], cwd=self.repo, check=False)
            runs.rerun(self.run_id, ", ".join(sorted(x["name"] for x in failed if run_of(x) == r)), "transient")
            self.healed[r] = ("transient", now())
        return final

    def poll(self) -> tuple[str, list[dict], list[dict]]:
        """("pending" | "green" | "red", checks, failed checks)."""
        cs = self._current()
        own = [c for c in cs if self._own_cancel(c)]
        for c in cs:
            b = c.get("bucket", "")
            if b != "pending" and c not in own and self.reported.get(c["name"]) != b:
                self.reported[c["name"]] = b
                say(f"  {b:<8} {c['name']}")
        failed = self._transient([c for c in cs if c.get("bucket") in FAILED and c not in own])
        if failed:
            return "red", cs, failed
        own = [c for c in cs if self._own_cancel(c)]
        pending = [c for c in cs if c.get("bucket") == "pending" or c in own]
        if cs and not pending:
            if self._runs_pending():
                return "pending", cs, []
            return "green", cs, []
        self._heal(pending)
        if self.refused:
            return "red", cs, self.refused_checks
        return "pending", cs, []

    def _heal(self, pending: list[dict]) -> None:
        by_run: dict[tuple[str, str], list[dict]] = {}
        for c in pending:
            if (r := run_of(c)) and c.get("bucket") == "pending":
                by_run.setdefault(r, []).append(c)
        running = any(c.get("state") == "IN_PROGRESS" for c in pending)
        for r, cs in by_run.items():
            slug, rid = r
            if any(c.get("state") == "IN_PROGRESS" for c in cs) and run_status(slug, rid) == "completed":
                self.stale_seen[r] = self.stale_seen.get(r, 0) + 1
                if self.stale_seen[r] < 2:              # the checks API may lag the run by a poll
                    continue
                names = ", ".join(c["name"] for c in cs)
                if self.healed.get(r, ("",))[0] == "stale":
                    raise PlatformError(f"check(s) {names} of run {rid} ({slug}) stay in progress although the run "
                                        "completed, also after a rerun", hint=f"gh run view {rid} -R {slug}; escalate")
                if not budget.allow_rerun(self.run_id):
                    self.refused, self.refused_checks = budget.REFUSED_RERUN, cs
                    continue
                say(f"  rerun    run {rid}: {names} in progress, but the run completed (stale)")
                gh(["run", "rerun", rid, "-R", slug], cwd=self.repo, check=False)
                runs.rerun(self.run_id, ", ".join(sorted(c["name"] for c in cs)), "stale")
                self.healed[r] = ("stale", now())
                self.stale_seen.pop(r, None)
                continue
            self.stale_seen.pop(r, None)
            if running or not all(c.get("state") in QUEUED for c in cs):
                self.queued_since.pop(r, None)
                continue
            since = self.queued_since.setdefault(r, now())
            if now() - since <= self.queue_timeout:
                continue
            if self.healed.get(r, ("",))[0] == "queued":
                labels = runner_labels(slug, rid) or "?"
                raise PlatformError(f"jobs of run {rid} ({slug}) queued for {int(now() - since)}s again after a cancel "
                                    f"and rerun: the runner set {labels} picks up no jobs",
                                    hint="check the ARC listener and runner pods of that scale set; escalate")
            if not budget.allow_rerun(self.run_id):
                self.refused, self.refused_checks = budget.REFUSED_RERUN, cs
                continue
            say(f"  rerun    run {rid}: only queued jobs for {int(now() - since)}s (cancel + rerun)")
            cancel_and_rerun(self.repo, slug, rid)
            runs.rerun(self.run_id, ", ".join(sorted(c["name"] for c in cs)), "stuck")
            self.healed[r] = ("queued", now())
            self.queued_since.pop(r, None)


def run_status(slug: str, rid: str) -> str:
    return gh(["run", "view", rid, "-R", slug, "--json", "status", "-q", ".status"], cwd=Path("."), check=False).strip()


def runner_labels(slug: str, rid: str) -> str:
    return gh(["api", f"repos/{slug}/actions/runs/{rid}/jobs", "--jq",
               '[.jobs[] | select(.status == "queued") | .labels[]] | unique | join(",")'], cwd=Path("."), check=False).strip()


def cancel_and_rerun(repo: Path, slug: str, rid: str, wait: float = 120) -> None:
    gh(["run", "cancel", rid, "-R", slug], cwd=repo, check=False)
    begin = now()
    while run_status(slug, rid) != "completed" and now() - begin < wait:
        sleep(5)
    gh(["run", "rerun", rid, "-R", slug], cwd=repo, check=False)


class NoChecks(PlatformError):
    """No check was reported within the grace period (spec 087: told apart by type, not by message)."""


class Conflicting(PlatformError):
    """The PR conflicts with its base, so its CI never ran; the checks that did (CodeQL) prove nothing (#221)."""


class ChecksPending(PlatformError):
    """The timeout ran out with checks still pending; `checks` holds their names."""

    def __init__(self, message: str, hint: str | None = None, checks: list[str] | None = None) -> None:
        super().__init__(message, hint=hint)
        self.checks = checks or []


def wait_checks(watch: CheckWatch, timeout: float, interval: float) -> tuple[str, list[dict], list[dict]]:
    """Poll until every check concluded or one is red. A PR without any check, or one that conflicts with its base, is
    never green."""
    begin = now()
    while True:
        status, cs, failed = watch.poll()
        if status == "green" and watch.conflicting():
            raise _conflicting(watch)
        if status != "pending":
            runs.ci_round(watch.run_id)
            return status, cs, failed
        waited = now() - begin
        if not cs and waited > NO_CHECKS_GRACE:
            if watch.conflicting():
                raise _conflicting(watch)
            raise NoChecks(f"no CI checks were reported on {watch.pr} after {NO_CHECKS_GRACE}s",
                           hint="is CI set up for pull requests, and is a runner online (vars.CI_RUNNER)? "
                                "Merging without any check is never done automatically")
        if waited > timeout:
            pending = [c["name"] for c in cs if c.get("bucket") == "pending"] or ["a workflow run that reports no checks yet (queued)"]
            raise ChecksPending(f"checks on {watch.pr} still pending after {int(timeout)}s: {', '.join(pending)}",
                                hint="run the command again later; a runner may be busy or offline", checks=pending)
        sleep(interval)


def _conflicting(watch: CheckWatch) -> Conflicting:
    return Conflicting(f"{watch.pr} conflicts with its base branch, so no pull_request workflow ran on it",
                       hint="merge the base branch into the PR branch and push, then wait again")


def red(repo: Path, pr: str, cs: list[dict], failed: list[dict]) -> list[str]:
    lines = [f"RED: {len(failed)} of {len(cs)} check(s) failed on {pr}: " + ", ".join(c["name"] for c in failed)]
    return lines + failure_logs(repo, failed)


def refused(repo: Path, st: dict, reason: str, lines: list[str]) -> list[str]:
    """Spec 102: the budget refused a CI rerun. The wait ends red; the ship is escalated (cause decision)."""
    limit = reason.rsplit(": ", 1)[-1]
    escalate(repo, budget.stop(st.get("run_id"), limit, "ci rerun", st.get("phase")), "decision", evidence="\n".join(lines), stage="ci")
    return [reason, *lines]


def land(repo: Path, timeout: float, interval: float, queue_timeout: float = QUEUE_TIMEOUT) -> tuple[bool, list[str]]:
    """Wait for the PR's checks: the first red one ends the wait; all green → merge the before-merge gitops PRs, then
    the PR (unless --no-merge). Returns (merged_or_green, report lines)."""
    st = require_state(repo)
    pr = st.get("pr")
    if not pr:
        raise PlatformError("the run has no PR yet", hint="cplat component ship pr --title <title> --body-file .pr-body.md")
    state = json.loads(gh(["pr", "view", pr, "--json", "state,mergeCommit"], cwd=repo) or "{}")
    if state.get("state") == "MERGED":
        return _merged(repo, st, (state.get("mergeCommit") or {}).get("oid", ""), ["already merged"])
    if state.get("state") == "CLOSED":
        raise PlatformError(f"{pr} was closed without merging", hint="reopen it, or `cplat component ship escalate 'PR closed'`")
    watch = CheckWatch(repo, pr, queue_timeout, st.get("run_id"))
    status, cs, failed = wait_checks(watch, timeout, interval)
    try:  # agent metrics (spec 089): never changes the result
        import runs_agents
        runs_agents.red_ci(st.get("run_id"), repo, [c["name"] for c in failed] if status == "red" else [])
    except Exception:  # noqa: BLE001
        pass
    if status == "red":
        try:
            import validate
            validate.record_ci_red(repo, [c["name"] for c in failed])   # spec 103: misses of the change-aware loop
        except Exception:  # noqa: BLE001
            pass
        st["fix_rounds"] = st.get("fix_rounds", 0) + 1
        save_state(repo, st)
        lines = red(repo, pr, cs, failed)
        if watch.refused:
            return False, refused(repo, st, watch.refused, lines)
        text = "\n".join(lines)
        why = budget.attempt(repo, "ci", text, len(failed), [c["name"] for c in failed])   # spec 102: no progress
        if why:
            escalate(repo, why, "code", evidence=text, stage="ci")
            lines.append(why)
        return False, lines
    lines = [f"GREEN: all {len(cs)} check(s) passed on {pr}"]
    if not st.get("merge", True):
        st["phase"] = "done"
        save_state(repo, st)
        return True, lines + ["not merged (--no-merge): merge the PR (and its gitops PRs) yourself, then run `/component:ship` "
                              "again to wait for dev"]
    ok, more = merge_gitops(repo, st, "before-merge", timeout, interval, queue_timeout)
    lines += more
    if not ok:
        return False, lines
    res = run(["gh", "pr", "merge", pr, "--squash", "--delete-branch"], cwd=repo, check=False)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
        raise PlatformError(f"merging {pr} failed: {detail[0]}", hint="merge conflicts with main: rebase is a human decision; "
                                                                       "`cplat component ship escalate 'merge failed'`")
    merged = json.loads(gh(["pr", "view", pr, "--json", "mergeCommit"], cwd=repo) or "{}")
    return _merged(repo, st, (merged.get("mergeCommit") or {}).get("oid", ""), lines + [f"merged {pr} (squash)"])


def _merged(repo: Path, st: dict, sha: str, lines: list[str]) -> tuple[bool, list[str]]:
    st["merge_sha"] = sha
    st["phase"] = "deploy"
    save_state(repo, st)
    run(["git", "switch", "-q", "main"], cwd=repo, check=False)
    run(["git", "pull", "-q", "--ff-only"], cwd=repo, check=False)
    return True, lines


# ---------------- gitops tasks (spec 076) ----------------

def plan_meta(repo: Path, st: dict) -> dict:
    try:
        sp = specmod.find(repo, st["spec"])
    except PlatformError:
        return {}
    return sp.plan[0] if sp.plan else {}


def gitops_tasks(repo: Path, st: dict, order: str | None = None) -> list[dict]:
    """The plan's tasks with `repo:`, in plan order."""
    return [t for t in plan_meta(repo, st).get("tasks") or []
            if isinstance(t, dict) and t.get("repo") and (order is None or t.get("order") == order)]


def _gitops_task(repo: Path, st: dict, task_id: str) -> dict:
    hit = [t for t in gitops_tasks(repo, st) if t.get("id") == task_id]
    if not hit:
        known = ", ".join(t["id"] for t in gitops_tasks(repo, st)) or "none"
        raise PlatformError(f"'{task_id}' is not a gitops task of {st['spec']} (gitops tasks: {known})",
                            hint="a gitops task is a plan task with `repo: <owner>/<gitops-repo>` and `order:`")
    return hit[0]


def gitops_checkout(repo: Path, slug: str) -> Path:
    return state_path(repo).parent / "cplat-gitops" / slug.replace("/", "__")


def gitops_prepare(repo: Path, task_id: str) -> Path:
    """A checkout of the task's gitops repo on `spec/<spec>-<task>`, kept next to the run's state."""
    st = require_state(repo)
    t = _gitops_task(repo, st, task_id)
    d, branch = gitops_checkout(repo, t["repo"]), f"spec/{st['spec']}-{task_id}"
    if not (d / ".git").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        run(["gh", "repo", "clone", t["repo"], str(d), "--", "-q"], cwd=repo)
    else:
        run(["git", "fetch", "-q", "origin"], cwd=d)
    if run(["git", "rev-parse", "--verify", "-q", branch], cwd=d, check=False).returncode == 0:
        run(["git", "switch", "-q", branch], cwd=d)
    else:
        run(["git", "switch", "-q", "-c", branch, "origin/main"], cwd=d)
    st.setdefault("gitops", {}).setdefault(task_id, {}).update({"repo": t["repo"], "order": t["order"], "branch": branch})
    save_state(repo, st)
    return d


SERVICE_REF = re.compile(r"^\s*service-ref\s*:", re.I | re.M)   # candidate lines of the spec 098 marker


def with_service_ref(body: str, ref: str) -> str:
    """`body` with exactly one line `Service-ref: <ref>` (ref = "<owner>/<repo>@<branch>").

    Every candidate line is removed; the marker takes the place of the first one. Without a candidate it is appended
    after one blank line. Every other line is kept byte-for-byte. Idempotent."""
    line, out, placed = f"Service-ref: {ref}\n", [], False
    for raw in body.splitlines(keepends=True):
        if not SERVICE_REF.match(raw):
            out.append(raw)
        elif not placed:
            out.append(line)
            placed = True
    if placed:
        return "".join(out)
    if not body.strip():
        return line
    return body + ("" if body.endswith("\n") else "\n") + "\n" + line


def gitops_pr(repo: Path, task_id: str, title: str, body_file: Path) -> dict:
    """Push the task's gitops branch and open (or reuse) its draft PR."""
    st = require_state(repo)
    t = _gitops_task(repo, st, task_id)
    info = st.get("gitops", {}).get(task_id)
    d = gitops_checkout(repo, t["repo"])
    if not info or not (d / ".git").exists():
        raise PlatformError(f"gitops task {task_id} has no checkout", hint=f"cplat component ship gitops prepare {task_id}")
    check_title(title)
    if not body_file.is_file():
        raise PlatformError(f"{body_file} does not exist")
    ahead = run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=d, check=False).stdout.strip()
    if ahead in {"", "0"}:
        raise PlatformError(f"{d} has no commit on {info['branch']}", hint="change the task's files there and commit first")
    run(["git", "push", "-q", "-u", "origin", info["branch"]], cwd=d)
    ref, marked = f"{service_slug(repo)}@{st['branch']}", d.parent / f"{task_id}-body.md"
    existing = json.loads(gh(["pr", "list", "-R", t["repo"], "--head", info["branch"], "--state", "open",
                              "--json", "number,url,body"], cwd=repo) or "[]")
    if existing:
        info["pr"] = existing[0]["url"]
        body = existing[0].get("body") or ""
        if with_service_ref(body, ref) != body:
            marked.write_text(with_service_ref(body, ref))
            gh(["pr", "edit", info["pr"], "--body-file", str(marked)], cwd=repo)
    else:
        marked.write_text(with_service_ref(body_file.read_text(), ref))
        out = gh(["pr", "create", "-R", t["repo"], "--draft", "--base", "main", "--head", info["branch"],
                  "--title", title, "--body-file", str(marked)], cwd=repo)
        info["pr"] = out.strip().splitlines()[-1]
    save_state(repo, st)
    return info


def merge_gitops(repo: Path, st: dict, order: str, timeout: float, interval: float,
                 queue_timeout: float) -> tuple[bool, list[str]]:
    """Merge the run's gitops PRs of one order, in plan order, each only after its checks passed."""
    lines: list[str] = []
    for t in gitops_tasks(repo, st, order):
        info = st.get("gitops", {}).get(t["id"]) or {}
        pr = info.get("pr")
        if not pr:
            raise PlatformError(f"gitops task {t['id']} ({order}) has no PR; nothing was merged",
                                hint=f"cplat component ship gitops prepare {t['id']}, commit, cplat component ship gitops pr {t['id']} ...")
        if info.get("merged"):
            continue
        view = json.loads(gh(["pr", "view", pr, "--json", "state,isDraft"], cwd=repo) or "{}")
        if view.get("state") == "CLOSED":
            raise PlatformError(f"gitops PR {pr} ({t['id']}) was closed without merging", hint="reopen it, or escalate")
        if view.get("state") != "MERGED":
            if view.get("isDraft"):
                gh(["pr", "ready", pr], cwd=repo, check=False)
            watch = CheckWatch(repo, pr, queue_timeout, st.get("run_id"))
            status, cs, failed = wait_checks(watch, timeout, interval)
            if status == "red" and watch.refused:
                return False, lines + refused(repo, st, watch.refused, red(repo, pr, cs, failed))
            if status == "red":
                return False, lines + [f"gitops task {t['id']} ({order}) is red; nothing more was merged"] + red(repo, pr, cs, failed)
            if st.get("product"):            # spec 097: one merge at a time, in the product plan's order
                import appship_merge
                gitops_dir, me = Path(st["product"]["dir"]), service_name(repo)
                try:
                    with appship_merge.slot(gitops_dir, me, appship_merge.plan_index(gitops_dir, me), timeout, interval):
                        appship_merge.merge(gitops_dir, pr, me, cwd=repo)
                except appship_merge.Conflict as e:
                    escalate(repo, str(e), "decision")
                    return False, lines + [str(e)]
                res = None
            else:
                res = run(["gh", "pr", "merge", pr, "--squash", "--delete-branch"], cwd=repo, check=False)
            if res is not None and res.returncode != 0:
                detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
                raise PlatformError(f"merging gitops PR {pr} failed: {detail[0]}", hint="escalate: a conflict is a human decision")
        info["merged"] = True
        save_state(repo, st)
        lines.append(f"merged gitops task {t['id']} ({order}): {pr}")
    return True, lines


# ---------------- deploy ----------------

def gitops_apps(repo: Path) -> list[str]:
    f = repo / ".platform-app.yml"
    return re.findall(r"^\s*-\s*([^\s#]+/[^\s#]+)", f.read_text(), re.M) if f.is_file() else []


def service_name(repo: Path) -> str:
    url = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/][^/]+/(.+?)(?:\.git)?$", url)
    return m.group(1) if m else repo.name


def _smoke_spec(repo: Path, st: dict) -> specmod.Spec | None:
    try:
        return specmod.find(repo, st["spec"])
    except PlatformError:
        return None


def _smoke_state(repo: Path, st: dict, result: smoke.SmokeResult, row: str, filed: dict | None) -> None:
    """The run record's `smoke` section and the state's summary. Never raises (a recording never changes the deploy)."""
    try:
        st["smoke"] = {"outcome": result.outcome, "row": row, "url": result.base_url, "reason": result.reason,
                       "digest": result.digest, "passed": result.passed, "failed": result.failed, "skipped": result.skipped,
                       "criteria": dict(result.criteria),
                       "signature": autoissue.signature("smoke", service_slug(repo), "dev", "\n".join(sorted(result.failing)))}
        runs.set_section(_ensure_run(repo, st), "smoke", {**result.section(filed), "image": st.get("deployed"),
                                                           "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    except Exception:  # noqa: BLE001
        pass


def _smoke_finish(repo: Path, st: dict, result: smoke.SmokeResult, lines: list[str], apps: list[str] | None = None,
                  svc: str | None = None, context: str | None = None, interval: float = 20) -> tuple[bool, list[str]]:
    """Record the smoke result, then end the deploy: after green or not run staging is promoted when the gitops-app asks for it
    (spec 093) and the run is done; escalated (cause code) when red."""
    lines = [*lines, *result.lines()]
    if result.outcome == "not-run":
        lines.append("NOT VERIFIED: the deploy was not checked by smoke tests, so nothing is promoted to staging")
    if result.outcome == "not-run" or result.ok:
        _smoke_state(repo, st, result, result.row(), None)
        lines.append(f"Smoke (dev): {result.row()}")
        ok, more = staging_deploy.promote(repo, st, apps or [], svc or service_name(repo), result, context, interval)
        lines += more
        return _done(repo, st, lines) if ok else (False, lines)
    sp = _smoke_spec(repo, st)
    sid = sp.id if sp else st["spec"]
    if result.failure_class == "environment":      # spec 105: the environment is broken, not the code: no issue, no promotion
        row = result.row()
        _smoke_state(repo, st, result, row, None)
        save_state(repo, st)
        reason = f"smoke red in dev: environment ({result.base_url})"
        skipped = staging_deploy.skip(repo, st, "dev smoke red", [])
        save_state(repo, st)
        escalate(repo, reason, "environment", report=lines)
        lines.append(f"ship {st['spec']}: escalated ({reason}); dev keeps running {st.get('deployed')}. "
                     f"Resume with /component:ship {st['spec']}")
        lines += skipped
        lines.append(f"Smoke (dev): {row}")
        return False, lines
    out = smoke.file_issue(result, service_slug=service_slug(repo), spec_id=sid, image=st.get("deployed"),
                           run_id=st.get("run_id"), shape=st.get("shape") or core.read_stamp(repo).get("shape", "none"))
    lines += out.lines
    if out.url:
        issue = out.url
    else:
        m = re.search(r"not filed: ([^;]*)", " ".join(out.lines))
        issue = f"not filed: {m.group(1).strip()}" if m else None
    filed = {"signature": out.signature, "url": out.url, "result": out.result}
    row = result.row(issue)
    _smoke_state(repo, st, result, row, filed)
    save_state(repo, st)
    reason = f"smoke red in dev: {len(result.failing)} failing ({sid})"
    skipped = staging_deploy.skip(repo, st, "dev smoke red", [])
    save_state(repo, st)
    escalate(repo, reason, "code", report=lines)
    lines.append(f"ship {st['spec']}: escalated ({reason}); dev keeps running {st.get('deployed')}. "
                 f"Resume with /component:ship {st['spec']}")
    lines += skipped
    lines.append(f"Smoke (dev): {row}")
    return False, lines


def _smoke_not_run(repo: Path, st: dict, reason: str, lines: list[str], apps: list[str] | None = None, svc: str | None = None,
                   context: str | None = None, interval: float = 20) -> tuple[bool, list[str]]:
    sp = _smoke_spec(repo, st)
    return _smoke_finish(repo, st, smoke.not_run("dev", reason, sp.smoke_acs() if sp else []), lines, apps, svc, context, interval)


def _smoke_step(repo: Path, st: dict, apps: list[str], svc: str, lines: list[str], base_url: str | None,
                context: str | None = None, interval: float = 20) -> tuple[bool, list[str]]:
    url, why = (base_url, None) if base_url else smoke.dev_url(repo, apps, svc)
    if not url:
        return _smoke_not_run(repo, st, why or "no dev URL", lines, apps, svc, context, interval)
    digest = cluster.running_digest(context, dev_namespace(repo, apps, svc), svc) if context else None
    if not digest:
        return _smoke_not_run(repo, st, "image digest unknown" + ("" if context else " (pass --context <kube-context>)"), lines, apps, svc, context, interval)
    prior = st.get("smoke") or {}
    if digest and prior.get("outcome") == "passed" and prior.get("digest") == digest:      # spec 105: a replay of a pass for this digest
        sec = {k: prior.get(k, 0) for k in ("passed", "failed", "skipped")}
        result = smoke.SmokeResult(env="dev", outcome="passed", base_url=prior.get("url") or url, digest=digest,
                                   criteria=dict(prior.get("criteria") or {}), **sec)
        return _smoke_finish(repo, st, result, [*lines, f"smoke (dev) already passed for {digest}: not run again"],
                             apps, svc, context, interval)
    result = smoke.run_smoke(repo, url, spec=_smoke_spec(repo, st), probe=smoke.liveness_probe(repo))
    result.digest = digest
    return _smoke_finish(repo, st, result, lines, apps, svc, context, interval)


def dev_namespace(repo: Path, apps: list[str], svc: str) -> str:
    """The namespace dev runs in: `<gitops-app dir>-dev` of the app that lists the service (fallback `<service>-dev`)."""
    try:
        me = service_slug(repo)
        for slug in apps:
            for a in smoke._app_dirs(slug, repo) or []:
                doc = smoke._read(slug, f"applications/{a}/system.yaml", repo)
                comps = model.build(doc, a).components if isinstance(doc, dict) else ()
                if any(c.repo == me or c.name == svc for c in comps):
                    return f"{a}-dev"
    except Exception:  # noqa: BLE001
        pass
    return f"{svc}-dev"


def deploy(repo: Path, timeout: float, interval: float, context: str | None,
           queue_timeout: float = QUEUE_TIMEOUT, base_url: str | None = None) -> tuple[bool, list[str]]:
    """Wait for each gitops-app's pin PR for the merge commit (spec 062) to merge, watching the service's main CI and
    the pin-dev run so a red or missing one fails at once (spec 077); then for Argo to run that build; then merge the
    after-release gitops PRs and wait for every app they name (spec 076)."""
    import shapecmd
    st = require_state(repo)
    if st["phase"] == "done":
        return True, ["already done"]
    if st.get("shape") == "platform" or (not st.get("shape") and shapecmd.resolve(repo) == "platform"):
        # spec 123: nothing to deploy; no kube context, pin PR, Argo, smoke or staging
        st["smoke"] = {"outcome": "not-run", "row": "not deployable", "reason": "not deployable (platform)"}
        st["staging"] = {"state": "skipped", "reason": "not deployable (platform)", "row": "Promotion (staging): not deployable"}
        return _done(repo, st, ["not deployable (platform): nothing to deploy", "Smoke (dev): not deployable",
                                "Promotion (staging): not deployable"])
    context = context or (st.get("product") or {}).get("context")
    if not context:                            # headless coordinators rarely pass --context: take the configured one
        import settings
        context, source = settings.kube_context(repo)
        if context:
            say(f"kube context: {context} ({source})")
    if st["phase"] == "done":
        return True, ["already done"]
    if not shapecmd.route(repo)["deployable"]:
        return _smoke_not_run(repo, st, "not deployable (library)", ["not deployable (library): nothing to deploy"])
    apps = gitops_apps(repo)
    if not apps:
        return _smoke_not_run(repo, st, "the repo is not linked to a gitops-app",
                              ["no .platform-app.yml: this repo is not linked to a gitops-app, so dev is not pinned "
                               "automatically; compose it with /component:add and link it (spec 062)"])
    if st.get("deployed") and (st.get("smoke") or {}).get("outcome") in {"red", "timed-out"}:
        return _smoke_step(repo, st, apps, service_name(repo), ["resuming: smoke only, against what dev runs now"], base_url,
                           context, interval)
    stg = st.get("staging") or {}
    if st.get("deployed") and (stg.get("state") == "pin-failed" or (stg.get("smoke") or {}).get("outcome") in {"red", "timed-out"}):
        ok, more = staging_deploy.resume(repo, st, apps, service_name(repo), context, interval)
        return _done(repo, st, more) if ok else (False, more)
    sha = st.get("merge_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise PlatformError("the run has no merge commit", hint="land the PR first: cplat component ship land")
    svc, short = service_name(repo), sha[:7]
    branch = f"pin/dev-{svc}-{short}"
    lines: list[str] = []
    begin = now()
    pending = list(apps)
    watches: dict[str, RunWatch] = {}
    green_at: float | None = None          # when the service's main CI for the merge commit was seen green
    while pending:
        ci, ci_runs = main_ci(repo, sha)
        if ci == "red":
            runs.ci_round(st.get("run_id"))
            return False, lines + [f"the service's CI on main is red for {short}; nothing was pinned"] + run_logs(repo, ci_runs)
        if ci == "green" and green_at is None:
            green_at = now()
            runs.ci_round(st.get("run_id"))
        for app in list(pending):
            prs = json.loads(gh(["pr", "list", "-R", app, "--state", "all", "--head", branch, "--json", "number,state,url"],
                                cwd=repo, check=False) or "[]")
            pr = prs[0] if prs else None
            if pr and pr["state"] == "MERGED":
                lines.append(f"{app}: dev pinned to {svc}:sha-{sha} ({pr['url']})")
                pending.remove(app)
                continue
            if pr and pr["state"] == "CLOSED":
                raise PlatformError(f"{app}: the pin PR {pr['url']} was closed without merging (a newer build superseded it, "
                                    "or its CI failed)", hint="read the PR's comments; `cplat component ship escalate 'pin failed'`")
            if app not in watches and (rid := pin_run(repo, app, svc, sha)):
                watches[app] = RunWatch(repo, app, rid, queue_timeout, st.get("run_id"))
            if app in watches:
                if watches[app].poll() == "red":
                    if watches[app].refused:
                        return False, lines + refused(repo, st, watches[app].refused, run_logs(repo, [(app, watches[app].rid)]))
                    return False, lines + [f"{app}: the pin-dev run for {short} failed; dev keeps the previous image"] + \
                        run_logs(repo, [(app, watches[app].rid)])
            elif green_at is not None and now() - green_at > NO_CHECKS_GRACE:
                raise PlatformError(f"{app}: no pin-dev run for {svc} {short} {NO_CHECKS_GRACE}s after the service's CI on "
                                    "main passed", hint=f"is the secret GITOPS_TOKEN set? gh secret list -R {service_slug(repo)} "
                                                        "(spec 062); then rerun the main CI run")
        if not pending:
            break
        if now() - begin > timeout:
            raise PlatformError(f"no merged pin PR {branch} after {int(timeout)}s in: {', '.join(pending)}",
                                hint="check the service's CI on main (docker-publish, pin-dev: is GITOPS_TOKEN set?) "
                                     "and the gitops-app's pin-dev workflow")
        sleep(interval)
    images = {f"sha-{sha}", f"sha-{short}"}
    if context:
        lines += _healthy(context, {f"{svc}-dev": {"images": images}}, timeout - (now() - begin), interval)
    ok, more = merge_gitops(repo, st, "after-release", timeout, interval, queue_timeout)
    lines += more
    if not ok:
        return False, lines
    affected = list(dict.fromkeys(a for t in gitops_tasks(repo, st) for a in t.get("apps") or []))
    if context and (affected or more):
        want: dict[str, dict] = {f"{svc}-dev": {"images": images}}
        rev = last_gitops_merge(repo, st)
        for a in affected:
            want.setdefault(a, rev)
        lines += _healthy(context, want, timeout, interval)
    elif not context:
        lines.append("Argo health not checked (pass --context <kube-context>)")
    st["deployed"] = f"sha-{sha}"
    save_state(repo, st)
    if not context:
        return _smoke_not_run(repo, st, "no kube context, so Argo health was not checked (pass --context <kube-context>)", lines,
                              apps, svc, context, interval)
    return _smoke_step(repo, st, apps, svc, lines, base_url, context, interval)


def service_slug(repo: Path) -> str:
    url = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else repo.name


def main_ci(repo: Path, sha: str) -> tuple[str, list[tuple[str, str]]]:
    """("red" | "green" | "pending" | "none", failed (slug, run id)) for the push runs of the merge commit on main."""
    slug = service_slug(repo)
    out = gh(["run", "list", "-R", slug, "--commit", sha, "--event", "push", "--json", "databaseId,status,conclusion"],
             cwd=repo, check=False)
    try:
        rs = json.loads(out or "[]")
    except ValueError:
        return "pending", []
    if not rs:
        return "none", []
    failed = [(slug, str(r["databaseId"])) for r in rs if r.get("conclusion") in {"failure", "cancelled", "timed_out"}]
    if failed:
        return "red", failed
    return ("green" if all(r.get("status") == "completed" for r in rs) else "pending"), []


def pin_run(repo: Path, app: str, svc: str, sha: str) -> str | None:
    """The gitops-app's pin-dev run for this build, found by its run name (`pin-dev <service> <tag>`, spec 077)."""
    out = gh(["run", "list", "-R", app, "--workflow", "pin-dev", "--limit", "30", "--json", "databaseId,displayTitle"],
             cwd=repo, check=False)
    try:
        rs = json.loads(out or "[]")
    except ValueError:
        return None
    names = {f"pin-dev {svc} sha-{sha}", f"pin-dev {svc} sha-{sha[:7]}"}
    hit = [r for r in rs if r.get("displayTitle") in names]
    return str(hit[0]["databaseId"]) if hit else None


class RunWatch:
    """One workflow run across polls (spec 077): red when it concludes failed; a run that stays queued for
    `queue_timeout` is cancelled and rerun once, the second time it is an error."""

    def __init__(self, repo: Path, slug: str, rid: str, queue_timeout: float, run_id: str | None = None):
        self.repo, self.slug, self.rid, self.queue_timeout = repo, slug, rid, queue_timeout
        self.run_id = run_id
        self.queued_since: float | None = None
        self.healed = False
        self.counted = False
        self.refused: str | None = None                    # spec 102: the budget refused the rerun

    def poll(self) -> str:
        out = gh(["run", "view", self.rid, "-R", self.slug, "--json", "status,conclusion"], cwd=self.repo, check=False)
        try:
            r = json.loads(out or "{}")
        except ValueError:
            return "pending"
        if r.get("status") == "completed":
            if not self.counted:                   # spec 087: one CI round per concluded pin-dev run
                self.counted = True
                runs.ci_round(self.run_id)
            return "green" if r.get("conclusion") in {"success", "skipped"} else "red"
        if r.get("status") != "queued":
            self.queued_since = None
            return "pending"
        self.queued_since = self.queued_since or now()
        if now() - self.queued_since > self.queue_timeout:
            if self.healed:
                raise PlatformError(f"run {self.rid} ({self.slug}) queued again after a cancel and rerun: the runner set "
                                    f"{runner_labels(self.slug, self.rid) or '?'} picks up no jobs", hint="escalate")
            if not budget.allow_rerun(self.run_id):
                self.refused = budget.REFUSED_RERUN
                return "red"
            say(f"  rerun    run {self.rid} ({self.slug}): queued for {int(now() - self.queued_since)}s (cancel + rerun)")
            cancel_and_rerun(self.repo, self.slug, self.rid)
            runs.rerun(self.run_id, "pin-dev", "stuck")
            self.healed, self.queued_since = True, None
        return "pending"


def run_logs(repo: Path, runs: list[tuple[str, str]], limit: int = 60) -> list[str]:
    out: list[str] = []
    for slug, rid in runs:
        log = gh(["run", "view", rid, "-R", slug, "--log-failed"], cwd=repo, check=False)
        tail = [ln for ln in log.splitlines() if ln.strip()][-limit:]
        out += [f"--- run {rid} ({slug}) ---", *tail]
    return out


def last_gitops_merge(repo: Path, st: dict) -> dict:
    """The merge commit (and repo) of the last gitops PR this run merged: the revision the named apps must reach."""
    merged = [i for i in (st.get("gitops") or {}).values() if i.get("merged") and i.get("pr")]
    if not merged:
        return {}
    view = json.loads(gh(["pr", "view", merged[-1]["pr"], "--json", "mergeCommit"], cwd=repo, check=False) or "{}")
    oid = (view.get("mergeCommit") or {}).get("oid")
    return {"revision": oid, "slug": merged[-1].get("repo", "")} if oid else {}


def _healthy(context: str, want: dict[str, dict], timeout: float, interval: float) -> list[str]:
    lines = []
    for app, need in want.items():
        health = argo_health(context, app, timeout, interval, **need)
        lines.append(f"Argo CD {app}: {health}")
        if health != "Synced/Healthy":
            raise PlatformError(f"{app} is {health}", hint=f"/system:status --context {context} in the gitops-app repo; escalate")
    return lines


def argo_health(context: str, app: str, timeout: float, interval: float, images: set[str] | None = None,
                revision: str | None = None, slug: str = "") -> str:
    """`Synced/Healthy` once the app runs the wanted build (spec 077: an image tag in `status.summary.images`, or a
    revision at least `revision`), a sync error of that build (stops at once), or the last state when the time is up."""
    begin = now()
    state = "missing"
    while True:
        p = run(["kubectl", "--context", context, "-n", "argocd", "get", "application", app, "-o", "json"], check=False)
        if p.returncode == 0:
            s = json.loads(p.stdout).get("status", {})
            have = s.get("summary", {}).get("images") or []
            rev = s.get("sync", {}).get("revision", "")
            if images and not any(img.rsplit(":", 1)[-1] in images for img in have):
                state = f"waiting for {sorted(images)[0][:11]}… (runs {', '.join(have) or 'nothing'})"
            elif revision and rev != revision and not _ahead(slug, revision, rev):
                state = f"waiting for revision {revision[:7]} (at {rev[:7] or '?'})"
            else:
                errors = [c for c in s.get("conditions") or [] if str(c.get("type", "")).endswith("Error")]
                op = s.get("operationState") or {}
                if errors:
                    return f"{errors[0]['type']}: {errors[0].get('message', '')}".strip()
                if op.get("phase") in {"Failed", "Error"}:
                    return f"sync {op['phase']}: {op.get('message', '')}".strip()
                state = f"{s.get('sync', {}).get('status', '?')}/{s.get('health', {}).get('status', '?')}"
                if state == "Synced/Healthy" or s.get("health", {}).get("status") == "Degraded":
                    return state
        if now() - begin > max(timeout, 0):
            return state
        sleep(interval)


def _ahead(slug: str, base: str, rev: str) -> bool:
    """Whether Argo's revision `rev` already contains `base` (a later commit on the gitops repo's main)."""
    if not rev or not slug:
        return False
    out = gh(["api", f"repos/{slug}/compare/{base}...{rev}", "--jq", ".status"], cwd=Path("."), check=False).strip()
    return out in {"ahead", "identical"}


def _done(repo: Path, st: dict, lines: list[str]) -> tuple[bool, list[str]]:
    st["phase"] = "done"
    save_state(repo, st)
    steps = plan_meta(repo, st).get("human_steps") or []
    if steps:
        lines = [*lines, "Human steps (the run cannot do these):", *(f"- [ ] {s}" for s in steps)]
    return True, lines


# ---------------- Stop hook ----------------

def _head(repo: Path, branch: str) -> str | None:
    r = run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], cwd=repo, check=False)
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def required_red(repo: Path, pr: str) -> bool:
    """True when a required check of the PR failed or was cancelled; false when `gh` fails (spec 126)."""
    try:
        out = gh(["pr", "checks", pr, "--required", "--json", "bucket"], cwd=repo, check=False)
        return any(c.get("bucket") in {"fail", "cancel"} for c in json.loads(out or "[]"))
    except (ValueError, AttributeError, PlatformError):
        return False


def no_progress_cause(repo: Path, st: dict, message: str, run_tests: bool = True) -> str:
    """The cause of a no-progress escalation: the rules on the last message, else the code-red evidence (spec 126)."""
    red = False
    phase = st.get("phase")
    if phase in ("plan", "build") and run_tests:
        red = build_red(repo, st["spec"])[1]
    elif phase in ("land", "deploy") and st.get("pr"):
        red = required_red(repo, st["pr"])
    return stopgate.cause(message, red)


def gate(repo: Path, hook_input: dict, run_tests: bool = True) -> dict | None:
    """None lets the session stop silently; a dict is the hook's JSON answer (spec 126: only the owner is held)."""
    try:
        st = load_state(repo)
    except PlatformError:
        return None
    if not st or st.get("escalated") or st["phase"] == "done":
        return None
    session = hook_input.get("session_id") or None
    mark = {"head": _head(repo, st["branch"]), "phase": st["phase"]}
    verdict = stopgate.check(st, session, mark)
    command = f"/component:ship {st['spec']}"
    if verdict.action == "silent":
        return None
    if verdict.action == "notice":
        return {"systemMessage": f"ship {st['spec']}: unfinished in phase {st['phase']}, no session owns it; resume it with {command}"}
    save_state(repo, st)
    if verdict.action == "escalate":
        message = stopgate.last_message(hook_input)
        cause = no_progress_cause(repo, st, message, run_tests)
        why = stopgate.no_progress_reason(st["phase"], message)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            escalate(repo, why, cause)
        return {"systemMessage": f"ship {st['spec']}: escalated ({why}); resume it with {command}"}
    reason = [f"The ship run of {st['spec']} is not finished (phase {st['phase']}, "
              f"stops without progress: {verdict.no_progress}/{stopgate.NO_PROGRESS_LIMIT}).",
              f"Next: {next_step(st)}."]
    if st["phase"] == "build" and run_tests:
        reason += build_status(repo, st["spec"])
    reason.append("Keep going. Only if a rule needs the user (a merge conflict after its re-plan, a changed acceptance test, a CRITICAL finding, "
                  "a decision the spec does not answer) or the user asked you to stop: run "
                  "`cplat component ship escalate '<reason>' --cause <platform|code|decision|environment>`, then stop.")
    return {"decision": "block", "reason": "\n".join(reason)}


def build_red(repo: Path, spec_id: str) -> tuple[list[str], bool]:
    """Trace and fast tests as lines, plus whether anything is red (a criterion without a test, red or unfinished tests)."""
    out: list[str] = []
    red = False
    tr = run([sys.executable, str(Path(__file__).with_name("cplat.py")), "spec", "trace", spec_id], cwd=repo, check=False, timeout=120)
    if tr.returncode != 0:
        red = True
        out.append("Criteria without a test:\n" + "\n".join(ln for ln in tr.stdout.splitlines() if ln.startswith("MISS")))
    if not (repo / "devbox.json").is_file():
        return out, red
    try:
        t = run(["devbox", "run", "test-fast"], cwd=repo, check=False, timeout=900)
    except PlatformError as e:
        return out + [f"`devbox run test-fast` did not finish: {e}"], True
    if t.returncode != 0:
        tail = [ln for ln in (t.stdout + t.stderr).splitlines() if ln.strip()][-30:]
        out.append("`devbox run test-fast` is red:\n" + "\n".join(tail))
        red = True
    else:
        out.append("`devbox run test-fast` is green.")
    return out, red


def build_status(repo: Path, spec_id: str) -> list[str]:
    """Trace and fast tests, so the model sees exactly what is still red."""
    return build_red(repo, spec_id)[0]


# ---------------- CLI ----------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat component ship", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("spec")
    p.add_argument("--no-merge", action="store_true", help="stop at a green PR; you merge")
    p.add_argument("--take-over", action="store_true", help="move a claim on a tracked issue to this run (spec 082)")
    p.add_argument("--system-dir", default=None, help="the gitops-app clone of the system ship this run belongs to (/system:ship only, spec 097)")
    p.add_argument("--budget", action="append", default=[], metavar="KEY=VALUE",
                   help="replace a limit of the run's budget: minutes, invocations, reruns, cost (a number or off; spec 102)")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("phase")
    p.add_argument("phase", choices=PHASES)
    p = sub.add_parser("pr")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", required=True)
    g = sub.add_parser("gitops").add_subparsers(dest="gcmd", required=True)
    p = g.add_parser("prepare")
    p.add_argument("task")
    p = g.add_parser("pr")
    p.add_argument("task")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", required=True)
    p = sub.add_parser("land")
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--interval", type=float, default=20)
    p.add_argument("--queue-timeout", type=float, default=QUEUE_TIMEOUT, help="cancel and rerun a run whose jobs stay queued this long")
    p = sub.add_parser("deploy")
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--interval", type=float, default=20)
    p.add_argument("--queue-timeout", type=float, default=QUEUE_TIMEOUT)
    p.add_argument("--context", help="kube context: also wait for Argo CD to report <service>-dev Synced/Healthy")
    p.add_argument("--base-url", default=None, help="run the smoke tests against this URL instead of the gitops-app's dev URL")
    p = sub.add_parser("escalate")
    p.add_argument("reason", nargs="+")
    p.add_argument("--cause", default=None, help=f"who must act: {_ALLOWED} (run record; `platform` is filed as an issue, spec 088)")
    p.add_argument("--command", default=None, help="the failing command (cause platform; default /component:ship)")
    p.add_argument("--evidence-file", default=None, help="failing output for the issue (cause platform); - reads stdin")
    sub.add_parser("finish")
    sub.add_parser("gate")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()

    if ns.cmd == "gate":
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        try:
            hook = json.loads(raw) if raw.strip() else {}
        except ValueError:
            hook = {}
        cwd = Path(hook.get("cwd") or repo)
        answer = gate(cwd, hook)
        if answer:
            print(json.dumps(answer))
        return 0
    if ns.cmd == "start":
        st = start(repo, ns.spec, not ns.no_merge, ns.take_over, Path(ns.system_dir).resolve() if ns.system_dir else None, ns.budget)
        if st["phase"] in ("plan", "build", "pr"):
            say(on_branch(repo, st["branch"]))
        print(describe(st))
        if line := budget.limits_line(st.get("run_id")):
            print(line)
        return 0
    if ns.cmd == "status":
        st = require_state(repo)
        print(json.dumps({**st, "next": next_step(st)}, indent=2) if ns.json else describe(st))
        return 0
    if ns.cmd == "phase":
        print(describe(set_phase(repo, ns.phase)))
        return 0
    if ns.cmd == "pr":
        st = open_pr(repo, ns.title, core.stage_pr_body(repo, ns.body_file))
        print(f"PR: {st['pr']}\n{describe(st)}")
        return 0
    if ns.cmd == "gitops" and ns.gcmd == "prepare":
        print(f"gitops checkout for {ns.task}: {gitops_prepare(repo, ns.task)}\nchange the task's files there, commit, "
              f"then `cplat component ship gitops pr {ns.task} --title <title> --body-file <file>`")
        return 0
    if ns.cmd == "gitops":
        info = gitops_pr(repo, ns.task, ns.title, core.stage_pr_body(repo, ns.body_file))
        print(f"gitops PR ({info['order']}): {info['pr']}")
        return 0
    if ns.cmd == "land":
        ok, lines = land(repo, ns.timeout, ns.interval, ns.queue_timeout)
        print("\n".join(lines))
        return 0 if ok else 1
    if ns.cmd == "deploy":
        ok, lines = deploy(repo, ns.timeout, ns.interval, ns.context, ns.queue_timeout, ns.base_url)
        print("\n".join(lines))
        return 0 if ok else 1
    if ns.cmd == "escalate":
        evidence = ""
        if ns.evidence_file:
            try:
                evidence = sys.stdin.read() if ns.evidence_file == "-" else Path(ns.evidence_file).read_text(errors="replace")
            except (OSError, ValueError):
                evidence = ""
        report: list[str] = []
        st = escalate(repo, " ".join(ns.reason), ns.cause, command=ns.command, evidence=evidence, report=report)
        shown = st["escalated"]
        if st.get("cause") == "platform":     # the output goes where the issue goes: no repo, spec, branch or secret
            shown = autoissue.scrub(shown, autoissue.private_names(runs.repo_slug(repo), st.get("spec"), st.get("branch")))
        print(f"ship {st['spec']}: escalated ({shown}); the session may stop. Resume with /component:ship {st['spec']}")
        for line in report:
            print(line)
        return 0
    if ns.cmd == "finish":
        print(f"ship run ended; state archived to {finish(repo)}")
        return 0
    return 2
