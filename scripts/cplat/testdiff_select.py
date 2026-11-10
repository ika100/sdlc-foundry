"""Spec 172: the files `cplat spec test-diff` judges are the ones the red-tests step committed (design, section 1)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def red_commits(root: Path, spec) -> list[str]:
    """Non-merge commits reachable from HEAD, oldest first, whose subject has `acceptance tests for` and names the spec."""
    number = re.escape(spec.number)
    names = re.compile(rf"AC-{number}\.|(?<![\w.]){number}(?![\w])|{re.escape(spec.id)}")
    out = _git(root, "log", "--no-merges", "--reverse", "--format=%H%x09%s", "HEAD").stdout
    found = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\t")
        if "acceptance tests for" in subject and names.search(subject):
            found.append(sha)
    return found


def in_range(root: Path, given: str, sha: str) -> bool:
    """`sha` is the given base or a descendant of it, and an ancestor of HEAD."""
    def ancestor(a: str, b: str) -> bool:
        return _git(root, "merge-base", "--is-ancestor", a, b).returncode == 0
    return ancestor(given, sha) and ancestor(sha, "HEAD")


def frozen_files(root: Path, given: str, frozen: str, building: list) -> set[str] | None:
    """The test files the red-tests commits of the `building` specs froze; None means fallback (no red-tests commit in range)."""
    import spec as sp
    reds = {s.id: red_commits(root, s) for s in building}
    if not any(in_range(root, given, c) for cs in reds.values() for c in cs):
        return None
    ids = {a.id for s in building for a in s.acs()}
    globs = sp.test_globs(sp.repo_shape(root))
    pats = [_glob_re(g) for g in globs]
    paths: set[str] = set()
    for cs in reds.values():
        if not cs:
            continue
        first = cs[0]
        args = ["log", "--no-merges", "--format=", "--name-only", frozen]
        if _git(root, "rev-parse", "--verify", "-q", f"{first}^").returncode == 0:
            args.append(f"^{first}^")
        paths |= set(_git(root, *args).stdout.split())
    keep = set()
    for f in paths:
        if (not any(p.match(f) for p in pats) or f.startswith("docs/") or f.endswith(".md") or sp._ignored(Path(f))):
            continue
        text = _git(root, "show", f"{frozen}:{f}")
        if text.returncode == 0 and set(sp.AC_ANY.findall(text.stdout)) & ids:
            keep.add(f)
    return keep


def _glob_re(glob: str) -> re.Pattern:
    """`Path.glob` semantics as a regex on a repo-relative path: `**/` spans directories, `*` and `?` stay in one."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        else:
            c = glob[i]
            out += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
            i += 1
    return re.compile(out + r"\Z")
