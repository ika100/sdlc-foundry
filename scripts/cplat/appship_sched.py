"""`cplat system ship` scheduling (spec 097): which repos start, gate classes and gate evaluation, repo start/result/escalate."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

import appship_state as state
import budget
import core
import model
import runs
import ship
import spec as specmod
from core import PlatformError, run

PASSED = state.PASSED


def entry_path(gitops_dir: Path, spec_id: str) -> Path:
    return state.git_dir(gitops_dir) / "cplat-app-ship" / f"{spec_id}-entry"


def clone_path(gitops_dir: Path, repo_id: str) -> Path:
    return gitops_dir.parent / repo_id


def _state_of(st: dict, repo_id: str) -> str:
    return (st.get("repos") or {}).get(repo_id, {}).get("state", "ready")


def next_action(gitops_dir: Path, st: dict) -> dict:
    """The `next --json` object: what starts now, what runs, what waits, what escalated, and the action."""
    plan = state.plan_repos(gitops_dir, st["spec"])
    stopped = bool(st.get("escalated")) or any(_state_of(st, r["id"]) == "escalated" for r in plan)
    running = [r["id"] for r in plan if _state_of(st, r["id"]) == "running"]
    escalated = [r["id"] for r in plan if _state_of(st, r["id"]) == "escalated"]
    held = [i for i in escalated if st["repos"][i].get("held")]
    room = int(st.get("max") or state.DEFAULT_MAX) - len(running)
    start: list[dict] = []
    blocked: list[dict] = []
    for r in plan:
        if _state_of(st, r["id"]) != "ready":
            continue
        waits = [d for d in r.get("depends_on") or [] if _state_of(st, d) not in PASSED]
        if waits:
            blocked.append({"id": r["id"], "waits_for": waits})
        elif not stopped and room > 0:
            entry = r.get("shape") == "gitops-app"
            start.append({"id": r["id"], "shape": r.get("shape"), "entry": entry,
                          "clone": str(entry_path(gitops_dir, st["spec"]) if entry else clone_path(gitops_dir, r["id"]))})
            room -= 1
    answer = None
    if st["phase"] != "done" and not st.get("escalated"):
        pick = next((i for i in escalated if i not in held), None)
        if pick is not None:
            answer = _answer_object(st["repos"][pick], pick)
    if st["phase"] == "done":
        action = "done"
    elif answer is not None:
        action = "answer"
    elif running:
        action = "wait"
    elif start:
        action = "start"
    elif plan and all(_state_of(st, r["id"]) in PASSED for r in plan) and not st.get("escalated"):
        import appship_joint
        # spec 144: the one dev PR first; spec 156: a run --until repos stops before it
        action = "land" if appship_joint.needs_land(st) and st.get("until") != "repos" else "complete"
    elif stopped:
        action = "escalate"
    else:
        action = "wait" if not plan else "escalate"
    out = {"phase": st["phase"], "start": start, "running": running, "blocked": blocked, "escalated": escalated,
           "held": held, "action": action}
    if answer is not None:
        out["answer"] = answer
    return out


def questions_of(reason: str, stored: list | None) -> list[dict]:
    """Spec 186: the questions of an escalation: the stored ones, else the one a reason ending in `(suggested: ...)` asks."""
    if isinstance(stored, list) and stored:
        return stored
    if re.search(r"\(suggested:[^)]*\)\s*$", reason or ""):
        q = specmod._question(reason)
        return [{"text": q["text"], "suggested": q["options"][0] if q["options"] else None}]
    return []


def _answer_object(entry: dict, repo_id: str) -> dict:
    reason = entry.get("reason") or ""
    return {"id": repo_id, "cause": entry.get("cause"), "reason": reason,
            "questions": questions_of(reason, entry.get("questions")),
            "resume": f"cplat system ship repo resume {repo_id} --answer '<text>'",
            "hold": f"cplat system ship repo hold {repo_id}"}


# ---------------- gate classes ----------------

def _show(gitops_dir: Path, path: str) -> dict:
    out = run(["git", "show", f"origin/main:{path}"], cwd=gitops_dir, check=False)
    try:
        data = yaml.safe_load(out.stdout) if out.returncode == 0 else None
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def gate_class(gitops_dir: Path, repo: dict) -> str:
    """entry | library | exposed | internal. Exposed means the model has a dev Instance that is exposed."""
    shape = repo.get("shape")
    if shape == "gitops-app":
        return "entry"
    entry = next((s for s in core.registry.load() if s["id"] == shape), None)
    if entry is not None and not entry["deployable"]:
        return "library"
    run(["git", "fetch", "-q", "origin"], cwd=gitops_dir, check=False)
    tree = run(["git", "ls-tree", "--name-only", "origin/main", "applications/"], cwd=gitops_dir, check=False).stdout.split()
    for app in tree:
        system = app.rstrip("/").rsplit("/", 1)[-1]
        doc = _show(gitops_dir, f"{app}/system.yaml")
        m = model.build(doc, system)
        found = next((c for c in m.components
                      if str(c.repo or "").endswith("/" + repo["id"]) or c.name == repo["id"]), None)
        if found is None:
            continue
        inst = m.instance(found.name, "dev")
        return "exposed" if inst is not None and inst.exposed else "internal"
    return "internal"


def _plan_entry(gitops_dir: Path, st: dict, repo_id: str) -> dict:
    found = next((r for r in state.plan_repos(gitops_dir, st["spec"]) if r["id"] == repo_id), None)
    if found is None:
        raise PlatformError(f"'{repo_id}' is not a repo of the plan of {st['spec']}",
                            hint="repos: " + ", ".join(r["id"] for r in state.plan_repos(gitops_dir, st["spec"])))
    return found


# ---------------- repo start / result / escalate ----------------

def _org(gitops_dir: Path) -> str:
    answers = gitops_dir / ".copier-answers.yml"
    try:
        org = (yaml.safe_load(answers.read_text()) or {}).get("github_org")
    except (OSError, yaml.YAMLError):
        org = None
    return str(org or (state.slug(gitops_dir) or "/").split("/")[0])


def _start_entry(gitops_dir: Path, spec_id: str) -> Path:
    wt = entry_path(gitops_dir, spec_id)
    if wt.is_dir():
        return wt
    run(["git", "fetch", "-q", "origin"], cwd=gitops_dir, check=False)
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"compose/{spec_id}"
    have = run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], cwd=gitops_dir, check=False).returncode == 0
    cmd = ["git", "worktree", "add", str(wt), branch] if have else ["git", "worktree", "add", str(wt), "-b", branch, "origin/main"]
    run(cmd, cwd=gitops_dir)
    return wt


def start_repo(gitops_dir: Path, repo_id: str) -> Path:
    st = state.require_state(gitops_dir)
    repo = _plan_entry(gitops_dir, st, repo_id)
    if limit := budget.check(st.get("run_id"), "repo ship start"):          # spec 102: a safe point
        reason = budget.stop(st.get("run_id"), limit, "repo ship start", st["phase"])
        state.escalate(gitops_dir, reason, "decision")
        raise PlatformError(reason, hint=f"no repo ship is started; resume with /system:ship {st['spec']} (--budget {limit}=N raises the limit)")
    if repo.get("shape") == "gitops-app":
        path = _start_entry(gitops_dir, st["spec"])
    else:
        path = clone_path(gitops_dir, repo_id).absolute()
        if not path.exists():
            ship.gh(["repo", "clone", f"{_org(gitops_dir)}/{repo_id}", str(path)], cwd=gitops_dir.parent)
        if run(["git", "status", "--porcelain"], cwd=path).stdout.strip():
            raise PlatformError(f"{path} has uncommitted changes; commit or stash them, then resume",
                                hint="commit or stash the work in that clone, then run the command again")
        import preflight                          # spec 131: the repo's permissions, before its ship starts
        if failure := preflight.check_repo(path, f"{_org(gitops_dir)}/{repo_id}"):
            escalate_repo(gitops_dir, repo_id, failure.reason(), "environment")
            raise PlatformError(failure.line())
    gate = gate_class(gitops_dir, repo)
    repo_spec = None if repo.get("shape") == "gitops-app" else repo_spec_of(gitops_dir, st, repo_id, path)

    def change(s: dict) -> None:
        e = s["repos"].setdefault(repo_id, {})
        e.update(state="running", clone=str(path), gate=gate, shape=repo.get("shape"), depends_on=list(repo.get("depends_on") or []))
        if repo_spec:
            e["spec"] = repo_spec
        e.pop("reason", None)
        e.pop("cause", None)
    state.update(gitops_dir, change)
    if repo_spec:
        launch(gitops_dir, repo_id)
    return path


# ---------------- spec 155: each component repo in its own session ----------------

def repo_spec_of(gitops_dir: Path, st: dict, repo_id: str, clone: Path) -> str:
    """AC-155.1: the repo spec of this system spec in the clone; written from the plan and approved when there is none."""
    want = f"{state.slug(gitops_dir)}:{st['spec']}"
    specs, _ = specmod.scan(clone)
    found = next((s for s in specs if s.meta.get("parent") == want and s.status not in ("superseded", "abandoned")), None)
    if found is not None:
        return found.id
    plan = state.plan_path(gitops_dir, st["spec"])
    if not specmod.slice_from_plan(plan, repo_id)["criteria"]:
        reason = f"the plan of {st['spec']} writes no criteria for {repo_id} (a plan from before spec 147): re-plan it with /system:plan"
        escalate_repo(gitops_dir, repo_id, reason, "decision")
        raise PlatformError(reason, hint=f"/system:plan {st['spec']}, then /system:ship {st['spec']}")
    shape = specmod.repo_shape(clone)
    sp = specmod.new_from_plan(clone, plan, repo_id, shape=shape)
    run(["git", "checkout", "-q", "-B", f"feature/{sp.id}"], cwd=clone)
    specmod.approve(specmod.find(clone, sp.id), shape)                     # spec 147 (AC-147.4): approved at once
    specmod.write_index(clone)
    run(["git", "add", "-A"], cwd=clone)
    run(["git", *core.git_identity(clone), "commit", "-q", "-s", "-m", f"docs(spec): {sp.id} from the system plan of {st['spec']}"],
        cwd=clone)
    return sp.id


def launch(gitops_dir: Path, repo_id: str, starts: int = 1, answer: str | None = None) -> dict:
    """AC-155.1: start the repo's headless `/component:ship` and keep its process in the state (cause environment on failure)."""
    import appship_proc
    st = state.require_state(gitops_dir)
    e = st["repos"][repo_id]
    try:
        extra = {"answer": answer} if answer is not None else {}
        proc = appship_proc.spawn(Path(e["clone"]), e["spec"], gitops_dir, st.get("run_id"), starts, **extra)
    except OSError as err:
        escalate_repo(gitops_dir, repo_id, f"the ship session of {repo_id} could not start: {err}", "environment")
        raise PlatformError(f"{repo_id}: the ship session could not start: {err}") from None

    def change(s: dict) -> None:
        s["repos"][repo_id]["proc"] = proc
    state.update(gitops_dir, change)
    return proc


