"""`cplat app-ship` scheduling (spec 097): which repos start, gate classes and gate evaluation, repo start/result/escalate."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import appship_state as state
import core
import runs
import ship
import spec as specmod
from core import PlatformError, run

PASSED = state.PASSED


def entry_path(gitops_dir: Path, spec_id: str) -> Path:
    return state.common_dir(gitops_dir) / "cplat-app-ship" / f"{spec_id}-entry"


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
    if st["phase"] == "done":
        action = "done"
    elif running:
        action = "wait"
    elif start:
        action = "start"
    elif plan and all(_state_of(st, r["id"]) in PASSED for r in plan) and not st.get("escalated"):
        action = "complete"
    elif stopped:
        action = "escalate"
    else:
        action = "wait" if not plan else "escalate"
    return {"phase": st["phase"], "start": start, "running": running, "blocked": blocked, "escalated": escalated, "action": action}


# ---------------- gate classes ----------------

def _show(gitops_dir: Path, path: str) -> dict:
    out = run(["git", "show", f"origin/main:{path}"], cwd=gitops_dir, check=False)
    try:
        data = yaml.safe_load(out.stdout) if out.returncode == 0 else None
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def gate_class(gitops_dir: Path, repo: dict) -> str:
    """entry | library | exposed | internal. Exposed is smoke.dev_url's rule: `expose`, `dev` in environments, `hosts.dev`."""
    shape = repo.get("shape")
    if shape == "gitops-app":
        return "entry"
    entry = next((s for s in core.registry.load() if s["id"] == shape), None)
    if entry is not None and not entry["deployable"]:
        return "library"
    run(["git", "fetch", "-q", "origin"], cwd=gitops_dir, check=False)
    tree = run(["git", "ls-tree", "--name-only", "origin/main", "applications/"], cwd=gitops_dir, check=False).stdout.split()
    for app in tree:
        services = _show(gitops_dir, f"{app}/services.yaml")
        found = next((e for e in services.get("services") or []
                      if isinstance(e, dict) and (str(e.get("repo") or "").endswith("/" + repo["id"]) or e.get("name") == repo["id"])), None)
        if found is None:
            continue
        hosts = (_show(gitops_dir, f"{app}/app.yaml").get("hosts") or {})
        if found.get("expose") and "dev" in (found.get("environments") or ["dev"]) and hosts.get("dev"):
            return "exposed"
        return "internal"
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
    if repo.get("shape") == "gitops-app":
        path = _start_entry(gitops_dir, st["spec"])
    else:
        path = clone_path(gitops_dir, repo_id).absolute()
        if not path.exists():
            ship.gh(["repo", "clone", f"{_org(gitops_dir)}/{repo_id}", str(path)], cwd=gitops_dir.parent)
        if run(["git", "status", "--porcelain"], cwd=path).stdout.strip():
            raise PlatformError(f"{path} has uncommitted changes; commit or stash them, then resume",
                                hint="commit or stash the work in that clone, then run the command again")
    gate = gate_class(gitops_dir, repo)

    def change(s: dict) -> None:
        e = s["repos"].setdefault(repo_id, {})
        e.update(state="running", clone=str(path), gate=gate, shape=repo.get("shape"), depends_on=list(repo.get("depends_on") or []))
        e.pop("reason", None)
        e.pop("cause", None)
    state.update(gitops_dir, change)
    return path


def escalate_repo(gitops_dir: Path, repo_id: str, reason: str, cause: str | None) -> dict:
    final = ship._coerce_cause(cause)[0]

    def change(s: dict) -> None:
        e = s["repos"].setdefault(repo_id, {})
        e.update(state="escalated", reason=reason, cause=final)
    return state.update(gitops_dir, change)


def result(gitops_dir: Path, repo_id: str, context: str | None) -> tuple[bool, list[str]]:
    """Read the repo's finished ship from its clone, evaluate its gate, archive the clone's ship state."""
    st = state.require_state(gitops_dir)
    repo = _plan_entry(gitops_dir, st, repo_id)
    cur = st["repos"].get(repo_id, {})
    if cur.get("state") in PASSED:
        return True, [f"{repo_id}: {cur['state']}"]
    clone = Path(cur.get("clone") or clone_path(gitops_dir, repo_id))
    sh = ship.load_state(clone) if clone.is_dir() else None
    if not sh:
        raise PlatformError(f"no ship run in {clone}", hint=f"start it: cplat ship start <spec> --product {gitops_dir}")
    slug = state.slug(gitops_dir)
    want = f"{slug}:{st['spec']}"
    parent = specmod.find(clone, sh["spec"]).meta.get("parent")
    if parent != want:
        raise PlatformError(f"the spec {sh['spec']} of {repo_id} has parent '{parent}', not '{want}'",
                            hint=f"create the repo spec with `cplat spec new --from-plan docs/plan/{st['spec']}.md {repo_id}` (it sets parent)")
    gate = cur.get("gate") or gate_class(gitops_dir, repo)
    smoke = sh.get("smoke") or {}
    sha, svc = sh.get("merge_sha") or "", repo_id
    argo = "-"
    outcome: tuple[str, str | None] = ("passed", None)
    if sh.get("escalated"):
        outcome = ("escalated", None)
    elif sh["phase"] != "done":
        raise PlatformError(f"ship of {repo_id} is in phase {sh['phase']}; resume it",
                            hint=f"cplat ship start {sh['spec']} --product {gitops_dir} (in {clone})")
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
                 argo=argo, smoke_row=smoke.get("row"), human_steps=list(steps), run_id=sh.get("run_id"))
        if outcome[0] == "passed":
            e["state"] = "passed"
        elif sh.get("escalated"):
            e.update(state="escalated", reason=sh["escalated"], cause=sh.get("cause") or "unknown")
        else:
            e.update(state="escalated", reason=outcome[1], cause="environment" if gate != "library" else "decision")
        if sh.get("run_id") and sh["run_id"] not in s.setdefault("ships", []):
            s["ships"].append(sh["run_id"])
    state.update(gitops_dir, change)
    ship.finish(clone)
    if outcome[0] == "passed":
        return True, [f"{repo_id}: passed ({gate})"]
    return False, [f"{repo_id}: escalated ({sh.get('escalated') or outcome[1]})"]
