#!/usr/bin/env python3
"""Spec 212: which cplat test files a local run of `devbox run test-fast` runs, read from a recorded dependency map.

  python3 scripts/testselect.py args [--full]   the pytest arguments that make `pytest tests/cplat` run the selection:
                                                `--deps-record <map to record>` (every test) or `--deps-select=<files>`
                                                (comma-separated, possibly none); the reason on stderr

A full run records the map (`tests/cplat/depsmap.py`); the maps live in the clone's git common directory, shared by its
worktrees. The rules are in docs/specs/212-*/design.md. Standard library only: it runs before uv builds the test env.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "cplat"))

import depstrace  # noqa: E402

VERSION = 1
TESTS = "tests/cplat"
STORE = "sdlc-test-deps"
FULL_HINT = "devbox run test-fast --full runs every test"
# changed, they can change any test's result: the suite's setup and the selection itself (AC-212.3)
SHARED_FIXED = ("tests/cplat/conftest.py", "tests/cplat/pytest.ini", "requirements-test.txt", "scripts/testselect.py",
                "scripts/cplat/depstrace.py", "tests/cplat/depsmap.py")
CODE_SUFFIXES = frozenset({".py", ".sh", ".jinja", ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg"})


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def store_dir(root: Path) -> Path:
    common = Path(_git(root, "rev-parse", "--git-common-dir").strip())
    return (common if common.is_absolute() else root / common) / STORE


def test_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in (root / TESTS).glob("test_*.py"))


def is_test(path: str) -> bool:
    return path.startswith(TESTS + "/test_") and path.endswith(".py") and "/" not in path[len(TESTS) + 1:]


def code_like(path: str) -> bool:
    suffix = Path(path).suffix
    return suffix in CODE_SUFFIXES or suffix == ""


def shared_files(root: Path) -> set[str]:
    """The suite's shared files: the fixed ones plus what conftest.py imports at module level (its plugins too)."""
    return set(SHARED_FIXED) | depstrace.Imports(root).closure(["tests/cplat/conftest.py"])


def load_maps(root: Path) -> list[dict]:
    maps = []
    store = store_dir(root)
    for f in sorted(store.glob("*.json")) if store.is_dir() else []:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("tests"), dict):
            continue
        commit = str(data.get("commit") or "")
        if not commit or subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=root,
                                        capture_output=True).returncode:
            continue   # the clone does not have the map's commit
        data["path"] = str(f)
        maps.append(data)
    return maps


def changed_files(root: Path, m: dict) -> set[str]:
    """What differs between the map's tree and the working tree (AC-212.6)."""
    diff = _git(root, "diff", "--name-only", "--no-renames", m["commit"]).split("\n")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").split("\n")
    return {f for f in [*diff, *untracked, *m.get("dirty", [])] if f}


class Index:
    def __init__(self, tests: dict):
        self.by_file: dict[str, set[str]] = {}
        self.by_dir: dict[str, set[str]] = {}
        self.trees: list[tuple[str, str]] = []
        for test, deps in tests.items():
            for f in deps.get("files", ()):
                self.by_file.setdefault(f, set()).add(test)
            for d in deps.get("dirs", ()):
                self.by_dir.setdefault(d, set()).add(test)
            for t in deps.get("trees", ()):
                self.trees.append((t, test))

    def tests_of(self, path: str) -> set[str]:
        hit = set(self.by_file.get(path, ()))
        hit |= self.by_dir.get(os.path.dirname(path) or ".", set())
        hit |= {test for t, test in self.trees if t == "." or path == t or path.startswith(t + "/")}
        return hit


def _short(commit: str) -> str:
    return commit[:9]


def plan(root: Path = ROOT, full: bool = False) -> dict:
    """{"mode": full|select|none, "reason", "tests", "total", "record" (full only), "map" (its commit, if one was used)}."""
    tests_now = test_files(root)
    total = len(tests_now)
    record = str(store_dir(root) / f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}.json")

    def run_full(reason: str, used: dict | None = None) -> dict:
        return {"mode": "full", "reason": reason, "tests": tests_now, "total": total, "record": record,
                "map": used and used["commit"]}

    if full:
        return run_full("--full given")
    maps = load_maps(root)
    if not maps:
        return run_full("no dependency map yet")
    newest_first = sorted(maps, key=lambda m: str(m.get("recorded", "")), reverse=True)
    changed, m = min(((changed_files(root, m), m) for m in newest_first), key=lambda cm: len(cm[0]))   # ties: the newest
    shared = sorted(changed & shared_files(root))
    if shared:
        return run_full(f"{shared[0]} is shared by every test", m)
    index = Index(m["tests"])
    selected: set[str] = set()
    for f in sorted(changed):
        if is_test(f):
            if f in tests_now:
                selected.add(f)
            continue
        hit = index.tests_of(f)
        if hit:
            selected |= hit
        elif code_like(f) and (root / f).exists():
            return run_full(f"{f} is code or configuration no test of the map reads", m)
    selected |= {t for t in tests_now if t not in m["tests"]}            # new since the map
    selected |= set(m.get("failed", ())) & set(tests_now)               # red in the recorded run
    selected &= set(tests_now)
    where = f"map at {_short(m['commit'])}, {len(changed)} changed file(s)"
    if len(selected) * 2 > total:
        return run_full(f"the change reaches {len(selected)} of {total} test files ({where})", m)
    if not selected:
        return {"mode": "none", "reason": f"no test file can see this change ({where})", "tests": [], "total": total,
                "map": m["commit"]}
    return {"mode": "select", "reason": where, "tests": sorted(selected), "total": total, "map": m["commit"]}


def message(p: dict) -> str:
    if p["mode"] == "full":
        return f"test-fast: all {p['total']} test files: {p['reason']}; this run records a new dependency map"
    if p["mode"] == "none":
        return f"test-fast: 0 of {p['total']} test files: {p['reason']}; {FULL_HINT}"
    return f"test-fast: {len(p['tests'])} of {p['total']} test files ({p['reason']}); {FULL_HINT}"


def pytest_args(p: dict) -> list[str]:
    if p["mode"] == "full":
        return ["--deps-record", p["record"]]
    return ["--deps-select=" + ",".join(p["tests"])]


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "args" or any(a != "--full" for a in argv[1:]):
        print("usage: python3 scripts/testselect.py args [--full]", file=sys.stderr)
        return 2
    p = plan(ROOT, full="--full" in argv[1:])
    print(message(p), file=sys.stderr)
    print(" ".join(pytest_args(p)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
