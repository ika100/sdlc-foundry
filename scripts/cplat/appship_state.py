"""`cplat app-ship` state (spec 097): the product run's state file, start checks, resume, escalate, finish, run record
and the Stop hook gate. Scheduling is in appship_sched, merging in appship_merge, rendering in appship_report."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import io
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import yaml

import budget
import runs
import ship
import spec as specmod
from core import PlatformError, run

PHASES = ["plan", "publish", "repos", "complete", "done"]
STATE_FILE = "cplat-app-ship.json"
STATE_LOCK = "cplat-app-ship.state.lock"
DEFAULT_MAX = 3
DEFAULT_MAX_BLOCKS = 8
PASSED = ("passed", "done-before")


def slug(repo: Path) -> str | None:
    """owner/name from the configured origin URL (not `get-url`, which applies `insteadOf` rewrites)."""
    url = run(["git", "config", "--get", "remote.origin.url"], cwd=repo, check=False).stdout.strip()
    m = re.search(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else runs.repo_slug(repo)


# ---------------- state file ----------------

def common_dir(repo: Path) -> Path:
    return ship.state_path(repo).parent


def state_path(repo: Path) -> Path:
    return common_dir(repo) / STATE_FILE


def load_state(repo: Path) -> dict | None:
    f = state_path(repo)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except ValueError:
        return None


def _ensure_run(repo: Path, st: dict) -> str | None:
    rid = st.get("run_id")
    if rid and (st.get("recorded") or runs.active(rid) is not None):
        return rid
    st["run_id"] = runs.start("product-ship", repo=slug(repo), spec=st.get("spec"), run_id=rid,
                              started_at=ship._utc_iso(st.get("started")))
    return st["run_id"]


def _fields(st: dict) -> dict:
    return {"ships": list(st.get("ships") or []), "repos": {i: r.get("state") for i, r in (st.get("repos") or {}).items()}}


def _record(repo: Path, st: dict) -> None:
    """Spec 087: one end record (none at the start). Never raises."""
    rid = _ensure_run(repo, st)
    if not rid or st.get("recorded"):
        return
    runs.phase(rid, st["phase"])
    if st.get("escalated"):
        runs.finish(rid, "escalated", escalation={"reason": st["escalated"], "cause": st.get("cause") or "unknown"}, fields=_fields(st))
        st["recorded"] = True
    elif st["phase"] == "done":
        runs.finish(rid, "done", fields=_fields(st))
        st["recorded"] = True


def save_state(repo: Path, st: dict) -> None:
    try:
        _record(repo, st)
    except Exception:  # noqa: BLE001  (recording never changes a run)
        pass
    st["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    state_path(repo).write_text(json.dumps(st, indent=2) + "\n")


def require_state(repo: Path) -> dict:
    st = load_state(repo)
    if not st:
        raise PlatformError("no product ship run in this repo", hint="start one with `/app:ship <spec>` (cplat app-ship start <spec>)")
    return st


@contextlib.contextmanager
def _locked(repo: Path) -> Iterator[None]:
    with open(common_dir(repo) / STATE_LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def update(repo: Path, fn: Callable[[dict], None]) -> dict:
    """Load, apply `fn`, save, holding the state lock (parallel repo ships write the same file)."""
    with _locked(repo):
        st = require_state(repo)
        fn(st)
        save_state(repo, st)
        return st


# ---------------- plan ----------------

def plan_path(repo: Path, spec_id: str) -> Path:
    return repo / "docs" / "plan" / f"{spec_id}.md"


def plan_meta(repo: Path, spec_id: str) -> dict:
    f = plan_path(repo, spec_id)
    if not f.is_file():
        return {}
    m = specmod.FRONT.match(f.read_text())
    try:
        meta = yaml.safe_load(m.group(1)) if m else None
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


def plan_repos(repo: Path, spec_id: str) -> list[dict]:
    return [r for r in plan_meta(repo, spec_id).get("repos") or [] if isinstance(r, dict) and r.get("id")]


def refresh_repos(repo: Path, st: dict) -> None:
    """`repos` from the plan: `done: true` is past its gate (done-before); existing entries keep their state."""
    repos = st.setdefault("repos", {})
    for r in plan_repos(repo, st["spec"]):
        e = repos.setdefault(r["id"], {"state": "done-before" if r.get("done") else "ready"})
        e["shape"] = r.get("shape")
        e["depends_on"] = list(r.get("depends_on") or [])


# ---------------- start ----------------

def services(repo: Path) -> list[str]:
    names: list[str] = []
    for f in sorted((repo / "applications").glob("*/services.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        names += [str(e["name"]) for e in (data.get("services") or []) if isinstance(e, dict) and e.get("name")]
    return names


def resolve_context(repo: Path, context: str | None) -> str:
    refusal = PlatformError("no kube context for the product's cluster",
                            hint="pass --context <name> or select it: kubectl config use-context <name>")
    ctx = context
    if not ctx:
        cur = run(["kubectl", "config", "current-context"], check=False)
        ctx = cur.stdout.strip() if cur.returncode == 0 else ""
    if not ctx:
        raise refusal
    apps = run(["kubectl", "--context", ctx, "-n", "argocd", "get", "applications", "-o", "name"], check=False)
    if apps.returncode != 0:
        raise refusal
    names = {ln.strip().rsplit("/", 1)[-1] for ln in apps.stdout.splitlines() if ln.strip()}
    svcs = services(repo)
    if svcs and not any(f"{s}-dev" in names for s in svcs):
        raise refusal
    return ctx


def _open_budget(repo: Path, st: dict, options: dict) -> None:
    """Spec 102: the product run owns the budget of its repo ships: the ship defaults times the plan's repos."""
    budget.open_root(st.get("run_id"), budget.work_key(repo, st["spec"], st["spec"]), ships=len(plan_repos(repo, st['spec'])), options=options, repo=repo)


