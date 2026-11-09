"""One gitops PR per environment for a system ship (spec 144, ADR-083).

In joint mode (a gitops-app whose pin-dev.yml knows the marker) the gitops entry's `compose/<spec>` branch stays open; each
component ship pushes a marker `ship/<spec>/<component>-<sha7>` when its PR merged (pin-dev then skips that build) and ends its
deploy once main's CI built the image; the system ship pins each build on `compose/<spec>` (`pin`) and `land` merges that one
PR, waits for Argo CD once, runs every dev smoke and promotes staging in one PR. A gitops-app rendered before keeps one PR per
component (`supported` is false). `ship`, `appship`, `appship_sched` and `appship_merge` are imported lazily (no cycle).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import re
from collections.abc import Iterator
from pathlib import Path

import appship_state as state
import cluster
import core
import envwait
import model
import registry
import runs
import smoke
import spec as specmod
import staging
import waits
from core import PlatformError, run

MARKER_TEXT = "refs/heads/ship/"
WORKFLOW = ".github/workflows/pin-dev.yml"
LEGACY_LINE = ("one dev PR per component: this gitops-app's pin-dev.yml predates spec 144; run /platform:update to get one "
               "dev PR per system spec")
LOCK = "cplat-app-ship.compose.lock"
SHA40 = re.compile(r"[0-9a-f]{40}")


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd=repo, check=check).stdout.strip()


def say(line: str) -> None:
    import ship
    ship.say(line)


# ---------------- mode and markers ----------------

def supported(gitops: Path) -> bool:
    """Whether the gitops-app's pin-dev.yml on main skips a build that has a marker (decision 1)."""
    run(["git", "fetch", "-q", "origin", "main"], cwd=gitops, check=False)
    out = run(["git", "show", f"origin/main:{WORKFLOW}"], cwd=gitops, check=False)
    return out.returncode == 0 and MARKER_TEXT in out.stdout


def branch(spec_id: str) -> str:
    return f"compose/{spec_id}"


def marker(spec_id: str, component: str, sha: str) -> str:
    return f"ship/{spec_id}/{component}-{sha[:7]}"


def markers(gitops: Path, spec_id: str) -> list[str]:
    out = run(["git", "ls-remote", "--heads", "origin"], cwd=gitops, check=False).stdout
    want = f"refs/heads/ship/{spec_id}/"
    return [ln.split()[-1].removeprefix("refs/heads/") for ln in out.splitlines() if ln.split() and ln.split()[-1].startswith(want)]


def push_marker(gitops: Path, spec_id: str, component: str, sha: str) -> str:
    """Push the marker at the head of the gitops-app's main. Never raises: a failure is a line (decision 2)."""
    ref = marker(spec_id, component, sha)
    try:
        run(["git", "fetch", "-q", "origin", "main"], cwd=gitops, check=False)
        head = git(gitops, "rev-parse", "origin/main")
        res = run(["git", "push", "-q", "origin", f"{head}:refs/heads/{ref}"], cwd=gitops, check=False)
        if res.returncode == 0:
            return f"marker {ref} pushed to the gitops-app: its pin-dev skips this build (spec 144)"
        why = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
    except PlatformError as e:
        why = [str(e)]
    return f"marker {ref} not pushed ({why[0]}): the system ship closes a pin-dev PR of this build when it pins it"


def delete_markers(gitops: Path, spec_id: str) -> list[str]:
    gone = []
    for ref in markers(gitops, spec_id):
        if run(["git", "push", "-q", "origin", "--delete", ref], cwd=gitops, check=False).returncode == 0:
            gone.append(ref)
    return [f"markers deleted: {', '.join(gone)}"] if gone else []


# ---------------- the component ship inside a joint run ----------------

