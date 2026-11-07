"""`cplat spec mutate <id>`: how many small faults in the changed code the spec's acceptance tests catch (spec 152).

  cplat spec mutate <id> [--base REF] [--max N] [--write] [--json]

Report only, Python repos (service-python, library-python): every changed line of `src/**/*.py` since REF (default
origin/main) is a site for one mutation at a time (a comparison or boolean operator flipped, `not` dropped, a True/False or
number changed, a returned value replaced by None). For each mutant the tests that name the spec's criteria run once
(`devbox run test-fast -- <files> -x`); a failing run kills the mutant. The score and the surviving mutants are printed;
`--write` puts them under `## Mutation check (report only)` in the spec's verification.md. The exit code is 0 whatever
the score; only a broken setup (unknown spec, tests red before any mutation) exits 1. Files are always restored.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import spec as specmod
from core import PlatformError

SHAPES = ("service-python", "library-python")
MAX_MUTANTS = 20
TIMEOUT = 120
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


def run_tests(root: Path, files: list[str]) -> bool:   # tests replace this
    """True when the tests pass."""
    try:
        p = subprocess.run(["devbox", "run", "test-fast", "--", *files, "-x", "-q", "-p", "no:cacheprovider"], cwd=root,
                           capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return False                     # a mutant that hangs the tests is caught
    return p.returncode == 0


def mutate(root: Path, spec_id: str, base: str = "origin/main", limit: int = MAX_MUTANTS) -> dict:
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
    if not run_tests(root, tests):
        raise PlatformError(f"the acceptance tests of {spec.id} fail before any mutation", hint="make `devbox run test-fast` green first")
    for m in found:
        path = root / m.file
        original = path.read_text()
        try:
            path.write_text(_splice(original, m.start, m.end, m.text))
            m.killed = not run_tests(root, tests)
        finally:
            path.write_text(original)
    killed = sum(1 for m in found if m.killed)
    return {"spec": spec.id, "status": "done", "tests": tests, "mutants": len(found), "killed": killed,
            "score": round(killed / len(found), 2),
            "survivors": [f"{m.file}:{m.line} {m.what}" for m in found if not m.killed]}


def render(result: dict) -> str:
    if result["status"] != "done":
        return f"{HEADING}\n\nSkipped: {result['reason']}.\n"
    lines = [HEADING, "", f"{result['killed']} of {result['mutants']} mutants of the changed code were caught by the acceptance "
             f"tests ({int(result['score'] * 100)} %; spec 152, report only)."]
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
    p.add_argument("--write", action="store_true", help="put the result into the spec's verification.md")
    p.add_argument("--json", action="store_true")


def main(ns: argparse.Namespace, root: Path) -> int:
    result = mutate(root, ns.id, ns.base, ns.max)
    text = render(result)
    if ns.write:
        write(root, ns.id, text)
    print(json.dumps(result, indent=2) if ns.json else text, end="" if not ns.json else "\n")
    return 0