def check_session(gitops_dir: Path, repo_id: str, sh: dict | None) -> str | None:
    """AC-155.5: a running repo whose session ended before its ship did is started once more; then it escalates.
    Returns the line to print, or None while the session runs or its ship has ended."""
    import appship_proc
    st = state.require_state(gitops_dir)
    e = (st.get("repos") or {}).get(repo_id) or {}
    if e.get("state") != "running" or not e.get("spec") or (sh and (sh.get("escalated") or sh.get("phase") == "done")):
        return None
    proc = e.get("proc") or {}
    if proc and appship_proc.alive(proc.get("pid")):
        return None
    starts = int(proc.get("starts") or 0)
    if starts < appship_proc.MAX_STARTS:
        new = launch(gitops_dir, repo_id, starts + 1)
        return (f"{repo_id}: ship session started again (pid {new['pid']}, log {new['log']})" if proc
                else f"{repo_id}: ship session started (pid {new['pid']}, log {new['log']})")
    reason = f"the ship session of {repo_id} ended {starts} times before its ship finished; see {proc.get('log')}"
    escalate_repo(gitops_dir, repo_id, reason, "environment")
    return f"{repo_id}: escalated ({reason})"


def _session_runs(entry: dict) -> bool:
    """Spec 155: the repo's own session still runs, so its ship and units state stay where it reads them (archiving them
    under it made its supervisor see no unit left and report the escalated run as shipped)."""
    import appship_proc
    return bool((entry.get("proc") or {}).get("pid")) and appship_proc.alive(entry["proc"]["pid"])


