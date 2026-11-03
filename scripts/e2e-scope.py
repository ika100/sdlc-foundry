#!/usr/bin/env python3
"""Does this change need the cluster e2e (spec 134, AC-134.2, AC-134.3)?

  e2e-scope.py [--base REF]   prints `run=true|false` (for $GITHUB_OUTPUT); one `trigger: <path>` line per reason on stderr
  e2e-scope.py --list         the scripts/cplat modules the e2e exercises, one per line

The cluster e2e (tests/e2e/run.sh, tests/e2e/cluster.sh) runs on a pull request only when the change touches what it exercises:
the gitops-app and cluster-gitops templates (not their copied .github/ files or Markdown), the templates' Dockerfiles, the e2e files,
shapes.yml, or a scripts/cplat module that the e2e scripts call or import, closed over every import. A release heading in the
changelog (the release pull request) always runs it. The module set is read from the code at HEAD, never from a list (ADR-080).
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
E2E_SCRIPTS = ("tests/e2e/run.sh", "tests/e2e/cluster.sh")
FILES = ("tests/e2e/run.sh", "tests/e2e/cluster.sh", ".github/workflows/e2e.yml", "scripts/e2e-scope.py", "shapes.yml")
TEMPLATES = ("templates/gitops-app/", "templates/cluster-gitops/")
CHANGELOG = "docs/CHANGELOG.md"
CALL = re.compile(r"\$cplat\s+([a-z][\w-]*)(?:\s+([a-z][\w-]*))?")
IMPORT = re.compile(r"^\s*(?:import\s+([\w, ]+)|from\s+(\w+)\s+import\b)", re.M)
HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.M)


def _units(cplat: Path) -> dict[str, Path]:
    """Every module (name -> file) and package (name -> __init__.py) of scripts/cplat."""
    units = {p.stem: p for p in cplat.glob("*.py")}
    units.update({p.name: p / "__init__.py" for p in cplat.iterdir() if (p / "__init__.py").is_file()})
    return units


def _tables(cplat_py: Path) -> tuple[dict, dict]:
    """NOUNS and PLUMBING of cplat.py, read as literals (cplat is not imported)."""
    found = {}
    for node in ast.parse(cplat_py.read_text()).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id in ("NOUNS", "PLUMBING") and node.value is not None:
            found[target.id] = ast.literal_eval(node.value)
    return found.get("NOUNS", {}), found.get("PLUMBING", {})


def _imports(path: Path, units: dict[str, Path]) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):      # module level and inside functions
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out & set(units)


def entry_points(root: Path) -> set[str]:
    """cplat, the modules the e2e scripts' `$cplat ...` calls resolve to, and the cplat modules their embedded Python imports."""
    cplat = root / "scripts" / "cplat"
    units = _units(cplat)
    nouns, plumbing = _tables(cplat / "cplat.py")
    out = {"cplat"}
    for rel in E2E_SCRIPTS:
        f = root / rel
        if not f.is_file():
            continue
        text = f.read_text()
        for noun, verb in CALL.findall(text):
            if noun in nouns and verb in nouns[noun]:
                out.add(nouns[noun][verb][0])
            elif noun in plumbing:
                out.add(plumbing[noun])
        for names, frm in IMPORT.findall(text):
            out |= {n.strip().split(".")[0] for n in (names.split(",") if names else [frm])}
    return out & set(units)


_CACHE: dict[tuple, set[str]] = {}


def exercised(root: Path) -> set[str]:
    """The entry points closed over every import (AC-134.3); remembered while no file it reads changes."""
    units = _units(root / "scripts" / "cplat")
    read = [root / rel for rel in E2E_SCRIPTS] + sorted(units.values())
    key = (str(root), *((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in read if p.is_file()))
    if key not in _CACHE:
        _CACHE[key] = _closure(root, units)
    return set(_CACHE[key])


def _closure(root: Path, units: dict[str, Path]) -> set[str]:
    seen: set[str] = set()
    todo = list(entry_points(root))
    while todo:
        m = todo.pop()
        if m not in seen:
            seen.add(m)
            todo += _imports(units[m], units) - seen
    return seen


def _cplat_trigger(rel: str, members: set[str], units: set[str]) -> bool:
    parts = rel.split("/")[2:]                                  # below scripts/cplat/
    if len(parts) == 1 and parts[0].endswith(".py"):
        return parts[0][:-3] in members
    if len(parts) > 1 and parts[0] in units:                    # a file of a package
        return parts[0] in members
    return True                                                 # data files, assets: the safe side


def _template_trigger(rel: str) -> bool:
    if rel.endswith(".jinja"):
        return True
    name = rel.rsplit("/", 1)[-1]
    under_github = "/.github/" in rel
    return not (under_github or name.lower().endswith(".md"))


def triggers(root: Path, files: list[str]) -> list[str]:
    """The changed paths that need the cluster e2e (AC-134.2)."""
    members: set[str] | None = None
    units = set(_units(root / "scripts" / "cplat"))
    out = []
    for rel in files:
        hit = rel in FILES or fnmatch.fnmatch(rel, "templates/*/Dockerfile*")
        if not hit and rel.startswith(TEMPLATES):
            hit = _template_trigger(rel)
        if not hit and rel.startswith("scripts/cplat/"):
            members = exercised(root) if members is None else members
            hit = _cplat_trigger(rel, members, units)
        if hit:
            out.append(rel)
    return out


def adds_release_heading(old: str, new: str) -> bool:
    return bool(_new_headings(old, new))


def _new_headings(old: str, new: str) -> list[str]:
    before = set(HEADING.findall(old))
    return [v for v in HEADING.findall(new) if v not in before]


def git(*args: str) -> str:
    p = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "git failed").strip().splitlines()[-1])
    return p.stdout


def default_base() -> str:
    try:
        return git("merge-base", "origin/main", "HEAD").strip()
    except RuntimeError:
        return "HEAD^"


def decide(base: str) -> tuple[bool, list[str]]:
    git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    files = git("diff", "--name-only", base, "HEAD").split()
    reasons = triggers(REPO, files)
    if CHANGELOG in files:
        old = git("show", f"{base}:{CHANGELOG}") if git("ls-tree", "--name-only", base, CHANGELOG).strip() else ""
        reasons += [f"release heading {v}" for v in _new_headings(old, git("show", f"HEAD:{CHANGELOG}"))]
    return bool(reasons), reasons


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", metavar="REF", help="compare HEAD with REF (default: the merge base with origin/main)")
    ap.add_argument("--list", action="store_true", help="print the exercised scripts/cplat modules")
    ns = ap.parse_args(argv)
    try:
        if ns.list:
            print("\n".join(sorted(exercised(REPO))))
            return 0
        run, reasons = decide(ns.base or default_base())
    except Exception as e:  # noqa: BLE001  (one readable line, never a traceback)
        print(f"ERROR: {e}")
        return 1
    for r in reasons:
        print(f"trigger: {r}", file=sys.stderr)
    print(f"run={'true' if run else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
