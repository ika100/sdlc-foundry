"""Spec 167: everything that happens to one dispatcher unit and the GitHub writes it makes (design.md "Units").

  start(repo, slug, cand, mode, slot, policy) -> Start   claim, worktree, unit file, run record, detached headless process
  adopt(repo, slug) -> [unit]                              the unit files of the repo's dispatcher worktrees that are not ended
  observe(repo, slug, unit) -> Obs                         what the unit's process, result file and PR say (the design's table)
  advance(repo, slug, unit, policy) -> Step                observe, then act: land, finish, escalate, restart, stuck
  land(repo, slug, unit_id) -> int                         the hidden `cplat dispatch land <unit>` verb: wait for CI and merge
  pause_flags / clear_flags / resume_paused                steering (AC-167.11)
  close_stale(repo, slug, number, evidence, why)           the premise check found the issue resolved on main (AC-167.4)
  cleanup(repo, slug, read_at)                             remove the worktrees of done units once a newer snapshot has seen them

Every step is written to the unit file (in the unit worktree's git dir, under a lock) before the next one is taken, and a step that
GitHub already shows (a claim for the same branch) is not made twice, so a killed dispatcher that starts again repeats nothing
(AC-167.9). The functions return the action lines `cplat dispatch start` prints. `book` of the daily budget runs before a unit is
finished and before its worktree goes, so its last tokens are counted. `alive`, `spawn`, `spawn_land` and `gh` are the seams tests replace.
"""
from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import claim
import core
import dispatch_budget
import dispatch_notify
import dispatch_policy
import dispatch_state as ds
import merge_lock
import pr as prmod
import runs
import ship
import spec as specmod
from core import PlatformError

CPLAT = Path(__file__).resolve().with_name("cplat.py")
MAX_STARTS = 2                      # a unit whose process ended unfinished is started once more; a second end is stuck
ENDED = ("done", "escalated", "stuck")
LAND_TIMEOUT = 7200
LAND_INTERVAL = 20
NEEDS_DECISION = "needs-decision"
STALE_LABEL = "stale-premise"
STALE_MARK = "<!-- cplat-dispatch-stale -->"
ESCALATION_MARK = "<!-- cplat-dispatch-escalation -->"
STASH_MESSAGE = "cplat dispatch: before restart"
EXCERPT = 300


# ---------------- results ----------------

@dataclass
class Start:
    unit: dict | None = None
    held: str | None = None              # `claimed` when the claim was refused (nothing was left behind)
    detail: str | None = None
    lines: list[str] = field(default_factory=list)


@dataclass
class Step:
    lines: list[str] = field(default_factory=list)
    needs: list[dict] = field(default_factory=list)      # new `stuck` needs (the cycle passes them to `dispatch_notify.write_needs`)


@dataclass
class Obs:
    """`running`, `landing`, `paused`, `ended` (nothing to do), or what to do: `land`, `restart-land`, `done`, `escalate`,
    `restart`, `stuck`."""
    state: str
    reason: str | None = None
    cause: str | None = None
    pr: str | None = None
    run: str | None = None
    event: str = "escalated"


# ---------------- seams ----------------

def gh(args: list[str], *, cwd: Path | str) -> str | None:   # tests replace this
    """The output of a `gh` call; None when it failed or `gh` is not there."""
    try:
        p = core.run(["gh", *args], cwd=cwd, check=False)
    except PlatformError:
        return None
    return p.stdout if p.returncode == 0 else None


def git(args: list[str], *, cwd: Path | str, check: bool = True) -> str:
    return core.run(["git", *args], cwd=cwd, check=check).stdout.strip()


def alive(pid: int | None) -> bool:
    """True while the process runs (a finished child of this process is reaped, so it does not count). A reused pid that runs something
    else is not ours: its command must name `headless` (or the executable of `$CPLAT_DISPATCH_HEADLESS`) or `dispatch land`."""
    if not pid:
        return False
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    out = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        return False
    exe = os.path.basename(os.environ.get("CPLAT_DISPATCH_HEADLESS") or "")
    return "headless" in out.stdout or "dispatch land" in out.stdout or bool(exe and exe in out.stdout)