def escalate_repo(gitops_dir: Path, repo_id: str, reason: str, cause: str | None, questions: list[str] | None = None) -> dict:
    final = ship._coerce_cause(cause)[0]
    parsed = []
    for text in questions or []:
        q = specmod._question(text)
        parsed.append({"text": q["text"], "suggested": q["options"][0] if q["options"] else None})

    def change(s: dict) -> None:
        e = s["repos"].setdefault(repo_id, {})
        e.update(state="escalated", reason=reason, cause=final)
        e.pop("questions", None)
        if parsed:
            e["questions"] = parsed
    return state.update(gitops_dir, change)


def _escalated_repo(gitops_dir: Path, repo_id: str, what: str, check_run: bool = False) -> None:
    st = state.require_state(gitops_dir)
    if not any(r["id"] == repo_id for r in state.plan_repos(gitops_dir, st["spec"])):
        raise PlatformError(f"'{repo_id}' is not a repo of the plan of {st['spec']}")
    if check_run and st.get("escalated"):
        raise PlatformError(f"the run of {st['spec']} is escalated: resume it with /system:ship {st['spec']}")
    cur = _state_of(st, repo_id)
    if cur != "escalated":
        raise PlatformError(f"{repo_id} is {cur}, not escalated: nothing to {what}")


