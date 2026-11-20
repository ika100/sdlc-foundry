"""`cplat spec mutate <id>`: how many small faults in the changed code the spec's acceptance tests catch (spec 152).

  cplat spec mutate <id> [--base REF] [--max N] [--budget SECONDS] [--write] [--json]

Report only, Python repos (service-python, library-python): every changed line of `src/**/*.py` since REF (default
origin/main) is a site for one mutation at a time (a comparison or boolean operator flipped, `not` dropped, a True/False or
number changed, a returned value replaced by None). For each mutant the tests that name the spec's criteria run once
(`devbox run test-fast -- <files> -x`); a failing run kills the mutant. The score and the surviving mutants are printed;
`--write` puts them under `## Mutation check (report only)` in the spec's verification.md. The exit code is 0 whatever
the score; only a broken setup (unknown spec, tests red before any mutation) exits 1. Files are always restored.

The whole check keeps to a wall-clock budget (default 90 s, `--budget`, #868): the baseline run and every mutant run count, a
run never outlasts what is left, and when the budget runs out the check stops and reports a partial score over the mutants it
tested ("5 of 20 mutants tested in 90 s (time budget)"). Mutants run one after another, not in parallel copies of the tree: a
copy needs its own devbox environment and venv (the devbox init hook runs `uv sync`), and suites backed by a shared service
(a local Postgres) would see each other's data, so parallel runs could kill or spare mutants by accident.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import spec as specmod
from core import PlatformError, repo_env

SHAPES = ("service-python", "library-python")
MAX_MUTANTS = 20
TIMEOUT = 120
BUDGET = 90                          # seconds of wall clock for the whole check (#868)
MIN_RUN = 5                          # do not start a run with less time than this left
HEADING = "## Mutation check (report only)"
_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
         ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}


@dataclass
class Mutant:
    file: str
    line: int
    what: str
    start: tuple[int, int]
    end: tuple[int, int]
    text: str
    killed: bool | None = None


def changed_lines(root: Path, base: str) -> dict[str, set[int]]:
    """`src/**/*.py` file → the line numbers added or changed since base."""
    out = subprocess.run(["git", "diff", "-U0", f"{base}...HEAD", "--", "src"], cwd=root, text=True, capture_output=True,
                         check=False).stdout
    lines: dict[str, set[int]] = {}
    current = None
    for ln in out.splitlines():
        if ln.startswith("+++ "):
            path = ln[6:] if ln.startswith("+++ b/") else None
            current = path if path and path.endswith(".py") else None
        elif current and (m := re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", ln)):
            start, count = int(m.group(1)), int(m.group(2) or 1)
            lines.setdefault(current, set()).update(range(start, start + count))
    return {f: ls for f, ls in lines.items() if ls}


def _mutations(node: ast.AST):
    """(description, mutated copy) for one node."""
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _SWAP:
        m = copy.deepcopy(node)
        m.ops = [_SWAP[type(node.ops[0])]()]
        yield f"{type(node.ops[0]).__name__} → {type(m.ops[0]).__name__}", m
    elif isinstance(node, ast.BoolOp):
        m = copy.deepcopy(node)
        m.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        yield f"{type(node.op).__name__.lower()} → {type(m.op).__name__.lower()}", m
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        yield "not dropped", copy.deepcopy(node.operand)
    elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
        yield f"{node.value} → {not node.value}", ast.Constant(not node.value)
    elif isinstance(node, ast.Constant) and type(node.value) is int:
        yield f"{node.value} → {node.value + 1}", ast.Constant(node.value + 1)
    elif isinstance(node, ast.Return) and node.value is not None and not (isinstance(node.value, ast.Constant) and node.value.value is None):
        yield "return value → None", ast.Return(value=ast.Constant(None))


def mutants(root: Path, lines: dict[str, set[int]], limit: int) -> list[Mutant]:
    found: list[Mutant] = []
    for rel in sorted(lines):
        try:
            tree = ast.parse((root / rel).read_text())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if getattr(node, "lineno", None) not in lines[rel] or getattr(node, "end_lineno", None) is None:
                continue
            for what, m in _mutations(node):
                text = ast.unparse(m)
                found.append(Mutant(rel, node.lineno, what, (node.lineno, node.col_offset), (node.end_lineno, node.end_col_offset),
                                    text if not isinstance(node, ast.expr) else f"({text})"))
    # spread over the files and lines: every k-th site when there are more than `limit`
    if len(found) > limit:
        step = len(found) / limit
        found = [found[int(i * step)] for i in range(limit)]
    return found


def _splice(source: str, start: tuple[int, int], end: tuple[int, int], text: str) -> str:
    lines = source.splitlines(keepends=True)
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln.encode()))
    raw = source.encode()
    a = offs[start[0] - 1] + start[1]
    b = offs[end[0] - 1] + end[1]
    return (raw[:a] + text.encode() + raw[b:]).decode()


def run_tests(root: Path, files: list[str], timeout: float = TIMEOUT) -> bool | None:   # tests replace this
    """True when the tests pass, False when they fail, None when they ran out of `timeout`."""
    try:
        p = subprocess.run(["devbox", "run", "test-fast", "--", *files, "-x", "-q", "-p", "no:cacheprovider"], cwd=root,
                           capture_output=True, text=True, timeout=timeout, check=False, env=repo_env())
    except subprocess.TimeoutExpired:
        return None
    return p.returncode == 0


clock = time.monotonic                   # tests replace this


def mutate(root: Path, spec_id: str, base: str = "origin/main", limit: int = MAX_MUTANTS, budget: float = BUDGET) -> dict:
    spec = specmod.find(root, spec_id)
    shape = specmod.spec_shape(spec, specmod.repo_shape(root))
    if shape not in SHAPES:
        return {"spec": spec.id, "status": "skipped", "reason": f"no mutation check for shape {shape or 'unknown'} yet"}
    tests = sorted({f for fs in specmod.trace(root, spec, specmod.test_globs(shape)).values() for f in fs})
    if not tests:
        return {"spec": spec.id, "status": "skipped", "reason": "no test names a criterion of the spec"}
    lines = changed_lines(root, base)
    found = mutants(root, lines, limit)
    if not found:
        return {"spec": spec.id, "status": "skipped", "reason": "no changed source line to mutate"}
    start = clock()
    deadline = start + budget
    baseline = run_tests(root, tests, timeout=max(min(TIMEOUT, budget), MIN_RUN))
    if baseline is False or (baseline is None and budget >= TIMEOUT):
        raise PlatformError(f"the acceptance tests of {spec.id} fail before any mutation", hint="make `devbox run test-fast` green first")
    for m in found if baseline else []:
        left = deadline - clock()
        if left < MIN_RUN:
            break
        path = root / m.file
        original = path.read_text()
        try:
            path.write_text(_splice(original, m.start, m.end, m.text))
            timeout = min(TIMEOUT, left)
            passed = run_tests(root, tests, timeout=timeout)
        finally:
            path.write_text(original)
        if passed is None and timeout < TIMEOUT:
            break                        # cut off by the budget, not hung: not tested
        m.killed = passed is not True    # a mutant that hangs the tests for the full TIMEOUT is caught
    tested = [m for m in found if m.killed is not None]
    killed = sum(1 for m in tested if m.killed)
    return {"spec": spec.id, "status": "done", "tests": tests, "mutants": len(found), "tested": len(tested), "killed": killed,
            "score": round(killed / len(tested), 2) if tested else None, "seconds": round(clock() - start),
            "budget": round(budget), "budget_hit": len(tested) < len(found),
            "survivors": [f"{m.file}:{m.line} {m.what}" for m in tested if not m.killed]}


def render(result: dict) -> str:
    if result["status"] != "done":
        return f"{HEADING}\n\nSkipped: {result['reason']}.\n"
    tested = result.get("tested", result["mutants"])
    lines = [HEADING, ""]
    if result.get("budget_hit"):
        lines += [f"{tested} of {result['mutants']} mutants tested in {result['seconds']} s (time budget of {result['budget']} s, "
                  "`--budget`); the score covers the tested ones.", ""]
    if tested:
        lines.append(f"{result['killed']} of {tested} mutants of the changed code were caught by the acceptance "
                     f"tests ({int(result['score'] * 100)} %; spec 152, report only).")
    else:
        lines.append("No mutant was tested: the acceptance tests alone used the time budget (spec 152, report only).")
    if result["survivors"]:
        lines += ["", "Survived (a test that names the criterion would fail if it checked this):"]
        lines += [f"- `{s}`" for s in result["survivors"]]
    return "\n".join(lines) + "\n"


def write(root: Path, spec_id: str, text: str) -> Path:
    path = specmod.find(root, spec_id).dir / "verification.md"
    old = path.read_text() if path.is_file() else ""
    if HEADING in old:
        old = old[:old.index(HEADING)].rstrip("\n") + "\n"
    path.write_text((old.rstrip("\n") + "\n\n" if old.strip() else "") + text)
    return path


def add_parser(sub) -> None:
    p = sub.add_parser("mutate", help="report how many faults in the changed code the acceptance tests catch (spec 152)")
    p.add_argument("id")
    p.add_argument("--base", default="origin/main")
    p.add_argument("--max", type=int, default=MAX_MUTANTS)
    p.add_argument("--budget", type=float, default=BUDGET, metavar="SECONDS",
                   help=f"wall-clock budget for the whole check; stops early with a partial score (default {BUDGET})")
    p.add_argument("--write", action="store_true", help="put the result into the spec's verification.md")
    p.add_argument("--json", action="store_true")


def main(ns: argparse.Namespace, root: Path) -> int:
    result = mutate(root, ns.id, ns.base, ns.max, ns.budget)
    text = render(result)
    if ns.write:
        write(root, ns.id, text)
    print(json.dumps(result, indent=2) if ns.json else text, end="" if not ns.json else "\n")
    return 0
