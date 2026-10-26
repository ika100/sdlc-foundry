"""`quicktask`: the rule check behind the inline path of /svc:quick-task (spec 111).

  cplat quick-task inline-check [--base REF]    exit 0: the coordinator may make the change itself; exit 1: use the agents

Allowed: at most one non-test source file and one test file (the shape's `test_globs`), at most 60 added + removed
lines (committed since the merge base with REF, uncommitted and untracked), and no mandatory-validation file
(manifests, lock files, Dockerfiles, CI workflows, specs: validate.MANDATORY), `.claude/**` or `.platform-settings.yml`.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import validate
from core import PlatformError

MAX_LINES = 60
PROTECTED = {"claude": [".claude/**"], "settings": [".platform-settings.yml"],
             "spec": ["docs/specs/**"]}


def _changes(root: Path, base: str) -> dict[str, int]:
    """path -> added + removed lines, against the merge base (committed, working tree and untracked files)."""
    code, mb = validate._git(root, "merge-base", base, "HEAD")
    if code != 0 or not mb.strip():
        raise PlatformError(f"cannot compare with '{base}'", hint="pass an existing ref with --base")
    code, text = validate._git(root, "diff", "--numstat", "--no-renames", mb.strip())
    if code != 0:
        raise PlatformError("git diff failed", hint="run it inside a git repository")
    out: dict[str, int] = {}
    for ln in text.splitlines():
        added, removed, path = ln.split("\t", 2)
        out[path] = (int(added) + int(removed)) if added.isdigit() and removed.isdigit() else 0
    code, text = validate._git(root, "ls-files", "-o", "--exclude-standard")
    for path in (text.splitlines() if code == 0 else []):
        try:
            out[path] = len((root / path).read_text(errors="replace").splitlines())
        except OSError:
            out[path] = 0
    return out


def check(root: Path, base: str) -> tuple[bool, str]:
    changes = _changes(root, base)
    shape = validate.shape_entry(root)
    files = sorted(changes)
    for f in files:
        for name, globs in PROTECTED.items():
            if validate.matches(f, globs):
                return False, f"{f} is a protected file ({name})"
    for cat, hit in validate.mandatory_categories(root, files, shape).items():
        if cat != "acceptance-test":
            return False, f"{hit[0]} is a {cat} file (mandatory validation)"
    tests = [f for f in files if validate._is_test(f, shape)]
    sources = [f for f in files if f not in tests]
    if len(sources) > 1:
        return False, f"{len(sources)} source files changed (at most 1)"
    if len(tests) > 1:
        return False, f"{len(tests)} test files changed (at most 1)"
    lines = sum(changes.values())
    if lines > MAX_LINES:
        return False, f"{lines} changed lines (at most {MAX_LINES})"
    return True, f"{len(files)} files, {lines} lines"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat quick-task", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inline-check")
    p.add_argument("--base", default=None, help="the branch the work started from (default: origin/main, else main)")
    ns = ap.parse_args(argv)
    root = validate.toplevel()
    ok, text = check(root, ns.base or validate.default_base(root))
    print(f"inline: allowed ({text})" if ok else f"inline: refused — {text}")
    return 0 if ok else 1