def component_deploy(repo: Path, st: dict, svc: str, timeout: float, interval: float) -> tuple[bool, list[str]]:
    """Decision 5: wait for main's CI on the merge commit (it publishes the image), keep the marker, end done."""
    import ship
    spec_id = st["product"]["spec"]
    gitops = Path(st["product"]["dir"])
    sha = st.get("merge_sha") or ""
    if not SHA40.fullmatch(sha):
        raise PlatformError("the run has no merge commit", hint="land the PR first: cplat component ship land")
    short = sha[:7]
    lines: list[str] = []
    begin = ship.now()
    while True:
        ci, ci_runs = ship.main_ci(repo, sha)
        if ci == "red":
            runs.ci_round(st.get("run_id"))
            return False, lines + [f"the service's CI on main is red for {short}; nothing was pinned"] + ship.run_logs(repo, ci_runs)
        if ci == "green":
            runs.ci_round(st.get("run_id"))
            break
        if ship.now() - begin > timeout:
            raise PlatformError(f"the service's CI on main for {short} did not finish within {int(timeout)}s",
                                hint="check the service's CI on main (docker-publish), then run deploy again")
        ship.sleep(interval)
    lines.append(f"the service's CI on main passed for {short}: image sha-{sha} is published")
    ref = marker(spec_id, svc, sha)
    if ref not in markers(gitops, spec_id):
        lines.append(push_marker(gitops, spec_id, svc, sha))
    ok, more = ship.merge_gitops(repo, st, "after-release", timeout, interval, ship.QUEUE_TIMEOUT)
    lines += more
    if not ok:
        return False, lines
    st["joint"] = {"tag": f"sha-{sha}", "marker": ref}
    st["smoke"] = {"outcome": "deferred", "row": "with the system ship",
                   "reason": "the system ship smokes dev once its dev PR merged (spec 144)"}
    st["staging"] = {"state": "skipped", "reason": "with the system ship", "row": "Promotion (staging): with the system ship"}
    lines += [f"dev: pinned in the system ship's dev PR ({branch(spec_id)}): {svc} sha-{sha}",
              "Smoke (dev): with the system ship", "Promotion (staging): with the system ship"]
    return ship._done(repo, st, lines)


# ---------------- pinning on compose/<spec> ----------------