def hold_repo(gitops_dir: Path, repo_id: str) -> str:
    """Spec 186 (AC-186.3): keep the escalated repo for the user; the run escalates once nothing runs."""
    _escalated_repo(gitops_dir, repo_id, "hold")

    def change(s: dict) -> None:
        s["repos"][repo_id]["held"] = True
    st = state.update(gitops_dir, change)
    return f"{repo_id}: held for you ({st['repos'][repo_id].get('reason')}); the run escalates once nothing runs"


def resume_repo(gitops_dir: Path, repo_id: str, answer: str) -> dict:
    """Spec 186 (AC-186.2): start the escalated repo's ship again in its own session with the user's answer."""
    _escalated_repo(gitops_dir, repo_id, "resume", check_run=True)

    def change(s: dict) -> None:
        e = s["repos"][repo_id]
        e.setdefault("answers", []).append({"at": dt.datetime.now().isoformat(timespec="seconds"), "text": answer,
                                            "cause": e.get("cause"), "reason": e.get("reason"), "questions": e.get("questions")})
        e["state"] = "running"
        for k in ("reason", "cause", "questions", "held"):
            e.pop(k, None)
    state.update(gitops_dir, change)
    return launch(gitops_dir, repo_id, 1, answer=answer)


def result(gitops_dir: Path, repo_id: str, context: str | None) -> tuple[bool, list[str]]:
    """Read the repo's finished ship from its clone, evaluate its gate, archive the clone's ship state."""
    st = state.require_state(gitops_dir)
    repo = _plan_entry(gitops_dir, st, repo_id)
    cur = st["repos"].get(repo_id, {})
    if cur.get("state") in PASSED:
        return True, [f"{repo_id}: {cur['state']}"]
    clone = Path(cur.get("clone") or clone_path(gitops_dir, repo_id))
    sh = ship.load_state(clone) if clone.is_dir() else None
    archived = False
    if not sh and cur.get("spec") and clone.is_dir():   # spec 155: the repo's session archived its ship already
        import shipwait
        sh = shipwait._archived(clone, cur["spec"])
        archived = sh is not None
    if not sh:
        raise PlatformError(f"no ship run in {clone}", hint=f"start it: cplat component ship start <spec> --system-dir {gitops_dir}")
    slug = state.slug(gitops_dir)
    want = f"{slug}:{st['spec']}"
    repo_spec = specmod.find(clone, sh["spec"])
    parent = repo_spec.meta.get("parent")
    if parent != want:
        raise PlatformError(f"the spec {sh['spec']} of {repo_id} has parent '{parent}', not '{want}'",
                            hint=f"create the repo spec with `cplat spec new --from-plan docs/plan/{st['spec']}.md {repo_id}` (it sets parent)")
    gate = cur.get("gate") or gate_class(gitops_dir, repo)
    smoke = sh.get("smoke") or {}
    if (st.get("joint") and smoke.get("outcome") == "deferred" and not sh.get("escalated") and sh["phase"] == "done"
            and gate != "library"):
        return _pin_result(gitops_dir, st, repo_id, clone, sh, repo_spec, gate, archived)
    sha, svc = sh.get("merge_sha") or "", repo_id
    argo = "-"
    outcome: tuple[str, str | None] = ("passed", None)
    if sh.get("escalated"):
        outcome = ("escalated", None)
    elif sh["phase"] != "done":
        raise PlatformError(f"ship of {repo_id} is in phase {sh['phase']}; resume it",
                            hint=f"cplat component ship start {sh['spec']} --system-dir {gitops_dir} (in {clone})")
    elif gate == "library":
        if not sha:
            outcome = ("escalated", f"the PR of {repo_id} is not merged")
    elif gate == "exposed":
        if smoke.get("outcome") in ("passed", "passed-on-retry"):
            argo = "Synced/Healthy" if sh.get("deployed") else "-"
        else:
            why = smoke.get("reason") or smoke.get("row") or smoke.get("outcome") or "no smoke result"
            outcome = ("escalated", f"smoke not run in dev for {repo_id}: {why}; an exposed service needs passing smoke")
    else:
        health = None
        if sha and sh.get("deployed") == f"sha-{sha}" and context:
            health = ship.argo_health(context, f"{svc}-dev", 120, 10, {sh["deployed"], f"sha-{sha[:7]}"})
        argo = health if health == "Synced/Healthy" else "-"
        if health != "Synced/Healthy":
            outcome = ("escalated", f"{svc}-dev is not Synced/Healthy on sha-{sha}")
    steps = ship.plan_meta(clone, sh).get("human_steps") or []

    def change(s: dict) -> None:
        e = s["repos"].setdefault(repo_id, {})
        e.update(gate=gate, spec=sh["spec"], pr=sh.get("pr"), fix_rounds=sh.get("fix_rounds", 0), deployed=sh.get("deployed"),
                 argo=argo, smoke_row=smoke.get("row"), human_steps=list(steps), run_id=sh.get("run_id"),
                 decisions=specmod.decisions(repo_spec.body))          # spec 141: answers taken for the user
        e.pop("questions", None)
        e.pop("held", None)
        if outcome[0] == "passed":
            e["state"] = "passed"
        elif sh.get("escalated"):
            e.update(state="escalated", reason=sh["escalated"], cause=sh.get("cause") or "unknown")
            if sh.get("questions"):
                e["questions"] = sh["questions"]
        else:
            e.update(state="escalated", reason=outcome[1], cause="environment" if gate != "library" else "decision")
        if sh.get("run_id") and sh["run_id"] not in s.setdefault("ships", []):
            s["ships"].append(sh["run_id"])
    state.update(gitops_dir, change)
    if not archived and not _session_runs(cur):
        ship.finish(clone)
    if outcome[0] == "passed":
        return True, [f"{repo_id}: passed ({gate})"]
    return False, [f"{repo_id}: escalated ({sh.get('escalated') or outcome[1]})"]


