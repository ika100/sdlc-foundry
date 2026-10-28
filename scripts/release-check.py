#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Release check and gate (spec 121, AC-121.23, AC-121.24, AC-121.26).

  release-check.py rows [--base REF]              the CHANGELOG section that will be released lists every changed versions row since REF
                                                  (`cplat platform versions --diff REF --changelog`), and a major move needs a major release
  release-check.py needs-upgrade-e2e [--base REF] prints `run=true|false` (for $GITHUB_OUTPUT): the change touches the versions table, adds a
                                                  release heading or touches the upgrade e2e or its code
  release-check.py gate SHA                       exit 0 only when SHA has a green check run of the upgrade e2e (via `gh api`)

REF defaults to the newest tag `v*` reachable from HEAD. This script never creates, moves or deletes a tag or a release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "cplat"))
import versions  # noqa: E402  (scripts/cplat/versions.py)

CHANGELOG = "docs/CHANGELOG.md"
E2E_NAME = "e2e upgrade (previous release → candidate)"
E2E_PATHS = ("tests/e2e/upgrade.sh", ".github/workflows/e2e-upgrade.yml", "scripts/cplat/update.py")
E2E_GLOBS = (re.compile(r"^scripts/cplat/upgrade[^/]*\.py$"),)
HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\]", re.M)


def git(*args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout).strip() else f"git {args[0]} failed")
    return p.stdout


def default_base() -> str:
    return git("describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD").strip()


def vtuple(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", v.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def changelog_text(ref: str | None = None) -> str:
    if ref is None:
        return (REPO / CHANGELOG).read_text()
    return git("show", f"{ref}:{CHANGELOG}", check=False)


def released_section(text: str, base: str) -> tuple[str, str | None, str]:
    """(label, version or None, body) of the section that will be released: the first heading newer than base, else [Unreleased]."""
    base_v = vtuple(base)
    heads = list(HEADING.finditer(text))
    chosen = None
    for h in heads:
        v = vtuple(h["name"])
        if v and base_v and v > base_v:
            chosen = h
            break
    if chosen is None:
        chosen = next((h for h in heads if h["name"].lower() == "unreleased"), None)
    if chosen is None:
        return "[Unreleased]", None, ""
    nxt = next((h for h in heads if h.start() > chosen.start()), None)
    body = text[chosen.end(): nxt.start() if nxt else len(text)]
    v = chosen["name"] if vtuple(chosen["name"]) else None
    return f"[{chosen['name']}]", v, body


def dropped_majors(base: str) -> list[str]:
    """`<engine> <major>` values in SUPPORTED_MAJORS / DEPRECATED_MAJORS at BASE that the current render.py no longer has."""
    out = []
    old_src = git("show", f"{base}:{versions.RENDER}", check=False)
    if not old_src:
        return out
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render_at_base.py"
        path.write_text(old_src)
        try:
            old = versions._load(path, "release_check_render_old")
        except Exception:  # noqa: BLE001  (unreadable old file: versions.at_ref reports it)
            return out
    new = versions._load(REPO / versions.RENDER, "release_check_render_new")
    for attr in ("SUPPORTED_MAJORS", "DEPRECATED_MAJORS"):
        for engine, majors in (getattr(old, attr, None) or {}).items():
            gone = [m for m in majors if m not in (getattr(new, attr, None) or {}).get(engine, ())]
            out += [f"{engine} {m} dropped from {attr}" for m in gone]
    return out


def changes_since(base: str) -> list[dict]:
    old = versions.at_ref(base)
    new, _ = versions.current()
    return versions.diff(old, new)


def cmd_rows(base: str) -> int:
    changes = changes_since(base)
    label, version, body = released_section(changelog_text(), base)
    errors = []
    for c, line in zip(changes, versions.diff_lines(changes, True)):
        if c["kind"] != "crds" and line not in body:      # a removed CRD version is not a row: it only needs the major release
            errors.append(f"ERROR: {CHANGELOG}: {label} does not list {line}")
    base_v = vtuple(base)
    major_release = bool(version and base_v and vtuple(version)[0] > base_v[0])
    if not major_release:
        needing = [ln.removeprefix("- ") for c, ln in zip(changes, versions.diff_lines(changes, True))
                   if (c["kind"] == "changed" and c["major"]) or c["kind"] in ("crds", "removed")]
        needing += dropped_majors(base)
        for change in needing:
            errors.append(f"ERROR: {change} needs a major platform release ({base} → {version or 'Unreleased'})")
    for e in errors:
        print(e)
    if errors:
        print(f"FAILED: {len(errors)} problem(s)")
        return 1
    print(f"OK: {len(changes)} changed row(s), all listed in {CHANGELOG} {label}")
    return 0


def cmd_needs(base: str) -> int:
    files = set(git("diff", "--name-only", base, "HEAD").split())
    run = bool(changes_since(base))
    run = run or any(f in E2E_PATHS or any(g.match(f) for g in E2E_GLOBS) for f in files)
    if not run and CHANGELOG in files:
        old = {h["name"] for h in HEADING.finditer(changelog_text(base))}
        run = any(h["name"] not in old and vtuple(h["name"]) for h in HEADING.finditer(changelog_text()))
    print(f"run={'true' if run else 'false'}")
    return 0


def gh(*args: str) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "gh failed").strip())
    return p.stdout


def cmd_gate(sha: str) -> int:
    conclusion = "none"
    try:
        repo = os.environ.get("GITHUB_REPOSITORY") or json.loads(gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
        runs = json.loads(gh("api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100")).get("check_runs", [])
        found = [r.get("conclusion") or "none" for r in runs if r.get("name") == E2E_NAME]
        conclusion = "success" if "success" in found else (found[-1] if found else "none")
    except (RuntimeError, ValueError, KeyError) as e:
        print(f"WARNING: cannot read the check runs of {sha}: {e}", file=sys.stderr)
    if conclusion == "success":
        print(f"OK: {sha} has a green upgrade e2e")
        return 0
    print(f"ERROR: {sha} has no green upgrade e2e ({conclusion}): do not tag it")
    return 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("rows", "needs-upgrade-e2e"):
        sub.add_parser(name).add_argument("--base", metavar="REF")
    sub.add_parser("gate").add_argument("sha")
    ns = ap.parse_args(argv)
    try:
        if ns.cmd == "gate":
            return cmd_gate(ns.sha)
        base = ns.base or default_base()
        return cmd_rows(base) if ns.cmd == "rows" else cmd_needs(base)
    except Exception as e:  # noqa: BLE001  (a readable one-line failure, never a traceback)
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