@contextlib.contextmanager
def _locked(gitops: Path) -> Iterator[None]:
    with open(state.git_dir(gitops) / LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def component_of(gitops: Path, repo_id: str) -> str:
    """The component name system.yaml gives the repo (its `repo:` is <org>/<repo id>), else the repo id."""
    for f in sorted((gitops / "applications").glob("*/system.yaml")):
        try:
            m = model.load_dir(f.parent)
        except Exception:  # noqa: BLE001
            continue
        c = next((c for c in m.components if str(c.repo or "").endswith("/" + repo_id)), None) or m.component(repo_id)
        if c is not None:
            return c.name
    return repo_id


def _devbox(wt: Path, *args: str) -> None:
    res = run(["devbox", "run", "--", "uv", "run", *args], cwd=wt, check=False)
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["no output"]
        raise PlatformError(f"{' '.join(args)} failed in {wt}: {tail[0]}", hint="fix the gitops-app checkout, then run the command again")


def _reset_after_merge(gitops: Path, st: dict, wt: Path) -> None:
    """A pin after the dev PR merged (a component shipped again after an escalation): a new compose branch and PR."""
    if wt.is_dir():
        run(["git", "worktree", "remove", "--force", str(wt)], cwd=gitops, check=False)
    run(["git", "branch", "-D", branch(st["spec"])], cwd=gitops, check=False)

    def change(s: dict) -> None:
        for k in ("joint_pr", "dev_merged", "dev_landed", "staging_done", "staging_pr", "staging_merged"):
            s.pop(k, None)
    state.update(gitops, change)
    st.update(state.require_state(gitops))


def pin(gitops: Path, st: dict, repo_id: str, tag: str) -> tuple[str, list[str]]:
    """Decision 6: pin `tag` of the repo's component in dev on compose/<spec>; returns (component, lines)."""
    import appship
    import appship_sched as sched
    import ship
    spec_id = st["spec"]
    lines: list[str] = []
    with _locked(gitops):
        wt = sched.entry_path(gitops, spec_id)
        landed = st.get("dev_merged") and {k: st.get(k) for k in ("joint_pr", "dev_merged")}
        if landed:
            _reset_after_merge(gitops, st, wt)
        wt = sched._start_entry(gitops, spec_id)
        run(["git", "fetch", "-q", "origin"], cwd=wt, check=False)
        if run(["git", "rev-parse", "--verify", "-q", f"origin/{branch(spec_id)}"], cwd=wt, check=False).returncode == 0:
            run(["git", "merge", "-q", "--ff-only", f"origin/{branch(spec_id)}"], cwd=wt, check=False)
        comp = component_of(wt, repo_id)
        _devbox(wt, "scripts/pin.py", "dev", comp, tag)
        _devbox(wt, "scripts/render.py", "--check")
        if run(["git", "status", "--porcelain"], cwd=wt).stdout.strip():
            git(wt, "add", "-A")
            git(wt, *core.git_identity(wt), "commit", "-q", "-s", "-m", f"chore(dev): pin {comp} to {tag} ({spec_id})")
            lines.append(f"{comp}: dev pinned to {tag} on {branch(spec_id)}")
        else:
            lines.append(f"{comp}: {branch(spec_id)} already pins {tag}")
        if landed and int(git(wt, "rev-list", "--count", "origin/main..HEAD")) == 0:
            # #521: the new build has the image dev already runs (a test-only fix): no empty dev PR; `land` reruns
            # the dev smoke on the revision that already landed
            run(["git", "worktree", "remove", "--force", str(wt)], cwd=gitops, check=False)
            run(["git", "branch", "-D", branch(spec_id)], cwd=gitops, check=False)
            state.update(gitops, lambda s: s.update(landed))
            st.update(state.require_state(gitops))
            return comp, [f"{comp}: dev already runs {tag} ({landed['joint_pr']}): no new dev PR; land reruns the dev smoke"]
        git(wt, "push", "-q", "-u", "origin", branch(spec_id))
        pr = state.require_state(gitops).get("joint_pr")
        if not pr:
            pr = appship.open_pr(wt, branch(spec_id), f"chore(dev): {spec_id} — the builds of the system spec",
                                 f"## Summary\n\nThe dev pins of the builds of the system spec {spec_id}, landed in one PR by "
                                 f"`/system:ship` (spec 144) after the last component merged.\n")
            state.update(gitops, lambda s: s.__setitem__("joint_pr", pr))
            lines.append(f"dev PR opened: {pr}")
        stray = f"pin/dev-{comp}-{tag.removeprefix('sha-')[:7]}"
        for p in json.loads(ship.gh(["pr", "list", "--head", stray, "--state", "open", "--json", "number,url"], cwd=gitops,
                                    check=False) or "[]"):
            ship.gh(["pr", "close", p["url"], "--delete-branch", "--comment",
                     f"Pinned in the system ship's dev PR {pr} (spec 144)."], cwd=gitops, check=False)
            lines.append(f"closed {p['url']}: this build is pinned in {pr}")
    return comp, lines


# ---------------- refresh before land (spec 166) ----------------

# what render.py writes (and cplat's restore state): a conflict there is resolved by taking main's file and rendering again
GENERATED = re.compile(r"^(?:applications/[^/]+/(?:applicationset\.yaml|overlays/|addons/|policies/|autonomy\.json)|operators/|bootstrap/)")


def _newer_pin(e: dict, ours: str, theirs: str | None, org: str, rid: str) -> bool:
    """Whether main's dev pin `theirs` is a later build of the component than `ours` (its main moved on, #597)."""
    a, b = ours.removeprefix("sha-"), (theirs or "").removeprefix("sha-")
    if not (SHA40.fullmatch(a) and SHA40.fullmatch(b)) or a == b:
        return False
    clone = Path(e.get("clone") or ".")
    return staging.newer(e.get("slug") or f"{org}/{rid}", a, b, clone) == "ahead"


def refresh(gitops: Path, st: dict) -> tuple[str | None, list[str]]:
    """Spec 166 (#597): bring compose/<spec> up to the current main before the dev PR lands. Main is merged in; a conflict in
    a rendered file takes main's file, then every build of the run is pinned again (or main's later build of it kept) and
    the system rendered again. Returns (escalation reason or None, lines); a conflict in any other file aborts the merge."""
    import appship_sched as sched
    spec_id = st["spec"]
    org = _org(gitops)
    lines: list[str] = []
    with _locked(gitops):
        wt = sched._start_entry(gitops, spec_id)
        run(["git", "fetch", "-q", "origin"], cwd=wt, check=False)
        if run(["git", "rev-parse", "--verify", "-q", f"origin/{branch(spec_id)}"], cwd=wt, check=False).returncode == 0:
            run(["git", "merge", "-q", "--ff-only", f"origin/{branch(spec_id)}"], cwd=wt, check=False)
        if run(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=wt, check=False).returncode == 0:
            return None, []
        merged = run(["git", *core.git_identity(wt), "merge", "-q", "--no-edit", "--no-ff", "origin/main"], cwd=wt, check=False)
        if merged.returncode != 0:
            conflicted = git(wt, "diff", "--name-only", "--diff-filter=U").split()
            source = [f for f in conflicted if not GENERATED.match(f)]
            if source or not conflicted:
                run(["git", "merge", "--abort"], cwd=wt, check=False)
                where = f"conflicts with main in {', '.join(source)}" if source else "could not merge main"
                return (f"the dev PR {st.get('joint_pr')} {where}: merge main into {branch(spec_id)} by hand, then run "
                        f"`cplat system ship land` again"), lines
            for f in conflicted:
                run(["git", "checkout", "--theirs", "--", f], cwd=wt, check=False)
                if not (wt / f).exists():
                    run(["git", "rm", "-q", "--", f], cwd=wt, check=False)
                else:
                    git(wt, "add", "--", f)
            lines.append(f"{branch(spec_id)}: took main's rendered files in {len(conflicted)} conflict(s), rendering again")
        app = _app_dir(wt)
        kept: dict[str, str] = {}
        for rid, e in st["repos"].items():
            ours, comp = e.get("pinned"), e.get("component")
            if not ours or not comp:
                continue
            now = model.read_pin(app, "dev", comp)
            if now == ours:
                continue
            if _newer_pin(e, ours, now, org, rid):
                kept[rid] = now
                lines.append(f"{comp}: main pins a later build ({now}) than this run's {ours}: dev keeps {now}")
            else:
                _devbox(wt, "scripts/pin.py", "dev", comp, ours)
                lines.append(f"{comp}: pinned {ours} again on {branch(spec_id)}")
        _devbox(wt, "scripts/render.py")
        _devbox(wt, "scripts/render.py", "--check")
        git(wt, "add", "-A")
        if run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=wt, check=False).returncode == 0:
            git(wt, *core.git_identity(wt), "commit", "-q", "-s", "--no-edit")
        elif run(["git", "diff", "--cached", "--quiet"], cwd=wt, check=False).returncode != 0:
            git(wt, *core.git_identity(wt), "commit", "-q", "-s", "-m", f"chore(dev): {spec_id} pins after main")
        git(wt, "push", "-q", "origin", f"HEAD:{branch(spec_id)}")
        if kept:
            def keep(s: dict) -> None:
                for rid, tag in kept.items():
                    s["repos"][rid]["pinned"] = tag
            st.update(state.update(gitops, keep))
        lines.insert(0, f"{branch(spec_id)}: merged main ({git(wt, 'rev-parse', '--short', 'origin/main')}) before landing")
    return None, lines


