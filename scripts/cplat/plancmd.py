"""cplat plan merge: fold a task into the later task that depends on it (spec 186, AC-186.4).

A task whose checks pass only together with a later task is one task. The plan stays valid: the merged plan is checked
in memory before plan.md is touched, and only plan.md is committed.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import re
from pathlib import Path

import core
import runs
import runs_agents
import ship
import spec as specmod
from core import PlatformError

HEADING = re.compile(r"^## (\S+) — ", re.M)


def _fail(message: str) -> PlatformError:
    return PlatformError(message)


def _spec_ref(repo: Path, given: str | None) -> str:
    if given:
        return given
    branch = core.run(["git", "-C", str(repo), "branch", "--show-current"], check=False).stdout.strip()
    if branch.startswith("feature/"):
        return branch.removeprefix("feature/")
    try:
        st = ship.load_state(repo)
    except PlatformError:
        st = None
    if st and st.get("spec"):
        return str(st["spec"])
    raise _fail("no spec: pass --spec <id> (not on a feature/<id> branch and no ship run)")


def _union(first: list, second: list) -> list:
    return [*first, *[x for x in second if x not in first]]


def merged_tasks(tasks: list[dict], tn: str, tm: str) -> tuple[list[dict], dict, list[str]]:
    """The plan's tasks with `tn` folded into `tm`: (tasks, the merged task, ids of the tasks that moved to `tm`)."""
    tasks = copy.deepcopy(tasks)
    a = next(t for t in tasks if t["id"] == tn)
    b = next(t for t in tasks if t["id"] == tm)
    b["files"] = _union(list(b.get("files") or []), list(a.get("files") or []))
    b["covers"] = _union(list(b.get("covers") or []), list(a.get("covers") or []))
    b["depends_on"] = [d for d in _union(list(b.get("depends_on") or []), list(a.get("depends_on") or [])) if d not in (tn, tm)]
    moved: list[str] = []
    for t in tasks:
        if t is a or t is b:
            continue
        deps = list(t.get("depends_on") or [])
        if tn in deps:
            moved.append(t["id"])
            deps = _union([d for d in deps if d != tn], [tm])
            t["depends_on"] = deps
    tasks = [t for t in tasks if t is not a]
    return tasks, b, moved


def _settle_parallel(tasks: list[dict], merged: dict) -> None:
    """tM keeps `parallel_safe` only when it shares no file with a parallel_safe task of its level."""
    if not merged.get("parallel_safe"):
        return
    level = next((lv for lv in specmod.topo_levels(tasks) if merged["id"] in lv), [])
    mine = set(merged.get("files") or [])
    for t in tasks:
        if t["id"] != merged["id"] and t["id"] in level and t.get("parallel_safe") and mine & set(t.get("files") or []):
            merged["parallel_safe"] = False
            return


def _sections(body: str) -> list[tuple[str, int, int]]:
    marks = list(HEADING.finditer(body))
    return [(m.group(1), m.start(), marks[i + 1].start() if i + 1 < len(marks) else len(body)) for i, m in enumerate(marks)]


def _line_list(text: str, label: str, values: list[str]) -> str:
    return re.sub(rf"^(\*\*{label}:\*\*).*$", lambda m: f"{m.group(1)} {', '.join(values)}", text, count=1, flags=re.M)


def merged_body(body: str, a: dict, b: dict, reason: str) -> str:
    spans = {tid: (s, e) for tid, s, e in _sections(body)}
    if a["id"] not in spans or b["id"] not in spans:
        return body
    (as_, ae), (bs, be) = spans[a["id"]], spans[b["id"]]
    a_text, b_text = body[as_:ae], body[bs:be]
    a_body = a_text.split("\n", 1)[1].strip("\n") if "\n" in a_text else ""
    b_text = _line_list(_line_list(b_text, "Files", b["files"]), "Covers", b["covers"]).rstrip("\n")
    b_text += f"\n\n**Merged from {a['id']} — {a.get('title', '')}** ({reason}):\n\n{a_body}\n\n"
    out = []
    pos = 0
    for start, end, text in sorted([(as_, ae, ""), (bs, be, b_text)]):
        out += [body[pos:start], text]
        pos = end
    out.append(body[pos:])
    return "".join(out)


def merge(repo: Path, tn: str, tm: str, spec_ref: str | None, reason: str | None) -> list[str]:
    sp = specmod.find(repo, _spec_ref(repo, spec_ref))
    if not sp.plan:
        raise _fail(f"{sp.id} has no plan.md")
    meta, body = sp.plan
    tasks = [t for t in (meta.get("tasks") or []) if isinstance(t, dict)]
    by_id = {t.get("id"): t for t in tasks}
    for t in (tn, tm):
        if t not in by_id:
            raise _fail(f"unknown task '{t}' in {sp.id}")
    for t in (tn, tm):
        if by_id[t].get("done"):
            raise _fail(f"{t} is done: a done task is not merged")
    if tn not in (by_id[tm].get("depends_on") or []):
        raise _fail(f"{tm} does not depend on {tn}: only a task that depends directly on another is merged into it")
    path = sp.dir / "plan.md"
    rel = str(path.relative_to(repo))
    if core.run(["git", "-C", str(repo), "status", "--porcelain", "--", rel], check=False).stdout.strip():
        raise _fail(f"{rel} has uncommitted changes: commit them first")

    reason = (reason or "").strip() or f"the checks of {tn} pass only together with {tm}"
    new_tasks, merged, moved = merged_tasks(tasks, tn, tm)
    try:
        _settle_parallel(new_tasks, merged)
    except PlatformError as e:
        raise _fail(f"the merged plan does not check: {e}") from None
    new_meta = {**meta, "tasks": [{**t} for t in new_tasks]}
    errors = specmod.check_plan(dataclasses.replace(sp, plan=(new_meta, body)), new_meta, body)
    if errors:
        raise _fail(f"the merged plan does not check: {errors[0]}")

    text = path.read_text()
    hash_line = re.search(r"^spec_hash:.*$", text, re.M)
    new_body = merged_body(body, by_id[tn], merged, reason)
    specmod.save(path, new_meta, new_body)
    if hash_line:
        path.write_text(re.sub(r"^spec_hash:.*$", lambda _m: hash_line.group(0), path.read_text(), count=1, flags=re.M))
    message = f"chore(plan): {sp.id} merge {tn} into {tm}\n\n{reason}\n\nPlan-Merge: {tn} into {tm}"
    core.run(["git", "-C", str(repo), "add", "--", rel])
    core.run(["git", "-C", str(repo), *core.git_identity(repo), "commit", "-s", "-q", "-m", message, "--", rel])
    sha = core.run(["git", "-C", str(repo), "rev-parse", "--short=7", "HEAD"]).stdout.strip()
    runs_agents.task_merge(runs.current(repo), repo, tn, tm, reason)
    deps = ", ".join(merged["depends_on"]) or "none"
    return [f"MERGED {tn} into {tm}: {reason}",
            f"  files: {', '.join(merged['files'])}; covers: {', '.join(merged['covers'])}; depends_on: {deps}",
            f"  dependants moved to {tm}: {', '.join(moved) or 'none'}",
            f"  committed {sha}"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat plan")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("merge", help="fold task tN into the later task tM that depends on it")
    p.add_argument("task")
    p.add_argument("into")
    p.add_argument("--spec")
    p.add_argument("--reason")
    p.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    print("\n".join(merge(Path(ns.repo).resolve(), ns.task, ns.into, ns.spec, ns.reason)))
    return 0
