"""cplat component build tests — the test command of one task, or of the build's load run (spec 172).

  cplat.py build tests <spec> <task> [--json] [--repo DIR]
  cplat.py build tests <spec> --load [--base REF] [--json] [--repo DIR]

Prints exactly one line: `cplat quiet test-fast -- <the task's test files>` in the shape's runner form, or for `--load`
`cplat quiet test-fast --repeat 3 -- <files>`; a load run with nothing to repeat prints `none: <reason>`.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path

import core
import spec as specmod
from core import PlatformError
from validate import matches

# shape -> (globs of the files test-fast runs, selection kind)
TEST_FAST: dict[str, tuple[list[str], str]] = {
    "platform": (["tests/cplat/**/test_*.py"], "paths"),
    "service-python": (["tests/**/test_*.py", "tests/**/*_test.py"], "paths"),
    "library-python": (["tests/**/test_*.py", "tests/**/*_test.py"], "paths"),
    "web-nextjs": (["tests/**/*.test.ts", "tests/**/*.test.tsx"], "paths"),
    "service-go": (["**/*_test.go"], "go"),
    "service-java": (["src/test/**/*Test.java", "src/test/**/Test*.java", "src/test/**/*Tests.java",
                      "src/test/**/*TestCase.java"], "java"),
}
GO_TEST = re.compile(r"^func (Test\w+)\(", re.M)


def _task_paths(root: Path, entries: list) -> set[str]:
    out: set[str] = set()
    for e in entries:
        e = str(e).strip().rstrip("/")
        if not e:
            continue
        if any(c in e for c in "*?["):
            out |= {str(p.relative_to(root)) for p in root.glob(e) if p.is_file()}
        elif (root / e).is_dir():
            out |= {str(p.relative_to(root)) for p in (root / e).rglob("*") if p.is_file()}
        else:
            out.add(e)
    return out


def _args(root: Path, kind: str, files: list[str]) -> list[str]:
    if kind == "paths":
        return list(files)
    if kind == "go":
        names: list[str] = []
        for f in files:
            p = root / f
            if p.is_file():
                names += [n for n in GO_TEST.findall(p.read_text(errors="ignore")) if n not in names]
        return ["-run", "^(" + "|".join(names) + ")$"] if names else []
    stems = sorted({Path(f).stem for f in files})
    return [f"-Dtest={','.join(stems)}", "-Dsurefire.failIfNoSpecifiedTests=false"] if stems else []


def _git(root: Path, *args: str) -> str:
    p = core.run(["git", "-C", str(root), *args], check=False)
    if p.returncode != 0:
        raise PlatformError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def build_tests(root: Path, ref: str, task: str | None, load: bool, base: str | None) -> dict:
    sp = specmod.find(root, ref)
    if load and task:
        raise PlatformError("a task and --load cannot be used together", hint="use one or the other")
    repo_shape = specmod.repo_shape(root)
    trace = specmod.trace(root, sp, specmod.test_globs(specmod.spec_shape(sp, repo_shape)))
    entry = TEST_FAST.get(repo_shape or "")
    doc: dict = {"spec": sp.id, "task": task, "load": load, "files": [], "args": [], "command": None, "reason": None}
    globs, kind = entry if entry else ([], "")

    if load:
        if not entry:
            doc["reason"] = f"{repo_shape} runs no test runner in test-fast"
        elif kind == "java":
            doc["reason"] = "service-java runs share target/, so they cannot run at once (ADR-094)"
        else:
            ref_base = base or _git(root, "merge-base", "main", "HEAD").strip()
            changed = {f for f in _git(root, "diff", "--name-only", f"{ref_base}..HEAD").splitlines()
                       if f and (root / f).is_file()}
            cands = {f for fs in trace.values() for f in fs} | changed
            doc["files"] = sorted(f for f in cands if matches(f, globs))
            if not doc["files"]:
                doc["reason"] = "no test files to repeat"
            else:
                doc["args"] = _args(root, kind, doc["files"])
                if not doc["args"]:
                    doc["reason"] = "no test files to repeat"
        if not doc["reason"]:
            doc["command"] = "cplat quiet test-fast --repeat 3 -- " + shlex.join(doc["args"])
        return doc

    if not task:
        raise PlatformError("name a task or pass --load", hint="cplat component build tests <spec> <task>")
    tasks = [t for t in (sp.plan[0].get("tasks") or []) if isinstance(t, dict)] if sp.plan else []
    t = next((t for t in tasks if t.get("id") == task), None)
    if t is None:
        raise PlatformError(f"{sp.id} has no task '{task}'", hint="cplat component build schedule " + sp.number)
    if t.get("repo"):
        raise PlatformError(f"task {task} is a gitops task (repo: {t['repo']}); it has no test command")
    cands = {f for ac in t.get("covers") or [] for f in trace.get(ac, [])} | _task_paths(root, t.get("files") or [])
    doc["files"] = sorted(f for f in cands if matches(f, globs))
    doc["args"] = _args(root, kind, doc["files"]) if entry else []
    doc["command"] = "cplat quiet test-fast" + (" -- " + shlex.join(doc["args"]) if doc["args"] else "")
    return doc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat component build tests", description=__doc__)
    ap.add_argument("spec")
    ap.add_argument("task", nargs="?")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--base")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    doc = build_tests(Path(ns.repo).resolve(), ns.spec, ns.task, ns.load, ns.base)
    print(json.dumps(doc) if ns.json else (doc["command"] or f"none: {doc['reason']}"))
    return 0