# ---------------- land ----------------

def needs_land(st: dict) -> bool:
    return bool(st.get("joint") and st.get("joint_pr") and not (st.get("dev_landed") and st.get("staging_done")))


def _app_dir(gitops: Path) -> Path:
    import gitops as gitopsmod
    return gitopsmod.find_app(gitops, None)


def _argo(gitops: Path, st: dict, env: str, rev: str, comps: list[str], wait_timeout: float, interval: float,
          resources: bool) -> tuple[int, list[str]]:
    system, targets, _every = envwait.env_targets(gitops, None, rev, env, [] if resources else comps)
    targets = [t for t in targets if not t.component or t.name in comps]
    ctx = st.get("context")
    if not ctx:
        return waits.REACHED, [f"Argo CD not checked in {env} (no kube context)"]
    items = envwait.list_apps(ctx)
    return envwait.watch(gitops, targets, rev, ctx, items, f"in {env}", "cplat system ship land", False, wait_timeout, interval, system)


def _smoke(gitops: Path, st: dict, rid: str, e: dict, m: model.Model, env: str) -> smoke.SmokeResult:
    clone = Path(e.get("clone") or "")
    comp, tag = e["component"], e["pinned"]
    try:
        sp = specmod.find(clone, e["spec"]) if e.get("spec") else None
    except PlatformError:
        sp = None
    acs = sp.smoke_acs() if sp else []
    url, why = m.url(comp, env)
    if not url:
        return smoke.not_run(env, f"{comp} has no {env} URL ({why})", acs)
    inst = m.instance(comp, env)
    ctx = st.get("context")
    digest = cluster.running_digest(ctx, inst.namespace if inst else f"{m.system}-{env}", comp) if ctx else None
    prior = (e.get("smoke") or {}) if env == "dev" else (e.get("staging_smoke") or {})
    if digest and prior.get("outcome") in ("passed", "passed-on-retry") and prior.get("digest") == digest and prior.get("row"):
        res = smoke.SmokeResult(env=env, outcome=prior["outcome"], base_url=url, digest=digest,
                                passed=int(prior.get("passed") or 0), failed=0, skipped=int(prior.get("skipped") or 0))
        return res
    res = smoke.run_smoke(clone, url, env=env, spec=sp, probe=smoke.liveness_probe(clone))
    res.digest = digest
    smoke.record(clone, res, tag, sp.id if sp else None)          # as `cplat instance verify <env>` records it (spec 142)
    return res