def _detach(cmd: list[str], cwd: Path | str, env: dict[str, str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    return p.pid


def headless_cmd(unit: dict, policy) -> list[str]:
    """`cplat headless --repo <worktree> [--budget K=V …] [--parallel 3|1 (ship)] "<prompt>"`; `$CPLAT_DISPATCH_HEADLESS` replaces
    `cplat headless` (the seam of the fake headless)."""
    exe = os.environ.get("CPLAT_DISPATCH_HEADLESS")
    cmd = [exe] if exe else [sys.executable, str(CPLAT), "headless"]
    cmd += ["--repo", str(unit["worktree"]), *dispatch_policy.budget_args(policy)]
    if unit["kind"] == "ship":
        cmd += ["--parallel", "3" if unit.get("mode") == "team" else "1", f"/component:ship {unit['spec']}"]
    else:
        cmd.append(f"/component:fix {unit['item']}")
    return cmd


def spawn(unit: dict, policy) -> int:   # tests replace this
    """Start the unit's headless process detached, in its worktree, under the unit's run record. Returns its pid. Raises OSError."""
    wt = unit["worktree"]
    with contextlib.suppress(OSError):
        ds.result_path(wt).unlink()          # a result of an earlier start never speaks for this one
    env = {**os.environ, "CPLAT_DISPATCH_UNIT": unit["unit"], "CPLAT_DISPATCH_RESULT": str(ds.result_path(wt))}
    if unit.get("run_id"):
        env["CPLAT_RUN_PARENT"] = unit["run_id"]       # readiness counts the unit's own runs by the parent chain
    return _detach(headless_cmd(unit, policy), wt, env, Path(unit["log"]))


def spawn_land(repo: Path, unit: dict) -> int:   # tests replace this
    """Start `cplat dispatch land <unit>` detached. Returns its pid. Raises OSError."""
    env = {**os.environ}
    if unit.get("run_id"):
        env["CPLAT_RUN_PARENT"] = unit["run_id"]
    cmd = [sys.executable, str(CPLAT), "dispatch", "land", unit["unit"], "--repo", str(repo)]
    return _detach(cmd, repo, env, Path(unit["log"]))


# ---------------- the unit file ----------------

def update_unit(worktree: Path | str, fn: Callable[[dict], object]) -> dict:
    """Read-modify-write of the unit file under a lock (the dispatcher and its land process both write it)."""
    gd = ds.unit_git_dir(worktree)
    with ds._flock(gd / "cplat-dispatch-unit.lock"):
        unit = ds.read_unit(worktree) or {}
        out = fn(unit)
        if isinstance(out, dict):
            unit = out
        ds.write_unit(worktree, unit)
        return unit


def _one_line(text: object, limit: int = EXCERPT) -> str:
    return " ".join(str(text or "").split())[:limit]


def _log_of(unit: dict) -> str:
    return str(unit.get("log") or "")


def _issues_of(unit: dict) -> list[int]:
    """The issues the unit claims: a fix unit its issue, a ship unit the issues its spec tracks."""
    if unit.get("kind") == "fix":
        return [int(str(unit["item"]).lstrip("#"))]
    return [int(n) for n in unit.get("tracks") or []]


def _open_issues(repo: Path, numbers: list[int]) -> list[int]:
    out = []
    for n in numbers:
        try:
            state = json.loads(gh(["issue", "view", str(n), "--json", "state"], cwd=repo) or "{}").get("state")
        except ValueError:
            state = None
        if state in (None, "OPEN"):         # GitHub not answering: treat as open (the writes are best effort)
            out.append(n)
    return out


def _branch_of(kind: str, number: int | None, spec_id: str | None) -> str:
    return f"fix/issue-{number}" if kind == "fix" else f"feature/{spec_id}"


def _ensure_label(repo: Path, name: str, color: str, description: str) -> None:
    gh(["label", "create", name, "--color", color, "--description", description], cwd=repo)


def _pr_number(url: str | None) -> int | None:
    tail = str(url or "").rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _book(slug: str) -> dispatch_budget.Usage:
    """Book the growth of every unit's tokens (call before a unit is finished or a worktree removed)."""
    return dispatch_budget.book(slug, ds.all_units(slug))


# ---------------- start ----------------

def _registered(repo: Path, path: Path) -> bool:
    out = git(["worktree", "list", "--porcelain"], cwd=repo, check=False)
    return any(line == f"worktree {path}" or line == f"worktree {path.resolve()}" for line in out.splitlines())


def _ref_exists(repo: Path, ref: str) -> bool:
    return core.run(["git", "rev-parse", "--verify", "-q", ref], cwd=repo, check=False).returncode == 0


def _worktree(repo: Path, slug: str, cand, branch: str) -> tuple[Path, bool]:
    """The unit's worktree on its branch: an existing one is reused, a new one starts from the draft's PR branch, the remote branch
    of the unit, else `origin/main`. Returns (path, created)."""
    path = ds.worktree_path(slug, cand.key)
    if path.is_dir() and _registered(repo, path):
        return path, False
    git(["worktree", "prune"], cwd=repo, check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _ref_exists(repo, f"refs/heads/{branch}"):
        git(["worktree", "add", str(path), branch], cwd=repo)
        return path, False
    base = "origin/main"
    draft = (cand.pr or {}).get("head") if cand.kind == "ship" else None
    for head in [h for h in (branch, draft) if h]:
        git(["fetch", "-q", "origin", head], cwd=repo, check=False)
        if _ref_exists(repo, f"refs/remotes/origin/{head}"):
            base = f"origin/{head}"
            break
    git(["worktree", "add", "-b", branch, str(path), base], cwd=repo)
    return path, True


def _discard(repo: Path, path: Path, branch: str, created: bool) -> None:
    git(["worktree", "remove", "--force", str(path)], cwd=repo, check=False)
    if created:
        git(["branch", "-D", branch], cwd=repo, check=False)


def _self_approve(path: Path, spec_id: str) -> bool:
    """Approve the draft in the unit's worktree (`approved by cplat dispatch` in its changelog) and commit it signed off.
    False when the spec is no draft any more (a restart finds it approved)."""
    sp = specmod.find(path, spec_id)
    if sp.status != "draft":
        return False
    specmod.approve(sp, specmod.repo_shape(path), by=claim.DISPATCH)
    git(["add", "--", f"docs/specs/{spec_id}"], cwd=path)
    git([*core.git_identity(path), "commit", "-q", "-s", "-m", f"docs(spec): approve {spec_id} ({claim.DISPATCH})"], cwd=path)
    return True


def _claim(repo: Path, numbers: list[int], branch: str) -> list[int]:
    """Claim each issue for the branch; returns the issues newly claimed. Raises PlatformError when another branch holds one (the
    ones claimed before are released again: nothing is left behind)."""
    fresh: list[int] = []
    try:
        for n in numbers:
            notes = claim.claim(repo, [n], branch, what=claim.DISPATCH)
            if any("claimed for" in note for note in notes):
                fresh.append(n)
    except PlatformError:
        if fresh:
            claim.release(repo, fresh, "not started: another issue of the item is claimed elsewhere (cplat dispatch)")
        raise
    return fresh


def start(repo: Path, slug: str, cand, mode: str, slot: int, policy) -> Start:
    """Design steps 1 to 4 for a ready candidate (`dispatch_backlog.Candidate`). A refused claim returns `held == "claimed"`."""
    repo = Path(repo)
    kind = cand.kind
    branch = _branch_of(kind, cand.number, cand.spec_id)
    mode = "single" if kind == "fix" else mode
    numbers = [cand.number] if kind == "fix" else [int(n) for n in cand.tracks]
    try:
        fresh = _claim(repo, numbers, branch)
    except PlatformError as e:
        return Start(held="claimed", detail=str(e).splitlines()[0])
    lines: list[str] = []
    try:
        path, created = _worktree(repo, slug, cand, branch)
        if kind == "ship" and cand.status == "draft" and _self_approve(path, cand.spec_id):
            lines.append(f"approved {cand.item} ({claim.DISPATCH})")
    except PlatformError as e:
        if fresh:
            claim.release(repo, fresh, "not started: the worktree could not be made (cplat dispatch)")
        return Start(held="claimed", detail=str(e).splitlines()[0])
    unit_id = ds.next_unit(slug, cand.key)
    run_id = runs.start("dispatch", repo=slug, spec=cand.spec_id)
    if kind == "fix":
        runs.set_section(run_id, "issue", {"repo": slug, "number": cand.number, "url": f"https://github.com/{slug}/issues/{cand.number}"})
    runs.set_section(run_id, "dispatch", {"unit": unit_id, "kind": kind, "mode": mode, "branch": branch})
    draft_pr = (cand.pr or {}).get("number") if cand.pr and cand.pr.get("head") != branch else None
    unit = {"unit": unit_id, "item": cand.item, "key": cand.key, "kind": kind, "mode": mode, "branch": branch, "worktree": str(path),
            "slot": slot, "pid": None, "land_pid": None, "log": str(ds.log_path(slug, unit_id)), "starts": 1, "run_id": run_id,
            "status": "starting", "pr": None, "started_at": ds.stamp(), "ended_at": None, "reason": None, "tokens": None,
            "spec": cand.spec_id, "tracks": list(cand.tracks), "draft_pr": draft_pr}
    ds.write_unit(path, unit)
    ds.unpin(slug, cand.key)
    try:
        pid = spawn(unit, policy)
    except OSError as e:
        step = escalate(repo, slug, unit, f"the headless process could not be started: {e}", "environment")
        return Start(unit=ds.read_unit(path), lines=[*lines, *step.lines])
    unit = update_unit(path, lambda u: u.update(pid=pid, status="running"))
    ds.events_add(slug, "started", unit_id, cand.item)
    lines.append(f"started {unit_id} ({kind}, {mode}, slot {slot}): {shlex.join(headless_cmd(unit, policy))}  log: {unit['log']}")
    return Start(unit=unit, lines=lines)


# ---------------- observe ----------------

def _ship_state(worktree: str) -> dict | None:
    try:
        return ship.load_state(Path(worktree))
    except (PlatformError, OSError):
        return None


def unit_pr(repo: Path, branch: str) -> dict | None:
    """The unit branch's pull request `{number, url, state}`: the open one, else the newest."""
    try:
        rows = json.loads(gh(["pr", "list", "--head", branch, "--state", "all", "--limit", "10", "--json", "number,url,state"], cwd=repo) or "[]")
    except ValueError:
        return None
    rows = [r for r in rows if isinstance(r, dict) and r.get("url")]
    return next((r for r in rows if r.get("state") == "OPEN"), None) or max(rows, key=lambda r: r.get("number") or 0, default=None)


def observe(repo: Path, slug: str, unit: dict) -> Obs:
    """The design's table, for one unit that is not ended: what its process, result file, ship state and pull request say."""
    status = unit.get("status")
    if status in ENDED:
        return Obs("ended")
    if status == "paused":
        return Obs("paused")
    if status == "landing":
        return _observe_land(unit)
    if alive(unit.get("pid")):
        return Obs("running")
    return _classify(repo, unit)


def _observe_land(unit: dict) -> Obs:
    if alive(unit.get("land_pid")):
        return Obs("landing")
    landed, summary = unit.get("landed"), _one_line(unit.get("landed_summary")) or None
    if landed == "merged":
        return Obs("done", pr=unit.get("pr"))
    if landed == "red":
        return Obs("escalate", reason=summary or "the checks of the pull request are red", cause="code", pr=unit.get("pr"), event="red")
    if landed in ("closed", "merge-failed"):
        return Obs("escalate", reason=summary or f"the pull request could not be merged ({landed})", cause="decision", pr=unit.get("pr"),
                   event="red")
    return Obs("restart-land" if int(unit.get("land_starts") or 0) < MAX_STARTS else "stuck")      # the land process died


def _classify(repo: Path, unit: dict) -> Obs:
    wt = str(unit["worktree"])
    res = ds.read_result(wt)
    if res and res.get("unit") not in (None, unit["unit"]):
        res = None
    ended = res if res and res.get("ended_at") else None
    text = str((ended or {}).get("result") or "")
    outcome, stop = (ended or {}).get("outcome"), (ended or {}).get("stop_reason")
    if unit["kind"] == "ship":
        st = _ship_state(wt) or {}
        if st.get("phase") == "done" or text.startswith("shipped"):
            return Obs("done")
        if st.get("escalated"):
            return Obs("escalate", reason=str(st["escalated"]), cause=st.get("cause") or "unknown", run=st.get("run_id"))
        if outcome == "escalated":
            return Obs("escalate", reason=text or "the run escalated", cause=(ended or {}).get("cause") or "unknown")
    elif outcome == "escalated":
        return Obs("escalate", reason=text or "the run escalated", cause=(ended or {}).get("cause") or "unknown")
    if stop == "paused":
        return Obs("paused")
    if unit["kind"] == "fix" and outcome == "done":
        pr = unit_pr(repo, unit["branch"])
        if pr and pr["state"] == "MERGED":
            return Obs("done", pr=pr["url"])
        if pr and pr["state"] == "OPEN":
            return Obs("paused") if ds.stop_path(wt).exists() else Obs("land", pr=pr["url"])
        return Obs("escalate", cause="decision", reason=f"the fix run ended without a pull request: {_one_line(text) or 'no message'}")
    return Obs("restart")


# ---------------- acting ----------------

def advance(repo: Path, slug: str, unit: dict, policy) -> Step:
    """Observe the unit and take the step its state calls for."""
    repo = Path(repo)
    obs = observe(repo, slug, unit)
    wt = unit["worktree"]
    if obs.state == "paused":
        if unit.get("status") != "paused":
            update_unit(wt, lambda u: u.update(status="paused"))
        return Step()
    if obs.state == "land":
        return Step(_start_land(repo, unit, obs.pr))
    if obs.state == "restart-land":
        return Step(_start_land(repo, unit, unit.get("pr")))
    if obs.state == "done":
        return Step(finish_done(repo, slug, unit, obs.pr))
    if obs.state == "escalate":
        return escalate(repo, slug, unit, obs.reason or "the run escalated", obs.cause, run=obs.run, event=obs.event, pr=obs.pr)
    if obs.state == "stuck" or (obs.state == "restart" and int(unit.get("starts") or 1) >= MAX_STARTS):
        return make_stuck(repo, slug, unit)
    if obs.state == "restart":
        return Step(restart(repo, slug, unit, policy))
    return Step()


def _start_land(repo: Path, unit: dict, pr: str | None) -> list[str]:
    n = int(unit.get("land_starts") or 0) + 1
    update_unit(unit["worktree"], lambda u: u.update(status="landing", pr=pr, landed=None, landed_summary=None, land_starts=n))
    try:
        pid = spawn_land(repo, {**unit, "pr": pr})
    except OSError as e:
        update_unit(unit["worktree"], lambda u: u.update(land_pid=None, landed="merge-failed", landed_summary=f"the land process could not be started: {e}"))
        return []
    update_unit(unit["worktree"], lambda u: u.update(land_pid=pid))
    return [f"landing {unit['unit']}: {pr}"]


def land(repo: Path, slug: str, unit_id: str) -> int:
    """`cplat dispatch land <unit>`: wait for the checks of the unit's pull request and merge it (under the merge lock). The unit file
    gets `landed` (`merged`, `red`, `closed`, `merge-failed`) and the summary. Exit 0 when merged."""
    wt = ds.worktree_path(slug, ds.unit_key(unit_id))
    unit = ds.read_unit(wt)
    if not unit or unit.get("unit") != unit_id or not unit.get("pr"):
        raise PlatformError(f"no unit {unit_id} with a pull request in {wt}", "`cplat dispatch status` lists the units")
    try:
        ok, lines = prmod.wait(wt, str(unit["pr"]), True, LAND_TIMEOUT, LAND_INTERVAL, ship.QUEUE_TIMEOUT, slug)
        landed, lines = ("merged" if ok else "red"), list(lines)
    except prmod.Closed as e:
        landed, lines = "closed", [str(e)]
    except merge_lock.Busy:
        raise
    except (prmod.MergeFailed, merge_lock.Conflict) as e:
        landed, lines = "merge-failed", [str(e)]
    except PlatformError as e:                  # checks that never came or never ended
        landed, lines = "merge-failed", [str(e)]
    summary = "\n".join(lines)[-2000:]
    print(summary, flush=True)
    update_unit(wt, lambda u: u.update(landed=landed, landed_summary=summary))
    return 0 if landed == "merged" else 1


def _end(repo: Path, slug: str, unit: dict, status: str, *, reason: str | None = None, cause: str | None = None, run: str | None = None,
         event: str | None = None, pr: str | None = None) -> dict:
    """The common end of a unit: book its tokens, finish its run record, add the history entry, write the unit file, add the event."""
    _book(slug)
    wt = unit["worktree"]
    tokens = dispatch_budget.unit_tokens(unit, ds.read_result(wt))
    pr = pr or unit.get("pr")
    ended = ds.stamp()
    fields: dict = {"tokens": tokens}
    if pr:
        fields["pr"] = {"number": _pr_number(pr), "url": pr}
    if status == "done":
        runs.finish(unit.get("run_id"), "done", fields=fields)
    else:
        escalation = {"reason": reason or "", "cause": cause or "unknown"}
        if run:
            escalation["run"] = run         # the escalated ship run this unit served: the needs list shows that run's item
        runs.finish(unit.get("run_id"), "escalated", escalation=escalation, fields=fields)
    ds.history_add(slug, {"unit": unit["unit"], "item": unit["item"], "kind": unit["kind"], "outcome": status, "pr": pr, "tokens": tokens,
                          "reason": reason, "started_at": unit.get("started_at"), "ended_at": ended})
    ended_unit = update_unit(wt, lambda u: u.update(status=status, ended_at=ended, reason=reason, cause=cause, tokens=tokens, pr=pr))
    ds.events_add(slug, event or status, unit["unit"], unit["item"], reason, pr)
    return ended_unit


def finish_done(repo: Path, slug: str, unit: dict, pr: str | None = None) -> list[str]:
    """A merged unit: release the claim, finish the run record, add the history entry, free the slot. The worktree stays until
    `cleanup` (a snapshot read before the merge would otherwise show the item as open again with no unit to say it is done)."""
    repo = Path(repo)
    pr = pr or unit.get("pr") or (unit_pr(repo, unit["branch"]) or {}).get("url")
    numbers = _issues_of(unit)
    if numbers:
        claim.release(repo, numbers, f"done in {pr} (cplat dispatch)")
    done = _end(repo, slug, unit, "done", pr=pr)
    if unit.get("draft_pr") and pr:
        gh(["pr", "close", str(unit["draft_pr"]), "--comment", f"Superseded by {pr}: cplat dispatch shipped {unit['spec']} on {unit['branch']}."], cwd=repo)
    return [f"done {done['unit']}: {pr}"]


def _note(unit: dict, reason: str) -> str:
    return f"{ESCALATION_MARK}\n{reason}\nLog: {_log_of(unit)}\nRemove the label {NEEDS_DECISION} to let cplat dispatch try again."


def escalate(repo: Path, slug: str, unit: dict, reason: str, cause: str | None, *, run: str | None = None, event: str = "escalated",
             pr: str | None = None, status: str = "escalated") -> Step:
    """Release the claim, label the issue (a spec: each open tracked issue) `needs-decision` with the reason and the log path, finish the
    run record `escalated`, add the event and free the slot; the worktree stays. Without an open issue the item is held in the state."""
    repo = Path(repo)
    reason = reason.strip() or "the run escalated"
    open_issues = _open_issues(repo, _issues_of(unit))
    if open_issues:
        claim.release(repo, open_issues, f"escalated: {_one_line(reason, 200)} (cplat dispatch)")
        _ensure_label(repo, NEEDS_DECISION, "D93F0B", "a decision of the user holds this item (spec 167)")
        for n in open_issues:
            gh(["issue", "edit", str(n), "--add-label", NEEDS_DECISION], cwd=repo)
            gh(["issue", "comment", str(n), "--body", _note(unit, reason)], cwd=repo)
    if not open_issues or (status == "stuck" and unit["kind"] == "ship"):
        ds.hold(slug, unit["key"], "stuck" if status == "stuck" else "needs-decision", unit["unit"])
    ended = _end(repo, slug, unit, status, reason=reason, cause=cause, run=run, event=event, pr=pr)
    if status == "stuck":
        need = dispatch_notify.stuck_need(slug, ended, cause or "environment")
        dispatch_notify.write_needs(slug, [need])
        return Step([f"stuck {ended['unit']}: {_log_of(ended)}"], [need])
    return Step([f"escalated {ended['unit']}: {_one_line(reason)}"])


def make_stuck(repo: Path, slug: str, unit: dict) -> Step:
    """A unit that ended twice without finishing (cause `environment`): escalated and stuck, with a `stuck` need naming the log."""
    reason = f"unit {unit['unit']} ended twice without finishing (cause environment); log: {_log_of(unit)}"
    return escalate(repo, slug, unit, reason, "environment", status="stuck", event="stuck")


def restart(repo: Path, slug: str, unit: dict, policy, *, count: bool = True) -> list[str]:
    """Start the unit's process again in the same worktree with the same command; a fix worktree with uncommitted changes is stashed
    first. `count` False (a resumed pause) does not count as a restart."""
    wt = unit["worktree"]
    if unit["kind"] == "fix" and git(["status", "--porcelain"], cwd=wt, check=False):
        git(["stash", "push", "-u", "-m", STASH_MESSAGE], cwd=wt, check=False)
    ds.clear_stop(wt)
    starts = int(unit.get("starts") or 1) + (1 if count else 0)
    try:
        pid = spawn(unit, policy)
    except OSError as e:
        return escalate(repo, slug, unit, f"the headless process could not be started: {e}", "environment").lines
    update_unit(wt, lambda u: u.update(pid=pid, starts=starts, status="running"))
    return [f"restarted {unit['unit']} (start {starts})" if count else f"restarted {unit['unit']} (resumed)"]


# ---------------- pause ----------------

def pause_flags(units: list[dict]) -> list[str]:
    """Write the stop flag into every running unit (a landing unit is not interrupted); returns the units flagged."""
    flagged = []
    for u in units:
        if u.get("status") in ("starting", "running"):
            with contextlib.suppress(OSError, PlatformError):
                ds.set_stop(u["worktree"])
                flagged.append(u["unit"])
    return flagged


def clear_flags(units: list[dict]) -> None:
    for u in units:
        ds.clear_stop(u["worktree"])


def resume_paused(repo: Path, slug: str, unit: dict, policy) -> Step:
    """Resume a paused unit (claims kept, no restart counted): a fix whose session had ended with an open pull request lands, any
    other unit starts its process again."""
    repo = Path(repo)
    ds.clear_stop(unit["worktree"])
    if unit["kind"] == "fix":
        res = ds.read_result(unit["worktree"]) or {}
        if res.get("ended_at") and res.get("outcome") == "done":
            pr = unit_pr(repo, unit["branch"])
            if pr and pr["state"] == "OPEN":
                return Step(_start_land(repo, unit, pr["url"]))
            if pr and pr["state"] == "MERGED":
                return Step(finish_done(repo, slug, unit, pr["url"]))
    return Step(restart(repo, slug, unit, policy, count=False))


# ---------------- adopt ----------------

def adopt(repo: Path, slug: str) -> list[dict]:
    """The units of the repo's dispatcher worktrees that are not ended, read from their unit files (nothing is kept in memory)."""
    return [u for u in ds.all_units(slug) if u.get("status") not in ENDED]


def adopted_lines(units: list[dict]) -> list[str]:
    """`adopted <unit> (pid N)` for each unit whose process still lives (a landing unit: its land process)."""
    out = []
    for u in units:
        pid = u.get("land_pid") if u.get("status") == "landing" else u.get("pid")
        if alive(pid):
            out.append(f"adopted {u['unit']} (pid {pid})")
    return out


# ---------------- stale close, cleanup ----------------

def close_stale(repo: Path, slug: str, number: int, evidence: str, why: str) -> list[str]:
    """The premise check found the issue resolved on `main`: comment, label `stale-premise` (made if missing), close; no unit."""
    repo = Path(repo)
    body = f"{STALE_MARK}\nResolved on main by {evidence}: {_one_line(why, 500)} (cplat dispatch premise check)."
    _ensure_label(repo, STALE_LABEL, "CFD3D7", "closed by the cplat dispatch premise check (spec 167)")
    gh(["issue", "edit", str(number), "--add-label", STALE_LABEL], cwd=repo)
    gh(["issue", "comment", str(number), "--body", body], cwd=repo)
    gh(["issue", "close", str(number)], cwd=repo)
    ds.events_add(slug, "stale", None, f"#{number}", evidence)
    ds.update(slug, lambda st: st.setdefault("stale_closed", []).append(number) if number not in st.get("stale_closed", []) else None)
    return [f"closed #{number} as stale: {evidence}"]


def cleanup(repo: Path, slug: str, read_at: str) -> list[str]:
    """Remove the worktree (and the local branch) of each done unit that ended before the snapshot read at `read_at`: from then on the
    snapshot shows the merge. Its tokens are booked first."""
    repo = Path(repo)
    gone = [u for u in ds.all_units(slug) if u.get("status") == "done" and str(u.get("ended_at") or "9") <= read_at]
    if not gone:
        return []
    _book(slug)
    for u in gone:
        git(["worktree", "remove", "--force", str(u["worktree"])], cwd=repo, check=False)
        git(["branch", "-D", u["branch"]], cwd=repo, check=False)
    return []
