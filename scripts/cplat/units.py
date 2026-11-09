"""`units`: the units of an unattended run, when each one is done, and what the run state says about them (spec 131).

A ship or build run is split into units: `plan`, `red-tests`, one `task:<id>` per plan task, or one `batch:<id>,<id>` per
batch of `parallel_safe` tasks that may run at once (spec 159), `verification` and `land`.
Each unit is complete when its rule holds in the **committed** tree of the feature head (`git show B:<path>`), never in the
working tree. The state lives in `<git dir>/cplat-units.json` (local, never committed): one entry per unit with its status,
sessions, stalls and checkpoint commit. The supervisor in headless.py starts one session per open unit.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import core
import runs
import spec as specmod
import yaml
from core import PlatformError, run

STALL_LIMIT = 2
PARALLEL_ENV = "CPLAT_PARALLEL_TASKS"   # spec 159: tasks per batch unit (`cplat headless --parallel N`); 1 = one task per unit
DEFAULT_PARALLEL = 3
FILE = "cplat-units.json"
VERSION = 1
ACCEPTANCE_MSG = "acceptance tests for"

SHIP_PHASES_AFTER_BUILD = {"pr", "land", "deploy"}


def gh(args: list[str], *, cwd: Path) -> str:   # tests replace this
    return run(["gh", *args], cwd=cwd, check=False).stdout


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _git(repo: Path, *args: str) -> tuple[int, str]:
    p = run(["git", *args], cwd=repo, check=False)
    return p.returncode, p.stdout.strip()


# ---------------- the feature head and the committed tree ----------------

def feature_head(repo: Path, spec_id: str) -> str:
    """`B`: refs/heads/feature/<spec id> when it exists, else HEAD (a full sha)."""
    code, out = _git(repo, "rev-parse", "--verify", "-q", f"refs/heads/feature/{spec_id}")
    if code == 0 and out:
        return out
    return _git(repo, "rev-parse", "HEAD")[1]


def _show(repo: Path, head: str, path: str) -> str | None:
    p = run(["git", "show", f"{head}:{path}"], cwd=repo, check=False)
    return p.stdout if p.returncode == 0 else None


def _spec_dir(repo: Path, spec_id: str) -> Path:
    return repo / specmod.SPECS_DIR / spec_id


def _parse(text: str | None) -> tuple[dict, str] | None:
    if text is None:
        return None
    m = specmod.FRONT.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return (meta, m.group(2)) if isinstance(meta, dict) else None


def _committed(repo: Path, spec_id: str, head: str) -> specmod.Spec | None:
    """The spec as committed in `head` (spec.md and plan.md), or None when spec.md is not there."""
    d = _spec_dir(repo, spec_id)
    base = f"{specmod.SPECS_DIR}/{spec_id}"
    sp = _parse(_show(repo, head, f"{base}/spec.md"))
    if sp is None:
        return None
    return specmod.Spec(d, sp[0], sp[1], _parse(_show(repo, head, f"{base}/plan.md")))


def _plan_tasks(sp: specmod.Spec | None) -> list[dict]:
    if sp is None or sp.plan is None:
        return []
    tasks = sp.plan[0].get("tasks")
    return [t for t in tasks if isinstance(t, dict) and t.get("id")] if isinstance(tasks, list) else []


# ---------------- ids and order ----------------

def parallel() -> int:
    """Spec 159: how many tasks one batch unit runs at once ($CPLAT_PARALLEL_TASKS, default 3)."""
    import os
    try:
        return max(1, int(os.environ.get(PARALLEL_ENV) or DEFAULT_PARALLEL))
    except ValueError:
        return DEFAULT_PARALLEL


def _task_units(by_id: dict[str, dict], level: list[str], cap: int) -> list[str]:
    """One level's units in plan order: the `parallel_safe` tasks with disjoint `files` share a batch (as
    `cplat component build schedule` groups them), at most `cap` per batch; every other task is a unit of its own."""
    batches: list[dict] = []
    for tid in level:
        t, files = by_id[tid], set(by_id[tid].get("files") or [])
        if t.get("parallel_safe") and cap > 1:
            target = next((b for b in batches if b["safe"] and len(b["ids"]) < cap and not (b["files"] & files)), None)
            if target:
                target["ids"].append(tid)
                target["files"] |= files
                continue
        batches.append({"ids": [tid], "files": files, "safe": bool(t.get("parallel_safe"))})
    return [f"batch:{','.join(b['ids'])}" if len(b["ids"]) > 1 else f"task:{b['ids'][0]}" for b in batches]


def tasks_of(unit: str) -> list[str]:
    """The plan tasks a `task:` or `batch:` unit covers; [] for any other unit."""
    kind, _, rest = unit.partition(":")
    return [rest] if kind == "task" else [t for t in rest.split(",") if t] if kind == "batch" else []


def _ids_from(sp: specmod.Spec | None) -> list[str]:
    tasks = _plan_tasks(sp)
    order: list[str] = []
    if tasks:
        by_id = {str(t["id"]): t for t in tasks}
        try:
            levels = specmod.topo_levels([{**t, "id": str(t["id"])} for t in tasks])
        except PlatformError:
            levels = [[str(t["id"]) for t in tasks]]
        plan_pos = {str(t["id"]): i for i, t in enumerate(tasks)}
        cap = parallel()
        for level in levels:
            order += _task_units(by_id, sorted((i for i in level if i in by_id), key=lambda i: plan_pos[i]), cap)
    return ["plan", "red-tests", *order, "verification", "land"]


def unit_ids(repo: Path, spec_id: str) -> list[str]:
    return _ids_from(_committed(repo, spec_id, feature_head(repo, spec_id)))


# ---------------- state file ----------------

def _path(repo: Path) -> Path:
    base = core.git_dir(repo)
    if base is None:
        raise PlatformError(f"{repo} is not a git repository")
    return base / FILE


def _read(repo: Path) -> dict | None:
    f = _path(repo)
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    ok = (isinstance(data, dict) and isinstance(data.get("units"), list) and isinstance(data.get("spec"), str)
          and all(isinstance(u, dict) and "id" in u for u in data["units"]))
    return data if ok else None


def _write(repo: Path, data: dict) -> None:
    runs._atomic_write(_path(repo), json.dumps(data, indent=2))


def _entry(unit: str) -> dict:
    return {"id": unit, "status": "open", "sessions": 0, "stalls": 0, "commit": None, "at": None, "hold": None}


def _update(repo: Path, fn) -> dict | None:
    """Read-modify-write under the run-state lock. `fn(data)` must not lock again. None when there is no file."""
    with runs._locked():
        data = _read(repo)
        if data is None:
            return None
        fn(data)
        _write(repo, data)
        return data


def _unit(data: dict, unit: str) -> dict | None:
    return next((u for u in data["units"] if u["id"] == unit), None)


def _checkpoint(entry: dict, commit: str) -> None:
    entry.update(status="done", commit=commit, at=_now(), stalls=0, hold=None)


# ---------------- completion rules ----------------

def _ship_state(repo: Path) -> dict | None:
    import ship
    return ship.load_state(repo)


def _trace_ok(repo: Path, spec_id: str) -> bool:
    tr = run([sys.executable, str(Path(__file__).with_name("cplat.py")), "spec", "trace", spec_id],
             cwd=repo, check=False, timeout=120)
    return tr.returncode == 0


def _acceptance_commit(repo: Path, head: str) -> bool:
    base = ""
    for ref in ("main", "origin/main"):
        code, out = _git(repo, "merge-base", ref, head)
        if code == 0 and out:
            base = out
            break
    rng = f"{base}..{head}" if base else head
    code, out = _git(repo, "log", f"--grep={ACCEPTANCE_MSG}", "--format=%H", rng)
    return code == 0 and bool(out)


def _done_in(sp: specmod.Spec | None, task: str) -> bool:
    return any(str(t["id"]) == task and t.get("done") is True for t in _plan_tasks(sp))


def _verified(repo: Path, spec_id: str, head: str, sp: specmod.Spec | None) -> bool:
    if sp is None or sp.status != "done":
        return False
    text = _show(repo, head, f"{specmod.SPECS_DIR}/{spec_id}/verification.md")
    if text is None:
        return False
    m = specmod.VERDICT.search(text)
    return bool(m and m.group(1) == "pass")


def _pr_pushed(repo: Path, spec_id: str, head: str) -> bool:
    try:
        out = gh(["pr", "list", "--head", f"feature/{spec_id}", "--state", "all", "--json", "state"], cwd=repo)
        prs = json.loads(out or "[]")
    except (PlatformError, ValueError):
        return False
    if not any(isinstance(p, dict) and p.get("state") in {"OPEN", "MERGED"} for p in prs):
        return False
    _, remote = _git(repo, "rev-parse", "--verify", "-q", f"refs/remotes/origin/feature/{spec_id}")
    return bool(remote) and remote == head


def _evaluate(repo: Path, command: str, spec_id: str, unit: str) -> tuple[str | None, str]:
    """(checkpoint commit or None, the first rule of the table that is not met)."""
    head = feature_head(repo, spec_id)
    sp = _committed(repo, spec_id, head)
    if unit == "plan":
        if sp is None or sp.plan is None:
            return None, f"docs/specs/{spec_id}/plan.md is not committed on the feature branch"
        errs = specmod.check_plan(sp, *sp.plan)
        if errs:
            return None, f"plan.md does not check: {errs[0]}"
        return head, ""
    if unit == "red-tests":
        if not _trace_ok(repo, spec_id):
            return None, f"`cplat spec trace {spec_id}` reports criteria without a test"
        if not _acceptance_commit(repo, head):
            return None, f"no commit 'acceptance tests for ...' on feature/{spec_id}"
        return head, ""
    if tasks := tasks_of(unit):
        open_ = [task for task in tasks if not _done_in(sp, task)]
        if open_:
            return None, f"plan.md does not have `done: true` for {', '.join(open_)} in a commit"
        return head, ""
    if unit == "verification":
        if not _verified(repo, spec_id, head, sp):
            return None, "the committed spec status is not `done` with a verification.md that says **Result:** pass"
        if command == "ship":
            st = _ship_state(repo)
            if not st or st.get("phase") not in SHIP_PHASES_AFTER_BUILD | {"done"}:
                return None, "the ship phase is not `pr` yet (`cplat component ship phase pr`)"
        return head, ""
    if unit == "land":
        if command == "ship":
            st = _ship_state(repo)
            if not st or st.get("phase") != "done":
                return None, "the ship phase is not `done`"
            return st.get("merge_sha") or head, ""
        if not _pr_pushed(repo, spec_id, head):
            return None, f"feature/{spec_id} is not pushed with an open or merged PR"
        return head, ""
    return None, f"unknown unit {unit}"


def detect(repo: Path, command: str, spec_id: str, unit: str) -> str | None:
    return _evaluate(repo, command, spec_id, unit)[0]


def missing(repo: Path, command: str, spec_id: str, unit: str) -> str:
    return _evaluate(repo, command, spec_id, unit)[1] or "nothing"


def next_step(unit: str, spec_id: str) -> str:
    if unit == "plan":
        return f"follow /component:plan {spec_id}, commit docs/specs/{spec_id}/plan.md"
    if unit == "red-tests":
        return (f"write the acceptance tests for every criterion of {spec_id} and commit them as "
                f"'test: acceptance tests for ...' (`cplat spec trace {spec_id}` must pass)")
    if unit.startswith("batch:"):
        tasks = tasks_of(unit)
        return (f"implement tasks {', '.join(tasks)} of the plan at once, as build Phase 2's parallel batch (coders in worktrees, "
                f"merged with `cplat component build merge`), mark each done (`cplat spec task done {spec_id} <task>`) and commit")
    if unit.startswith("task:"):
        task = unit.split(":", 1)[1]
        return f"implement task {task} of the plan, mark it done (`cplat spec task done {spec_id} {task}`) and commit"
    if unit == "verification":
        return (f"follow /component:verify {spec_id}, commit verification.md (Result: pass) and the spec status done; "
                "in a ship run then `cplat component ship phase pr`")
    return "push the branch and open the PR; in a ship run follow the land phase until the ship phase is done"


# ---------------- prepare ----------------

def _derive(repo: Path, spec_id: str, entries: dict[str, dict], head: str, sp: specmod.Spec | None, phase: str) -> None:
    def mark(unit: str) -> None:
        if unit in entries:
            _checkpoint(entries[unit], head)

    if phase == "build":
        mark("plan")
        done = {str(t["id"]) for t in _plan_tasks(sp) if t.get("done") is True}
        for unit in entries:
            if tasks_of(unit) and set(tasks_of(unit)) <= done:
                mark(unit)
    elif phase in SHIP_PHASES_AFTER_BUILD:
        for unit in entries:
            if unit != "land":
                mark(unit)


def prepare(repo: Path, command: str, spec_id: str) -> dict:
    """Load or create the units file and bring it up to date; returns the data."""
    head = feature_head(repo, spec_id)
    sp = _committed(repo, spec_id, head)
    ids = _ids_from(sp)
    existing = _read(repo)
    fresh = existing is None or existing.get("spec") != spec_id
    stored = {} if fresh else {u["id"]: u for u in existing["units"]}
    entries = {i: {**_entry(i), **{k: v for k, v in stored.get(i, {}).items() if k in _entry(i)}, "id": i} for i in ids}
    derived = None if fresh else existing.get("derived")
    escalated = None if fresh else existing.get("escalated")
    if fresh:
        st = _ship_state(repo)
        if st and st.get("spec") == spec_id and st.get("phase") != "done" and not st.get("escalated"):
            _derive(repo, spec_id, entries, head, sp, str(st.get("phase")))
            derived = "5.5"
    st = _ship_state(repo)
    skip_validity = bool(st and st.get("spec") == spec_id and (st.get("merge_sha") or st.get("phase") in {"deploy", "done"}))
    for u in entries.values():
        if u["status"] == "running":
            u["status"] = "open"
        if u["status"] == "done" and not skip_validity:
            ok = u["commit"] and _git(repo, "merge-base", "--is-ancestor", u["commit"], head)[0] == 0
            if not ok and u["id"] == "land":   # a squash merge is no ancestor: land stays done while its PR is still found
                ok = detect(repo, command, spec_id, "land") is not None
            if not ok:                         # e.g. a file left by an earlier run of the same spec in a reused clone
                u.update(status="open", commit=None, at=None)
    for u in entries.values():
        if u["status"] != "done":
            commit = detect(repo, command, spec_id, u["id"])
            if commit:
                _checkpoint(u, commit)
    data = {"version": VERSION, "command": command, "spec": spec_id, "derived": derived, "escalated": escalated,
            "units": [entries[i] for i in ids]}
    with runs._locked():
        _write(repo, data)
    return data


def next_open(data: dict) -> str | None:
    return next((u["id"] for u in data["units"] if u["status"] == "open"), None)


# ---------------- sessions ----------------

def start_session(repo: Path, unit: str, session_id: str | None = None) -> None:
    def mutate(data: dict) -> None:
        u = _unit(data, unit)
        if u is not None:
            u.update(status="running", sessions=int(u.get("sessions", 0)) + 1, hold=None)

    _update(repo, mutate)


def end_session(repo: Path, command: str, spec_id: str, unit: str, before: str) -> dict:
    """Detect the checkpoint after a session. Returns {"checkpoint": sha, "stalls": 0} or {"checkpoint": None, "stalls": n}."""
    commit = detect(repo, command, spec_id, unit)
    moved = feature_head(repo, spec_id) != before
    result: dict = {}

    def mutate(data: dict) -> None:
        u = _unit(data, unit)
        if u is None:
            return
        if commit:
            _checkpoint(u, commit)
        else:
            u.update(status="open", hold=None, stalls=0 if moved else int(u.get("stalls", 0)) + 1)
        result.update(checkpoint=commit, stalls=u["stalls"])

    _update(repo, mutate)
    return result or {"checkpoint": commit, "stalls": 0}


def escalate(repo: Path, reason: str, cause: str) -> None:
    """Mark the units file escalated. Never raises."""
    try:
        _update(repo, lambda data: data.__setitem__("escalated", {"reason": reason, "cause": cause}))
    except Exception:  # noqa: BLE001
        pass


def resume(repo: Path) -> None:
    """A new run after an escalation resumes where it stopped (spec 163): the escalation of the run before is dropped,
    as ship.py does for the ship state, so the supervisor does not read it again after the next session. Never raises."""
    try:
        _update(repo, lambda data: data.__setitem__("escalated", None))
    except Exception:  # noqa: BLE001
        pass


# ---------------- status ----------------

def rows(repo: Path) -> list[dict]:
    data = _read(repo)
    if data is None:
        return []
    return [{"id": u["id"], "status": u.get("status", "open"), "sessions": int(u.get("sessions", 0)),
             "commit": u.get("commit")} for u in data["units"]]


def describe_lines(repo: Path) -> list[str]:
    rs = rows(repo)
    if not rs:
        return []
    out = ["  units:"]
    for r in rs:
        n = r["sessions"]
        sha = r["commit"][:7] if r["commit"] else "-"
        out.append(f"    {r['id']:<20} {r['status']:<9} {n} session{'s' if n != 1 else '':<5}{sha}")
    return out


# ---------------- Stop hook of a unit session ----------------

def gate(repo: Path, unit: str, hook_input: dict) -> dict | None:
    data = _read(repo)
    if data is None or data.get("escalated"):
        return None
    st = _ship_state(repo)
    if st and st.get("spec") == data["spec"] and st.get("escalated"):
        return None
    spec_id, command = data["spec"], data.get("command", "ship")
    entry = _unit(data, unit)
    if entry is None:
        return None
    commit, why = _evaluate(repo, command, spec_id, unit)
    if commit:
        _update(repo, lambda d: _checkpoint(_unit(d, unit), commit) if _unit(d, unit) else None)
        return None
    head = feature_head(repo, spec_id)
    if entry.get("hold") and entry["hold"].get("head") == head:
        return None
    _update(repo, lambda d: _unit(d, unit).__setitem__("hold", {"head": head}) if _unit(d, unit) else None)
    return {"decision": "block",
            "reason": (f"Unit {unit} of {spec_id} is not finished: {why}.\nNext: {next_step(unit, spec_id)}.\n"
                       "Commit your work. Stop when the unit is done; never start another unit.")}


# ---------------- the grace and the next step ----------------

def only_verification_left(repo: Path) -> bool:
    data = _read(repo)
    if data is not None:
        done = {u["id"]: u.get("status") == "done" for u in data["units"]}
        if "verification" not in done or done["verification"]:
            return False
        return all(v for k, v in done.items() if k not in {"verification", "land"})
    st = _ship_state(repo)
    if not st or st.get("phase") != "build":
        return False
    spec_id = st["spec"]
    head = feature_head(repo, spec_id)
    tasks = _plan_tasks(_committed(repo, spec_id, head))
    if not tasks or not all(t.get("done") is True for t in tasks):
        return False
    return _acceptance_commit(repo, head)