def _issue(e: dict, rid: str, res: smoke.SmokeResult, org: str) -> str | None:
    out = smoke.file_issue(res, service_slug=f"{org}/{rid}", spec_id=e.get("spec"), image=e.get("pinned"), run_id=e.get("run_id"),
                           shape=e.get("shape") or "none")
    if out.url:
        return out.url
    m = re.search(r"not filed: ([^;]*)", " ".join(out.lines))
    return f"not filed: {m.group(1).strip()}" if m else None


def _org(gitops: Path) -> str:
    return (state.slug(gitops) or "/").split("/")[0]


def _section(res: smoke.SmokeResult, row: str) -> dict:
    return {"outcome": res.outcome, "digest": res.digest, "row": row, "passed": res.passed, "skipped": res.skipped}


def _land_pr(gitops: Path, pr: str, who: str, what: str, timeout: float, interval: float) -> tuple[bool, list[str]]:
    import appship
    import appship_merge
    ok, lines = appship_merge.land(gitops, pr, who, timeout, interval)
    if not ok:
        reason = appship.red_reason(what, pr, lines)
        state.escalate(gitops, reason, "code")
        return False, [reason, *lines]
    appship._land_main(gitops)
    return True, lines


def land(gitops: Path, timeout: float, wait_timeout: float, interval: float = 20, wait_interval: float = 10) -> tuple[int, list[str]]:
    """Decision 8: `cplat system ship land`. Exit 0 landed, 1 escalated, 2 Argo CD timeout (run it again)."""
    import appship
    import appship_sched as sched
    st = state.require_state(gitops)
    spec_id = st["spec"]
    if not st.get("joint"):
        raise PlatformError("this run pins dev in one PR per component (its gitops-app predates spec 144): nothing to land",
                            hint="cplat system ship next --json")
    if st.get("escalated"):
        raise PlatformError(f"the run is escalated: {st['escalated']}", hint=f"resume it with /system:ship {spec_id}")
    plan = state.plan_repos(gitops, spec_id)
    open_ = [r["id"] for r in plan if (st["repos"].get(r["id"]) or {}).get("state") not in state.PASSED]
    if open_:
        raise PlatformError("repos not past their gate: " + ", ".join(open_),
                            hint="the dev PR lands after the last component of the plan merged: cplat system ship next --json")
    pr = st.get("joint_pr")
    if not pr:
        raise PlatformError("the run has no dev PR (nothing was pinned)", hint="cplat system ship next --json")
    if st.get("dev_landed") and st.get("staging_done"):
        return waits.REACHED, [f"dev PR {pr} landed already" + (f", staging PR {st['staging_pr']}" if st.get("staging_pr") else "")]
    lines: list[str] = []
    if not st.get("dev_merged"):
        reason, more = refresh(gitops, st)
        lines += more
        if reason:
            state.escalate(gitops, reason, "code")
            return waits.RED, [*lines, reason]
        ok, more = _land_pr(gitops, pr, "dev", "dev PR", timeout, interval)
        if not ok:
            return waits.RED, more
        lines += [f"dev PR merged: {pr}", *more]
        ops, steps = appship.install_operators(gitops, st.get("context"))
        lines += ops
        sha = git(gitops, "rev-parse", "HEAD")
        lines += delete_markers(gitops, spec_id)
        wt = sched.entry_path(gitops, spec_id)
        if wt.is_dir():
            run(["git", "worktree", "remove", "--force", str(wt)], cwd=gitops, check=False)

        def merged(s: dict) -> None:
            s["dev_merged"] = sha
            entry = next((i for i, r in s["repos"].items() if r.get("shape") == "gitops-app"), None)
            if steps and entry:
                s["repos"][entry]["human_steps"] = [*(s["repos"][entry].get("human_steps") or []), *steps]
        st = state.update(gitops, merged)
    else:
        appship._land_main(gitops)
    pinned = [(r["id"], st["repos"][r["id"]]) for r in plan if (st["repos"].get(r["id"]) or {}).get("pinned")]
    comps = [e["component"] for _, e in pinned]
    if not st.get("dev_landed"):
        code, more = _argo(gitops, st, "dev", st["dev_merged"], comps, wait_timeout, wait_interval, resources=True)
        lines += more
        if code == waits.RED:
            reason = f"dev did not run the system spec after {pr}: {more[0].removeprefix('RED: ')}"
            state.escalate(gitops, reason, "environment")
            return waits.RED, [*lines, reason]
        if code == waits.TIMEOUT:
            return waits.TIMEOUT, [*lines, "run `cplat system ship land` again: it resumes after the merge"]
        code, more = _dev_smokes(gitops, st, plan, pinned)
        lines += more
        if code != waits.REACHED:
            return code, lines
        st = state.update(gitops, lambda s: s.__setitem__("dev_landed", True))
    code, more = _staging(gitops, st, plan, timeout, wait_timeout, interval, wait_interval)
    return code, [*lines, *more]


