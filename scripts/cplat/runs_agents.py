"""Agent metrics (spec 089): which agent, on which shape and model, needed how much rework.

The sections `agents`, `replans` and `agent_metrics` live in the 087 run record of a build (or of the ship run it
attached to). Events are the source of truth; `counts` is derived from them and from `agent_metrics.measured`.
Contract: docs/specs/089-agent-quality-is-measured-per-agent-and/design.md.

Every public function takes `run_id` first (None, unknown or finished: no-op), never raises and prints nothing.
A malformed argument marks the run's agent metrics incomplete (runs.mark_incomplete) and records nothing else.

  cplat runs agent spawned|merged|conflict|conflict-outcome|replan|fix-round|findings|tester ...   (always exit 0)
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path
from typing import Callable, Sequence

import core
import runs
import shapecmd
import spec as specmod

SECTION, REPLANS, STATUS = "agents", "replans", "agent_metrics"
METRICS = ("out_of_plan", "merge_conflicts", "replans", "fix_rounds", "red_ci", "findings", "refused_test_diffs",
           "tester_events")
ROLE_METRICS = {"architect": ("out_of_plan", "merge_conflicts", "replans"),
                "coder": ("fix_rounds", "red_ci", "findings", "refused_test_diffs"),
                "quality": ("refused_test_diffs",), "tester": ("tester_events",)}
FIX_CAUSES = ("lint/type", "test", "ci", "verification")
SEVERITIES = ("not met", "partial", "deviation")
TESTER_REASONS = ("untraced", "wrong failure")
CONFLICT_OUTCOMES = ("re-planned", "resolved", "escalated")
PASSES = ("first", "after fix")

_PROBLEMS: list[str] = []      # problems of the current call (the CLI prints the first one)
_AC_RE = re.compile(r"^AC-\d+\.\d+$")


class _Malformed(Exception):
    """An argument or a state the recording cannot use."""


# ---------------- identity ----------------

def _model_of(plugin: str, role: str) -> str:
    try:
        text = (core.PLATFORM_ROOT / "plugins" / plugin / "agents" / f"{role}.md").read_text()
        head = text.split("---", 2)[1] if text.startswith("---") else ""
        m = re.search(r"^model:\s*([\w.-]+)\s*$", head, re.M)
        return m.group(1) if m else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def identity(repo: Path, role: str, model_id: str | None = None) -> dict:
    """{"agent", "shape", "model", "model_id"} for a role (`coder`) or a full name (`web:coder`)."""
    try:
        routed = shapecmd.route(Path(repo))
        shape, agents = routed["shape"], routed["agents"]
    except Exception:  # noqa: BLE001
        shape, agents = "none", {}
    if ":" in role:
        name = role
    else:
        name = agents.get(role) or (f"shared:{role}" if role in ("quality", "security") else f"svc:{role}")
    plugin, _, short = name.partition(":")
    return {"agent": name, "shape": shape, "model": _model_of(plugin, short), "model_id": model_id}


# ---------------- the sections ----------------

def _status() -> dict:
    return {"schema": 1, "complete": True, "measured": [], "problems": []}


def _ensure(rec: dict) -> None:
    if not isinstance(rec.get(SECTION), list):
        rec[SECTION] = []
    if not isinstance(rec.get(REPLANS), list):
        rec[REPLANS] = []
    if not isinstance(rec.get(STATUS), dict):
        rec[STATUS] = _status()


def init(run_id: str | None) -> None:
    runs.mutate(run_id, _ensure)


def _entry(rec: dict, ident: dict) -> dict:
    key = f"{ident['agent']}|{ident['shape']}|{ident['model']}"
    for e in rec[SECTION]:
        if e.get("id") == key:
            if ident.get("model_id"):
                e["model_id"] = ident["model_id"]
            return e
    e = {"id": key, "agent": ident["agent"], "shape": ident["shape"], "model": ident["model"],
         "model_id": ident.get("model_id"), "counts": {}, "events": []}
    rec[SECTION].append(e)
    return e


def _role(entry: dict) -> str:
    return str(entry.get("agent", "")).rpartition(":")[2]


def _of(entry: dict, kind: str) -> list[dict]:
    return [e for e in entry["events"] if e.get("kind") == kind]


def _natural(kind: str, ev: dict):
    if kind == "out-of-plan":
        return (ev.get("task"), ev.get("path"))
    if kind == "finding":
        return (ev.get("cycle"), ev.get("severity"), ev.get("criterion") or ev.get("task"))
    if kind == "tester":
        return (ev.get("reason"), ev.get("criterion") or ev.get("test"))
    if kind == "refused-test-diff":
        return (ev.get("file"), ev.get("task"))
    return None


def _event(rec: dict, entry: dict, kind: str, fields: dict) -> dict:
    """Add the event (or update the one with the same natural key); ids number the kind across the section."""
    key = _natural(kind, fields)
    if key is not None:
        for old in _of(entry, kind):
            if _natural(kind, old) == key:
                old.update(fields)
                return old
    n = 0
    for e in rec[SECTION]:
        for old in _of(e, kind):
            try:
                n = max(n, int(str(old.get("id", "")).rpartition(":")[2]))
            except ValueError:
                pass
    ev = {"id": f"{kind}:{n + 1}", "kind": kind, **fields}
    entry["events"].append(ev)
    return ev


def _counts(entry: dict, measured: set[str]) -> dict:
    role = _role(entry)
    out: dict = {}

    def n(kind: str, **where) -> int:
        return sum(1 for e in _of(entry, kind) if all(e.get(k) == v for k, v in where.items()))

    for metric in ROLE_METRICS.get(role, ()):
        if metric not in measured:
            out[metric] = None
            if metric == "merge_conflicts":
                out["conflicts_resolved"] = None
            continue
        if metric == "out_of_plan":
            out[metric] = n("out-of-plan")
        elif metric == "merge_conflicts":
            out[metric] = n("merge-conflict")
            out["conflicts_resolved"] = n("merge-conflict", outcome="resolved")
        elif metric == "replans":
            out[metric] = n("re-plan")
        elif metric == "fix_rounds":
            out[metric] = {c: n("fix-round", cause=c) for c in FIX_CAUSES}
        elif metric == "red_ci":
            out[metric] = n("red-ci")
        elif metric == "findings":
            out[metric] = {p: {s: n("finding", **{"pass": p, "severity": s}) for s in SEVERITIES} for p in PASSES}
        elif metric == "refused_test_diffs":
            out[metric] = n("refused-test-diff")
        elif metric == "tester_events":
            out[metric] = {r: n("tester", reason=r) for r in TESTER_REASONS}
    return out


def _recount(rec: dict) -> None:
    measured = set(rec[STATUS].get("measured") or [])
    for e in rec[SECTION]:
        e["counts"] = _counts(e, measured)


def _problem(run_id: str | None, text: str) -> None:
    runs.mark_incomplete(run_id, STATUS, text)
    if run_id:
        _PROBLEMS.append(text)


def _live(run_id: str | None) -> dict | None:
    return runs.active(run_id) if run_id else None


def _change(run_id: str | None, fn: Callable[[dict], None], *measure: str) -> bool:
    """fn(rec) under the run lock, then mark `measure` measured and recount. A failure marks the run incomplete."""
    err: list[Exception] = []

    def change(rec: dict) -> None:
        _ensure(rec)
        try:
            fn(rec)
        except Exception as e:  # noqa: BLE001
            err.append(e)
            raise
        status = rec[STATUS]
        status["measured"] = sorted(set(status.get("measured") or []) | set(measure))
        _recount(rec)

    result = runs.mutate(run_id, change)
    if result == "error":
        if err and isinstance(err[0], _Malformed):
            _problem(run_id, f"malformed: {err[0]}")
        elif err:
            _problem(run_id, f"write failed: {type(err[0]).__name__}: {err[0]}"[:200])
        else:
            _problem(run_id, "write failed: the active record could not be updated")
    return result == "ok"


def _guard(run_id: str | None, fn: Callable[[], None]) -> None:
    try:
        fn()
    except _Malformed as e:
        _problem(run_id, f"malformed: {e}")
    except Exception as e:  # noqa: BLE001
        _problem(run_id, f"{type(e).__name__}: {e}"[:200])


# ---------------- plan and git helpers ----------------

def _plan_tasks(repo: Path, ref: str | None) -> tuple[specmod.Spec, list[dict]]:
    if not ref:
        raise _Malformed("the run has no spec")
    try:
        s = specmod.find(Path(repo), ref)
    except Exception as e:  # noqa: BLE001
        raise _Malformed(f"unknown spec {ref!r}") from e
    if not s.plan:
        raise _Malformed(f"{s.id} has no plan")
    return s, [t for t in (s.plan[0].get("tasks") or []) if isinstance(t, dict)]


def _in_files(path: str, files: Sequence[str]) -> bool:
    for f in files:
        f = str(f)
        if path == f or (f.endswith("/") and path.startswith(f)):
            return True
        if any(c in f for c in "*?[") and fnmatch.fnmatchcase(path, f.replace("**", "*")):
            return True
    return False


def _git_paths(repo: Path, *args: str) -> list[str]:
    proc = core.run(["git", "-C", str(repo), "diff", "--name-only", *args], check=False)
    if proc.returncode != 0:
        raise _Malformed("git diff failed: " + ((proc.stderr or "").strip().splitlines() or ["?"])[-1][:80])
    return [p for p in proc.stdout.splitlines() if p]


def _text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Malformed(f"{what} {value!r}")
    return value.strip()


# ---------------- recording ----------------

def spawned(run_id: str | None, repo: Path, role: str, *, model_id: str | None = None) -> None:
    if not _live(run_id):
        return

    def go() -> None:
        ident = identity(repo, _text(role, "role"), model_id)
        _change(run_id, lambda rec: _entry(rec, ident))
    _guard(run_id, go)


def merged(run_id: str | None, repo: Path, task: str, since: str, helpers: Sequence[str] = ()) -> None:
    rec0 = _live(run_id)
    if not rec0:
        return

    def go() -> None:
        tid, rev = _text(task, "task"), _text(since, "since")
        if rev.startswith("-"):
            raise _Malformed(f"since {rev!r}")
        _, tasks = _plan_tasks(repo, rec0.get("spec"))
        files = next((t.get("files") or [] for t in tasks if t.get("id") == tid), None)
        if files is None:
            raise _Malformed(f"unknown task {tid!r}")
        changed = _git_paths(repo, f"{rev}..HEAD")
        extra = set(helpers)
        stray = [p for p in changed if not _in_files(p, files) and p not in extra]
        arch, coder = identity(repo, "architect"), identity(repo, "coder")

        def fn(rec: dict) -> None:
            a = _entry(rec, arch)
            _entry(rec, coder)
            for p in stray:
                _event(rec, a, "out-of-plan", {"task": tid, "path": p})
        _change(run_id, fn, "out_of_plan", "merge_conflicts", "replans", "fix_rounds")
    _guard(run_id, go)


def _partner(tasks: list[dict], task: str, paths: Sequence[str]) -> str | None:
    best, best_n = None, 0
    for t in tasks:
        if not t.get("done") or t.get("id") == task:
            continue
        n = sum(1 for p in paths if _in_files(p, t.get("files") or []))
        if n and n >= best_n:
            best, best_n = t.get("id"), n
    return best


def conflict(run_id: str | None, repo: Path, task: str, *, with_task: str | None = None,
             paths: Sequence[str] | None = None, outcome: str = "escalated", spec: str | None = None) -> str | None:
    rec0 = _live(run_id)
    if not rec0:
        return None
    made: list[str] = []

    def go() -> None:
        tid = _text(task, "task")
        if outcome not in ("re-planned", "escalated"):
            raise _Malformed(f"conflict outcome {outcome!r}")
        found = list(paths) if paths is not None else _git_paths(repo, "--diff-filter=U")
        ref = spec or rec0.get("spec")
        partner = with_task
        if partner is None:
            try:
                partner = _partner(_plan_tasks(repo, ref)[1], tid, found)
            except _Malformed:
                partner = None
        ident = identity(repo, "architect")

        def fn(rec: dict) -> None:
            a = _entry(rec, ident)
            ev = _event(rec, a, "merge-conflict", {
                "spec": ref, "task": tid, "with": partner, "paths": found,
                "author": {"agent": a["agent"], "model": a["model"], "model_id": a.get("model_id")},
                "outcome": outcome})
            made.append(ev["id"])
        _change(run_id, fn, "out_of_plan", "merge_conflicts", "replans")
    _guard(run_id, go)
    return made[0] if made else None


def _latest_conflict(rec: dict, task: str) -> dict | None:
    found = [e for a in rec[SECTION] for e in _of(a, "merge-conflict") if e.get("task") == task]
    return found[-1] if found else None


def conflict_outcome(run_id: str | None, repo: Path, task: str, outcome: str) -> None:
    if not _live(run_id):
        return

    def go() -> None:
        tid = _text(task, "task")
        if outcome not in CONFLICT_OUTCOMES:
            raise _Malformed(f"conflict outcome {outcome!r}")

        def fn(rec: dict) -> None:
            ev = _latest_conflict(rec, tid)
            if ev is None:
                raise _Malformed(f"no merge conflict recorded for {tid}")
            ev["outcome"] = outcome
        _change(run_id, fn)
    _guard(run_id, go)


def replan(run_id: str | None, repo: Path, task: str, *, model_id: str | None = None) -> None:
    rec0 = _live(run_id)
    if not rec0:
        return

    def go() -> None:
        tid = _text(task, "task")
        ident = identity(repo, "architect", model_id)

        def fn(rec: dict) -> None:
            a = _entry(rec, ident)
            cf = _latest_conflict(rec, tid)
            ev = _event(rec, a, "re-plan", {"task": tid, "conflict": cf["id"] if cf else None})
            if cf:
                cf["outcome"] = "re-planned"
            rec[REPLANS].append({"id": ev["id"], "spec": (cf or {}).get("spec") or rec.get("spec"), "task": tid,
                                 "agent": a["agent"], "model": a["model"], "model_id": a.get("model_id"),
                                 "conflict": ev["conflict"]})
        _change(run_id, fn, "replans")
    _guard(run_id, go)


def fix_round(run_id: str | None, repo: Path, cause: str, *, task: str | None = None) -> None:
    if not _live(run_id):
        return

    def go() -> None:
        if cause not in FIX_CAUSES:
            raise _Malformed(f"fix-round cause {cause!r}")
        if task is not None:
            _text(task, "task")
        ident = identity(repo, "coder")

        def fn(rec: dict) -> None:
            _event(rec, _entry(rec, ident), "fix-round", {"cause": cause, "task": task})
        _change(run_id, fn, "fix_rounds")
    _guard(run_id, go)


def red_ci(run_id: str | None, repo: Path, checks: Sequence[str]) -> None:
    if not _live(run_id):
        return

    def go() -> None:
        names = [str(c) for c in checks]
        ident = identity(repo, "coder")

        def fn(rec: dict) -> None:
            c = _entry(rec, ident)
            if names:
                _event(rec, c, "red-ci", {"check": names[0], "checks": names})
        _change(run_id, fn, "red_ci")
    _guard(run_id, go)


def _verdicts(path: Path) -> list[tuple[str, str]]:
    """(criterion, verdict) of each AC row of the criteria table."""
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        raise _Malformed(f"no {path.name}") from e
    col, rows = 1, []
    for line in lines:
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip().strip("*`").strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].lower() in ("criterion", "criteria") and "verdict" in [c.lower() for c in cells]:
            col = [c.lower() for c in cells].index("verdict")
        elif cells and _AC_RE.match(cells[0]) and len(cells) > col:
            rows.append((cells[0], cells[col].lower()))
    if not rows:
        raise _Malformed(f"{path.name} has no criteria table")
    return rows


def findings(run_id: str | None, repo: Path, cycle: int, *, deviations: Sequence[str] = (),
             spec: str | None = None) -> None:
    rec0 = _live(run_id)
    if not rec0:
        return

    def go() -> None:
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 1:
            raise _Malformed(f"findings cycle {cycle!r}")
        s, tasks = _plan_tasks(repo, spec or rec0.get("spec"))
        rows = _verdicts(s.dir / "verification.md")
        ids = {t.get("id") for t in tasks}

        def covering(ac: str) -> list[str]:
            return [str(t["id"]) for t in tasks if ac in (t.get("covers") or [])]

        pas = "first" if cycle == 1 else "after fix"
        events, bad = [], []
        for ac, verdict in rows:
            if verdict in ("not met", "partial"):
                events.append({"criterion": ac, "task": None, "severity": verdict, "pass": pas, "cycle": cycle,
                               "tasks": covering(ac)})
        for d in deviations:
            if _AC_RE.match(str(d)):
                events.append({"criterion": d, "task": None, "severity": "deviation", "pass": pas, "cycle": cycle,
                               "tasks": covering(d)})
            elif d in ids:
                events.append({"criterion": None, "task": d, "severity": "deviation", "pass": pas, "cycle": cycle,
                               "tasks": [d]})
            else:
                bad.append(d)
        ident = identity(repo, "coder")

        def fn(rec: dict) -> None:
            c = _entry(rec, ident)
            for ev in events:
                _event(rec, c, "finding", ev)
        _change(run_id, fn, "findings", "fix_rounds")
        for d in bad:
            _problem(run_id, f"malformed: deviation {d!r}")
    _guard(run_id, go)


def tester(run_id: str | None, repo: Path, *, untraced: Sequence[str] = (), wrong_failures: Sequence[str] = ()) -> None:
    if not _live(run_id):
        return

    def go() -> None:
        ident = identity(repo, "tester")

        def fn(rec: dict) -> None:
            t = _entry(rec, ident)
            for ac in untraced:
                _event(rec, t, "tester", {"reason": "untraced", "criterion": str(ac), "test": None})
            for name in wrong_failures:
                _event(rec, t, "tester", {"reason": "wrong failure", "criterion": None, "test": str(name)})
        _change(run_id, fn, "tester_events")
    _guard(run_id, go)


def refused_test_diff(run_id: str | None, repo: Path, files: Sequence[tuple[str, str]], *, by: str = "coder",
                      task: str | None = None) -> None:
    if not _live(run_id):
        return

    def go() -> None:
        if by not in ("coder", "quality"):
            raise _Malformed(f"test-diff --by {by!r}")
        coder, who = identity(repo, "coder"), identity(repo, by)

        def fn(rec: dict) -> None:
            _entry(rec, coder)                    # the coder took part either way
            w = _entry(rec, who)
            for f, why in files:
                _event(rec, w, "refused-test-diff", {"file": str(f), "reason": str(why), "task": task})
        _change(run_id, fn, "refused_test_diffs")
    _guard(run_id, go)


# ---------------- CLI ----------------

class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # type: ignore[override]
        raise _Usage(message)

    def exit(self, status=0, message=None):  # type: ignore[override]
        raise _Usage(message or "exit")

    def _print_message(self, message, file=None):  # never print: the CLI is silent on stdout
        pass


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="cplat runs agent", description="Record an agent signal in the current run (spec 089).")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str) -> argparse.ArgumentParser:
        s = sub.add_parser(name)
        s.add_argument("--dir", default=".")
        return s

    s = add("spawned")
    s.add_argument("role")
    s.add_argument("--model-id")
    s = add("merged")
    s.add_argument("task")
    s.add_argument("--since", required=True)
    s.add_argument("--helper", action="append", default=[])
    s = add("conflict")
    s.add_argument("task")
    s.add_argument("--with", dest="with_task")
    s.add_argument("--path", action="append")
    s.add_argument("--outcome", default="escalated")
    s.add_argument("--spec")
    s = add("conflict-outcome")
    s.add_argument("task")
    s.add_argument("outcome")
    s = add("replan")
    s.add_argument("task")
    s.add_argument("--model-id")
    s = add("fix-round")
    s.add_argument("cause")
    s.add_argument("--task")
    s = add("findings")
    s.add_argument("--cycle", required=True)
    s.add_argument("--deviation", action="append", default=[])
    s.add_argument("--spec")
    s = add("tester")
    s.add_argument("--untraced", action="append", default=[])
    s.add_argument("--wrong-failure", action="append", default=[])
    return p


def _dir_of(argv: list[str]) -> Path:
    for i, a in enumerate(argv):
        if a == "--dir" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if a.startswith("--dir="):
            return Path(a[6:])
    return Path(".")


def _dispatch(ns: argparse.Namespace, rid: str | None) -> None:
    repo = Path(ns.dir).resolve()
    c = ns.cmd
    if c == "spawned":
        spawned(rid, repo, ns.role, model_id=ns.model_id)
    elif c == "merged":
        merged(rid, repo, ns.task, ns.since, ns.helper)
    elif c == "conflict":
        conflict(rid, repo, ns.task, with_task=ns.with_task, paths=ns.path, outcome=ns.outcome, spec=ns.spec)
    elif c == "conflict-outcome":
        conflict_outcome(rid, repo, ns.task, ns.outcome)
    elif c == "replan":
        replan(rid, repo, ns.task, model_id=ns.model_id)
    elif c == "fix-round":
        fix_round(rid, repo, ns.cause, task=ns.task)
    elif c == "findings":
        try:
            cycle = int(ns.cycle)
        except ValueError:
            _problem(rid, f"malformed: findings cycle {ns.cycle!r}")
            return
        findings(rid, repo, cycle, deviations=ns.deviation, spec=ns.spec)
    elif c == "tester":
        tester(rid, repo, untraced=ns.untraced, wrong_failures=ns.wrong_failure)


def main(argv: list[str]) -> int:
    """Record one signal. Always returns 0, prints nothing on stdout; one WARNING line on stderr when it could not."""
    _PROBLEMS.clear()
    rid = None
    try:
        try:
            rid = runs.current_run(_dir_of(argv))
            ns = build_parser().parse_args(argv)
        except _Usage as e:
            _problem(rid, f"malformed: {str(e).strip()[:120] or 'usage'}")
        else:
            _dispatch(ns, rid)
    except BaseException as e:  # noqa: BLE001  (recording never fails a build)
        if isinstance(e, KeyboardInterrupt):
            raise
        _problem(rid, f"{type(e).__name__}: {e}"[:200])
    if _PROBLEMS:
        try:
            print(f"WARNING: agent metric not recorded ({_PROBLEMS[0]}); this run's agent metrics are marked incomplete",
                  file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
    return 0