def _pin_result(gitops_dir: Path, st: dict, repo_id: str, clone: Path, sh: dict, repo_spec: specmod.Spec,
                gate: str, archived: bool = False) -> tuple[bool, list[str]]:
    """Spec 144 (AC-144.1, AC-144.3): a component ship of a joint run ended at its image: pin it in the dev PR."""
    import appship_joint
    tag = (sh.get("joint") or {}).get("tag") or f"sha-{sh.get('merge_sha')}"
    comp, lines = appship_joint.pin(gitops_dir, st, repo_id, tag)
    steps = ship.plan_meta(clone, sh).get("human_steps") or []

    def change(s: dict) -> None:
        e = s["repos"].setdefault(repo_id, {})
        e.update(state="pinned", gate=gate, spec=sh["spec"], pr=sh.get("pr"), fix_rounds=sh.get("fix_rounds", 0), pinned=tag,
                 component=comp, deployed=None, argo="-", smoke_row=None, human_steps=list(steps), run_id=sh.get("run_id"),
                 decisions=specmod.decisions(repo_spec.body))
        for k in ("smoke", "staging_row", "staging_smoke"):
            e.pop(k, None)
        if sh.get("run_id") and sh["run_id"] not in s.setdefault("ships", []):
            s["ships"].append(sh["run_id"])
    state.update(gitops_dir, change)
    if not archived and not _session_runs(st["repos"].get(repo_id) or {}):
        ship.finish(clone)
    pr = state.require_state(gitops_dir).get("joint_pr")
    return True, [f"{repo_id}: pinned {tag} in the system ship's dev PR ({pr})", *lines]