def _dev_smokes(gitops: Path, st: dict, plan: list[dict], pinned: list[tuple[str, dict]]) -> tuple[int, list[str]]:
    """Decision 8: every pinned component's dev smoke in plan order; a red one escalates its repo, then the run."""
    import appship_sched as sched
    m = model.load_dir(_app_dir(gitops))
    org = _org(gitops)
    lines: list[str] = []
    results: dict[str, dict] = {}
    for rid, e in pinned:
        gate = sched.gate_class(gitops, next(r for r in plan if r["id"] == rid))
        upd: dict = {"deployed": e["pinned"], "argo": "Synced/Healthy", "gate": gate}
        if gate == "exposed":
            res = _smoke(gitops, st, rid, {**e, **upd}, m, "dev")
            lines += res.lines()
            if res.ok:
                row = res.row()
                upd.update(state="passed", smoke_row=row, smoke=_section(res, row))
            elif res.outcome == "not-run":
                row = res.row()
                upd.update(state="escalated", smoke_row=row, cause="environment",
                           reason=f"smoke not run in dev for {rid}: {res.reason}; an exposed service needs passing smoke")
            else:
                row = res.row(_issue(e, rid, res, org))
                upd.update(state="escalated", smoke_row=row, smoke=_section(res, row),
                           cause="environment" if res.failure_class == "environment" else "code",
                           reason=f"smoke red in dev: {len(res.failing)} failing ({e.get('spec') or rid})")
            lines.append(f"Smoke (dev) {rid}: {row}")
        else:
            upd["state"] = "passed"
            lines.append(f"Smoke (dev) {rid}: not run: {rid} has no dev URL (not exposed in dev); Argo CD Synced/Healthy")
        results[rid] = upd

    def change(s: dict) -> None:
        for rid, upd in results.items():
            s["repos"][rid].update(upd)
    state.update(gitops, change)
    red = [rid for rid, upd in results.items() if upd.get("state") == "escalated"]
    if red:
        st = state.escalate(gitops, "smoke red in dev for " + ", ".join(red))
        return waits.RED, [*lines, f"product ship {st['spec']}: escalated ({st['escalated']}); dev keeps running the new builds. "
                                   f"Resume with /system:ship {st['spec']}"]
    return waits.REACHED, lines


