"""A test that globs docs/changelog.d must also read docs/CHANGELOG.md (issue #1071).

The release moves every fragment into docs/CHANGELOG.md, so a test that finds its entry in the fragments alone breaks at the
release. `changelog_entry` (tests/cplat/changelog_support.py) searches both; a test that reads `CHANGELOG.md` itself passes too.
"""
from __future__ import annotations

import ast
from pathlib import Path

MESSAGE = ("a test globs docs/changelog.d but never reads docs/CHANGELOG.md, so the release breaks it: "
           "use changelog_entry (tests/cplat/changelog_support.py)")
_LISTING = {"glob", "rglob", "iterdir"}


def _text(node: ast.AST, source: str) -> str:
    return ast.get_source_segment(source, node) or ""


def _problems(func: ast.AST, source: str) -> list[int]:
    names = {t.id for n in ast.walk(func) if isinstance(n, ast.Assign) and "changelog.d" in _text(n.value, source)
             for t in n.targets if isinstance(t, ast.Name)}
    lines = []
    for n in ast.walk(func):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _LISTING:
            recv = n.func.value
            if "changelog.d" in _text(recv, source) or (isinstance(recv, ast.Name) and recv.id in names):
                lines.append(n.lineno)
    if not lines:
        return []
    reads = any(isinstance(n, ast.Constant) and isinstance(n.value, str) and "CHANGELOG.md" in n.value for n in ast.walk(func))
    uses_helper = any(isinstance(n, ast.Name) and n.id == "changelog_entry" for n in ast.walk(func))
    return [] if reads or uses_helper else lines[:1]


def scan(root: Path) -> list[tuple[str, int, str]]:
    """(file, line, message) per test function that lists docs/changelog.d and never reads docs/CHANGELOG.md."""
    root = Path(root)
    tests = root / "tests"
    found = []
    for path in sorted(tests.rglob("*.py")) if tests.is_dir() else []:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                found += [(rel, line, MESSAGE) for line in _problems(node, source)]
    return found