def start(repo: Path, ref: str, max_: int | None = None, context: str | None = None,
          budget_options: list[str] | dict | None = None) -> dict:
    import shapecmd
    options = budget.parse_options(budget_options)
    try:
        shape = shapecmd.route(repo)["shape"]
    except PlatformError:
        shape = "unknown"
    if shape != "gitops-app":
        raise PlatformError(f"this is a {shape} repo: a component spec ships with /svc:ship <spec>", hint=f"/svc:ship {ref}")
    sp = specmod.find(repo, ref)
    if sp.status not in {"approved", "building"}:
        raise PlatformError(f"{sp.id} is '{sp.status}'; only an approved product spec is shipped",
                            hint=f"/app:spec approve {sp.number}")
    st = load_state(repo)
    ctx = resolve_context(repo, context or (st.get("context") if st and st.get("spec") == sp.id else None))
    if st and st["spec"] != sp.id and st["phase"] != "done" and not st.get("escalated"):
        raise PlatformError(f"another product ship run is in progress: {st['spec']} (phase {st['phase']})",
                            hint="finish it with `cplat app-ship finish`")
    origin = slug(repo)
    if st and st["spec"] == sp.id:
        if st.get("escalated"):                # spec 087: a resumed escalated run is a new run
            st["run_id"] = runs.start("product-ship", repo=origin, spec=sp.id, resumes=st.get("run_id"))
            st["recorded"] = False
        st["escalated"] = st["cause"] = None
        st["blocks"] = 0
        st["context"] = ctx
        if max_:
            st["max"] = max_
        for r in st.get("repos", {}).values():
            if r.get("state") == "escalated":
                r["state"] = "ready"
                r.pop("reason", None)
                r.pop("cause", None)
        refresh_repos(repo, st)
        with _locked(repo):
            save_state(repo, st)
        _open_budget(repo, st, options)
        return st
    phase = "publish" if plan_path(repo, sp.id).is_file() else "plan"
    st = {"spec": sp.id, "phase": phase, "max": max_ or DEFAULT_MAX, "context": ctx, "recorded": False,
          "started": dt.datetime.now().isoformat(timespec="seconds"), "blocks": 0, "escalated": None, "cause": None,
          "repos": {}, "ships": [], "waiting": [], "gitops_merged": []}
    if st["phase"] != "plan":
        refresh_repos(repo, st)
    state_path(repo).parent.mkdir(parents=True, exist_ok=True)
    with _locked(repo):
        save_state(repo, st)
    _open_budget(repo, st, options)
    return st