# ---------------- staging in one PR (AC-144.7) ----------------

def _candidates(gitops: Path, st: dict, plan: list[dict]) -> tuple[list[tuple[str, str, str, str | None]], dict[str, str]]:
    m = model.load_dir(_app_dir(gitops))
    org = _org(gitops)
    cands, skipped = [], {}
    for r in plan:
        e = st["repos"].get(r["id"]) or {}
        if not e.get("pinned") or e.get("gate") not in ("exposed", "internal"):
            continue
        rid, tag = r["id"], e["pinned"]
        comp = m.component(e["component"])
        if comp is None:
            skipped[rid] = f"{e['component']} is not in system.yaml"
            continue
        name = comp.name
        if m.staging_promotion(comp) != "after-dev-smoke":
            skipped[rid] = f"automatic promotion to staging is off for {name}"
            continue
        inst = m.instance(name, "staging")
        if inst is None:
            skipped[rid] = f"{name} is not in staging yet: the first promotion is manual: /instance:promote {name} --to staging"
            continue
        previous = inst.tag
        if previous == tag:
            skipped[rid] = f"staging already runs {tag}: nothing pinned"
            continue
        me = comp.repo or f"{org}/{rid}"
        clone = Path(e.get("clone") or gitops)
        build = tag.removeprefix("sha-")
        have = staging.resolve(me, previous, clone)
        if have and SHA40.fullmatch(build) and have != build and staging.newer(me, build, have, clone) == "ahead":
            skipped[rid] = f"staging already runs a newer build of {name} ({have[:7]}): nothing pinned"
            continue
        dev_digest = (e.get("smoke") or {}).get("digest")
        if not dev_digest:
            skipped[rid] = "the dev smoke recorded no image digest"
            continue
        try:
            current = registry.digest(registry.image_name({"image": comp.image} if comp.image else None, me), tag)
        except PlatformError as ex:
            skipped[rid] = f"digest of {tag} not verified: {ex}"
            continue
        if current != dev_digest:
            skipped[rid] = f"digest changed since smoke: {dev_digest} -> {current}"
            continue
        cands.append((rid, name, tag, previous))
    return cands, skipped


def _staging_pr(gitops: Path, st: dict, cands: list[tuple[str, str, str, str | None]]) -> str:
    import appship
    spec_id = st["spec"]
    wt = state.git_dir(gitops) / "cplat-app-ship" / f"{spec_id}-staging"
    br = f"promote/staging-{spec_id}"
    run(["git", "fetch", "-q", "origin"], cwd=gitops, check=False)
    if wt.is_dir():
        run(["git", "worktree", "remove", "--force", str(wt)], cwd=gitops, check=False)
    wt.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "worktree", "add", "-q", "-B", br, str(wt), "origin/main"], cwd=gitops)
    for _rid, name, tag, _prev in cands:
        _devbox(wt, "scripts/pin.py", "staging", name, tag)
    _devbox(wt, "scripts/render.py", "--check")
    git(wt, "add", "-A")
    git(wt, *core.git_identity(wt), "commit", "-q", "-s", "-m",
        f"chore(staging): promote {spec_id}: " + ", ".join(f"{n} {t}" for _r, n, t, _p in cands))
    git(wt, "push", "-q", "-u", "origin", br)
    rows = "\n".join(f"- `{n}`: `{p}` -> `{t}`" for _r, n, t, p in cands)
    pr = appship.open_pr(wt, br, f"chore(staging): promote {spec_id} (automatic, spec 093)",
                         f"## Summary\n\nEvery dev smoke of the system spec {spec_id} passed, so staging follows it in one PR "
                         f"(`/system:ship`, spec 144):\n\n{rows}\n\nRevert this PR to put staging back.\n")
    return pr


