#!/usr/bin/env python3
"""Fail on every real sleep in tests/cplat (spec 178): a test waits for an event or a file, or uses the fake clock.

A sleep inside a string literal (a fake program standing in for a slow process) is allowed on a line carrying
`fake-delay: <reason>`. tests/cplat/waiting.py, the helper that polls, is exempt; the FIXTURE_FILES are exempt
only for sleep text inside string literals, a real sleep call in them is still flagged.

Usage: check-test-sleeps.py [--root DIR]
"""
import argparse
import ast
import re
import sys
from pathlib import Path

HINT = ('waits a fixed time: wait for an event or a file (waiting.wait_for, waiting.wait_file) or use the fake clock; '
        'a fake program marks its delay "fake-delay: <reason>"')
SLEEP_MODULES = {"time", "asyncio"}
TEXT_SLEEP = re.compile(r"""\b(?:time|asyncio)\.sleep\(|(?:^|[;|]|&&)\s*sleep\s+[\w$"'{]""")
# Tests whose string literals hold sleeps as sample input for a detector (never run as sleeps): this check's own tests and the
# polling-loop detector of spec 143 over documentation text.
FIXTURE_FILES = {"test_178_sleeps_check.py", "test_143_waits_docs.py"}
MARKER = re.compile(r"fake-delay:\s*\S")


def code_sleeps(tree: ast.AST) -> list[tuple[int, str]]:
    modules: set[str] = set()   # names bound to the time or asyncio module
    funcs: set[str] = set()     # names bound to their sleep
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update((a.asname or a.name) for a in node.names if a.name in SLEEP_MODULES)
        elif isinstance(node, ast.ImportFrom) and node.module in SLEEP_MODULES:
            funcs.update((a.asname or a.name) for a in node.names if a.name == "sleep")
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "sleep" and isinstance(f.value, ast.Name) and f.value.id in modules | SLEEP_MODULES:
            found.append((node.lineno, f"{f.value.id}.sleep(...)"))
        elif isinstance(f, ast.Name) and f.id in funcs:
            found.append((node.lineno, f"{f.id}(...)"))
    return found


def text_sleeps(tree: ast.AST) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for offset, line in enumerate(node.value.split("\n")):
                m = TEXT_SLEEP.search(line)
                if m and not MARKER.search(line):
                    found.append((node.lineno + offset, m.group(0).strip(" ;|&") + "..."))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    root = Path(ap.parse_args().root)
    base = root / "tests" / "cplat"
    lines = []
    for path in sorted(base.rglob("*.py")):
        if path == base / "waiting.py":
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        rel = path.relative_to(root).as_posix()
        found = code_sleeps(tree) + ([] if path.name in FIXTURE_FILES else text_sleeps(tree))
        for lineno, text in sorted(set(found)):
            lines.append(f"{rel}:{lineno}: {text} {HINT}")
    if lines:
        print("\n".join(lines))
        print(f"check-test-sleeps: {len(lines)} fixed sleep(s) in tests/cplat")
        return 1
    print("OK: no fixed sleeps in tests/cplat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