def set_phase(repo: Path, phase: str) -> dict:
    if phase not in PHASES:
        raise PlatformError(f"unknown phase '{phase}'", hint="one of " + ", ".join(PHASES))

    def change(st: dict) -> None:
        st["phase"] = phase
        st["blocks"] = 0
        if phase != "plan":
            refresh_repos(repo, st)
    return update(repo, change)


# ---------------- escalate / finish ----------------

def escalate(repo: Path, reason: str, cause: str | None = None) -> dict:
    """End the run escalated. The cause is the escalated repo's when there is one (spec 097, AC-097.12)."""
    def change(st: dict) -> None:
        bad = next(((i, r) for i, r in st.get("repos", {}).items() if r.get("state") == "escalated"), None)
        why, final = reason, ship._coerce_cause(cause)[0]
        if bad:
            if bad[1].get("cause"):
                final = bad[1]["cause"]
            if cause is None and not reason.startswith(bad[0]):
                why = f"{bad[0]}: {reason}"
        st["escalated"] = why
        st["cause"] = final
    st = update(repo, change)
    budget.snapshot(repo, st.get("phase") or "none", st.get("escalated") or reason, [])   # spec 102: local only
    return st


def finish(repo: Path) -> Path:
    f = state_path(repo)
    with _locked(repo):
        st = require_state(repo)
        if not st.get("recorded"):
            runs.finish(st.get("run_id"), "abandoned", fields=_fields(st))
        done = f.with_name(f"cplat-app-ship-{st['spec']}-{dt.datetime.now():%Y%m%d%H%M%S}.json")
        f.rename(done)
    return done


# ---------------- describe / Stop hook ----------------

def next_step(st: dict) -> str:
    sid = st["spec"]
    return {
        "plan": f"plan the product unattended (/app:plan {sid}), then `cplat app-ship phase publish`",
        "publish": "publish the spec and plan: `cplat app-ship publish`",
        "repos": "`cplat app-ship next --json`, then start the repos it lists (`cplat app-ship repo start <id>`) "
                 "and read each result (`cplat app-ship repo result <id>`)",
        "complete": "`cplat app-ship complete`, print its report, then `cplat app-ship finish`",
        "done": "nothing: the run is finished (`cplat app-ship finish`)",
    }[st["phase"]]


def describe(st: dict) -> str:
    head = f"product ship {st['spec']}: phase {st['phase']}" + (f" — ESCALATED: {st['escalated']}" if st.get("escalated") else "")
    lines = [head]
    if st.get("context"):
        lines.append(f"  context: {st['context']}")
    lines.append(f"next: {next_step(st)}")
    return "\n".join(lines)


def gate(repo: Path, hook_input: dict, max_blocks: int = DEFAULT_MAX_BLOCKS) -> dict | None:
    """None lets the session stop; a dict is the hook's JSON answer."""
    try:
        st = load_state(repo)
    except PlatformError:
        return None
    if not st or st.get("escalated") or st["phase"] == "done":
        return None
    if st.get("blocks", 0) >= max_blocks:
        with contextlib.redirect_stderr(io.StringIO()):     # the hook's output is its answer only
            escalate(repo, f"gave up after {max_blocks} attempts to stop in phase {st['phase']}", "environment")
        return None
    blocks = st.get("blocks", 0) + 1
    st = update(repo, lambda s: s.__setitem__("blocks", s.get("blocks", 0) + 1))
    reason = [f"The product ship of {st['spec']} is not finished (phase {st['phase']}, stop attempt {blocks}/{max_blocks}).",
              f"Next: {next_step(st)}.",
              "Keep going. Only if a rule needs the user (a question of a repo spec, a conflict, a decision the spec does not answer) "
              "or the user asked you to stop: run `cplat app-ship escalate '<reason>' --cause <platform|code|decision|environment>`, then stop."]
    return {"decision": "block", "reason": "\n".join(reason)}


_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def valid_id(repo_id: str) -> str:
    if not _ID.match(repo_id):
        raise PlatformError(f"'{repo_id}' is not a repo id")
    return repo_id