def _staging(gitops: Path, st: dict, plan: list[dict], timeout: float, wait_timeout: float, interval: float,
             wait_interval: float) -> tuple[int, list[str]]:
    if st.get("staging_done"):
        return waits.REACHED, []
    lines: list[str] = []
    if not st.get("staging_pr"):
        cands, skipped = _candidates(gitops, st, plan)

        def skip(s: dict) -> None:
            for rid, why in skipped.items():
                s["repos"][rid]["staging_row"] = f"not promoted: {why}"
            if not cands:
                s["staging_done"] = True
        st = state.update(gitops, skip)
        lines += [f"Promotion (staging) {rid}: not promoted: {why}" for rid, why in skipped.items()]
        if not cands:
            return waits.REACHED, lines
        pr = _staging_pr(gitops, st, cands)

        def opened(s: dict) -> None:
            s["staging_pr"] = pr
            s["staging_promoted"] = [[rid, name, tag, prev] for rid, name, tag, prev in cands]
        st = state.update(gitops, opened)
        lines.append(f"staging PR opened: {pr}")
    pr = st["staging_pr"]
    cands = [tuple(c) for c in st.get("staging_promoted") or []]
    if not st.get("staging_merged"):
        ok, more = _land_pr(gitops, pr, "staging", "staging PR", timeout, interval)
        if not ok:
            return waits.RED, [*lines, *more]
        lines += [f"staging PR merged: {pr}", *more]
        wt = state.git_dir(gitops) / "cplat-app-ship" / f"{st['spec']}-staging"
        if wt.is_dir():
            run(["git", "worktree", "remove", "--force", str(wt)], cwd=gitops, check=False)
        sha = git(gitops, "rev-parse", "HEAD")
        st = state.update(gitops, lambda s: s.__setitem__("staging_merged", sha))
    else:
        import appship
        appship._land_main(gitops)
    code, more = _argo(gitops, st, "staging", st["staging_merged"], [c[1] for c in cands], wait_timeout, wait_interval,
                       resources=False)
    lines += more
    if code == waits.RED:
        reason = f"staging did not run the system spec after {pr}: {more[0].removeprefix('RED: ')}"
        state.escalate(gitops, reason, "environment")
        return waits.RED, [*lines, reason]
    if code == waits.TIMEOUT:
        return waits.TIMEOUT, [*lines, "run `cplat system ship land` again: it resumes after the merge"]
    m = model.load_dir(_app_dir(gitops))
    org = _org(gitops)
    results: dict[str, dict] = {}
    for rid, _name, tag, prev in cands:
        e = st["repos"][rid]
        res = _smoke(gitops, st, rid, e, m, "staging")
        lines += res.lines()
        promo = f"{tag} ({pr}), was {prev}"
        if res.ok or res.outcome == "not-run":
            row = res.row()
            results[rid] = {"staging_row": promo, "staging_smoke": _section(res, row)}
        else:
            row = res.row(_issue(e, rid, res, org))
            results[rid] = {"staging_row": promo, "staging_smoke": _section(res, row), "state": "escalated", "cause": "code",
                            "reason": f"smoke red in staging: {len(res.failing)} failing ({e.get('spec') or rid}); staging keeps "
                                      f"running {tag} (no automatic rollback: revert {pr} to go back)"}
        lines += [f"Promotion (staging) {rid}: {promo}", f"Smoke (staging) {rid}: {row}"]

    def change(s: dict) -> None:
        for rid, upd in results.items():
            s["repos"][rid].update(upd)
        s["staging_done"] = True
    state.update(gitops, change)
    red = [rid for rid, upd in results.items() if upd.get("state") == "escalated"]
    if red:
        st = state.escalate(gitops, "smoke red in staging for " + ", ".join(red))
        return waits.RED, [*lines, f"product ship {st['spec']}: escalated ({st['escalated']}). Resume with /system:ship {st['spec']}"]
    return waits.REACHED, lines
