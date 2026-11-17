#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Release check and gate (spec 121, AC-121.23, AC-121.24, AC-121.26).

  release-check.py rows [--base REF]              the CHANGELOG section that will be released (before the release: [Unreleased] plus the
                                                  fragments in docs/changelog.d, spec 132) lists every changed versions row since REF
                                                  (`cplat platform versions --diff REF --changelog`), a major move needs a major release, and no
                                                  section repeats a paragraph (#336)
  release-check.py needs-major [--base REF]       one line per change that needs a major release (the rule `rows` uses), nothing when none
  release-check.py from-tag previous|oldest       the tag each upgrade test starts from: `previous` the newest release before HEAD (the rule of
                                                  tests/e2e/upgrade.sh), `oldest` the newest vX.0.* of the candidate's major (`skipped: <reason>`
                                                  when there is none or it is the previous release; spec 191)
  release-check.py needs-upgrade-e2e [--base REF] prints `render=`, `drill=` and `run=` (last) `true|false` (for $GITHUB_OUTPUT): the render
                                                  check, the Postgres drill and the update part of the upgrade e2e (changed versions table, release
                                                  heading, template, renderer or the checks' own code)
  release-check.py gate SHA                       exit 0 only when SHA has a green check run of both the upgrade e2e and `upgrade render check`
                                                  (via `gh api`), each judged alone: on SHA, or on the head of SHA's pull request with the same
                                                  tree as SHA (#400: a squash merge of an up-to-date branch, so the run on the merge commit tests
                                                  nothing new)

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
try:
    import platrelease_changelog as fragments  # noqa: E402  (spec 132: docs/changelog.d)
    import versions  # noqa: E402  (scripts/cplat/versions.py)
except ModuleNotFoundError as e:   # a bare `python3` lacks pyyaml; uv reads the dependencies above (#295)
    sys.exit(f"ERROR: {e}: run it as `uv run scripts/release-check.py {' '.join(sys.argv[1:])}`")

CHANGELOG = "docs/CHANGELOG.md"
E2E_NAME = "e2e upgrade (previous release → candidate)"
RENDER_NAME = "upgrade render check"
E2E_PATHS =("tests/e2e/upgrade.sh", ".github/workflows/e2e-upgrade.yml", "scripts/cplat/update.py")
E2E_GLOBS = (re.compile(r"^scripts/cplat/upgrade[^/]*\.py$"), re.compile(r"^tests/e2e/lib/"))   # the probe helper (#323)
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


def repeated_paragraphs(text: str) -> list[str]:
    """`[section]: paragraph…` for every paragraph a section of the changelog repeats (a duplicated entry, e.g. from a merge
    conflict, #336). Headings are not paragraphs."""
    heads = list(HEADING.finditer(text))
    out = []
    for h, nxt in zip(heads, heads[1:] + [None]):
        seen: set[str] = set()
        for para in re.split(r"\n[ \t]*\n", text[h.end(): nxt.start() if nxt else len(text)]):
            p = para.strip()
            if not p or p.startswith("#"):
                continue
            if p in seen:
                first = p.splitlines()[0]
                out.append(f"[{h['name']}]: {first[:100]}{'…' if len(first) > 100 else ''}")
            seen.add(p)
    return out


def changes_since(base: str) -> list[dict]:
    old = versions.at_ref(base)
    new, _ = versions.current()
    return versions.diff(old, new)


def major_reasons(base: str, changes: list[dict]) -> list[str]:
    """The changes since BASE that need a major platform release (the one rule `rows` and the release command share)."""
    needing = [ln.removeprefix("- ") for c, ln in zip(changes, versions.diff_lines(changes, True))
               if (c["kind"] == "changed" and c["major"]) or c["kind"] in ("crds", "removed")]
    return needing + dropped_majors(base)


def cmd_needs_major(base: str) -> int:
    for reason in major_reasons(base, changes_since(base)):
        print(reason)
    return 0


def cmd_rows(base: str) -> int:
    changes = changes_since(base)
    text = changelog_text()
    label, version, body = released_section(text, base)
    if version is None:     # before the release, the fragments are unreleased content too (spec 132); an invalid one fails here
        found = fragments.read_fragments(REPO)
        if found:
            body, label = fragments.assemble(body, found), f"{label} and {fragments.FRAGMENTS}"
    errors = [f"ERROR: {CHANGELOG}: {where} repeats a paragraph" for where in repeated_paragraphs(text)]
    for c, line in zip(changes, versions.diff_lines(changes, True)):
        if c["kind"] != "crds" and line not in body:      # a removed CRD version is not a row: it only needs the major release
            errors.append(f"ERROR: {CHANGELOG}: {label} does not list {line}")
    base_v = vtuple(base)
    major_release = bool(version and base_v and vtuple(version)[0] > base_v[0])
    if not major_release:
        for change in major_reasons(base, changes):
            errors.append(f"ERROR: {change} needs a major platform release ({base} → {version or 'Unreleased'})")
    for e in errors:
        print(e)
    if errors:
        print(f"FAILED: {len(errors)} problem(s)")
        return 1
    print(f"OK: {len(changes)} changed row(s), all listed in {CHANGELOG} {label}")
    return 0


def has_versions(tag: str) -> bool:
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{tag}:scripts/cplat/versions.py"], capture_output=True).returncode == 0


def previous_tag() -> str | None:
    """The rule of tests/e2e/upgrade.sh step 1: the newest release tag merged into HEAD that has the versions table and does not point at
    HEAD; the newest v5.0.* while no tag has the table."""
    if not any(has_versions(t) for t in git("tag", "--list", "v*", "--sort=-v:refname").split()):
        return next(iter(git("tag", "--list", "v5.0.*", "--sort=-v:refname").split()), None)
    here = set(git("tag", "--points-at", "HEAD").split())
    merged = git("tag", "--merged", "HEAD", "--sort=-v:refname").split()
    return next((t for t in merged if has_versions(t) and t not in here), None)


def oldest_tag(previous: str | None) -> tuple[str | None, str]:
    """(tag, skip reason): the newest vX.0.* of the candidate's major (a release heading newer than PREVIOUS, else PREVIOUS's major)."""
    prev_v = vtuple(previous) if previous else None
    heads = [vtuple(h["name"]) for h in HEADING.finditer(changelog_text())]
    newer = [v for v in heads if v and (prev_v is None or v > prev_v)]
    major = max(newer)[0] if newer else (prev_v[0] if prev_v else None)
    if major is None:
        return None, "skipped: no vX.0.* release tag"
    found = [(vtuple(t), t) for t in git("tag", "--list", f"v{major}.0.*").split() if vtuple(t)]
    if not found:
        return None, f"skipped: no v{major}.0.* release tag"
    tag = max(found)[1]
    if tag == previous:
        return None, f"skipped: {tag} is the previous release"
    return tag, ""


def cmd_from_tag(which: str) -> int:
    previous = previous_tag()
    if which == "previous":
        if previous is None:
            print("ERROR: no previous release tag found (v5.0.*)")
            return 1
        print(previous)
        return 0
    tag, reason = oldest_tag(previous)
    print(tag or reason)
    return 0


RENDER_PATHS = ("scripts/cplat/update.py", "scripts/cplat/versions.py", "scripts/upgrade-render-check.py", "tests/e2e/lib/upgrade-system.sh",
                "scripts/release-check.py", ".github/workflows/e2e-upgrade.yml")
RENDER_PREFIXES = ("templates/gitops-app/",)
DRILL_PATHS = ("scripts/cplat/upgrade.py", "scripts/cplat/upgradeverify.py", "scripts/cplat/dbbackup.py", "scripts/cplat/backupstate.py",
               "tests/e2e/upgrade-drill.sh")
DATABASE_ROWS = ("operator cloudnative-pg", "operator plugin-barman-cloud")


def cmd_needs(base: str) -> int:
    files = set(git("diff", "--name-only", base, "HEAD").split())
    changes = changes_since(base)
    heading = False
    if CHANGELOG in files:
        old = {h["name"] for h in HEADING.finditer(changelog_text(base))}
        heading = any(h["name"] not in old and vtuple(h["name"]) for h in HEADING.finditer(changelog_text()))
    render = bool(changes) or heading or any(f in RENDER_PATHS or f.startswith(RENDER_PREFIXES) for f in files)
    drill = any(f in DRILL_PATHS for f in files) or any(
        str(c.get("name", "")).startswith("postgres ") or c.get("name") in DATABASE_ROWS for c in changes)
    run = bool(changes) or heading or any(f in E2E_PATHS or any(g.match(f) for g in E2E_GLOBS) for f in files)
    for key, value in (("render", render), ("drill", drill), ("run", run)):
        print(f"{key}={'true' if value else 'false'}")
    return 0


def gh(*args: str) -> str:
    """A read from GitHub; a dropped network is retried by core.run (spec 154, #557)."""
    import core
    p = core.run(["gh", *args], check=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "gh failed").strip())
    return p.stdout


def check_conclusion(repo: str, sha: str, name: str) -> str:
    runs = json.loads(gh("api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100")).get("check_runs", [])
    found = [r.get("conclusion") or "none" for r in runs if r.get("name") == name]
    return "success" if "success" in found else (found[-1] if found else "none")


def same_tree_heads(repo: str, sha: str) -> list[str]:
    """The heads of SHA's pull requests whose tree is SHA's tree (#400)."""
    def tree(commit: str) -> str:
        return json.loads(gh("api", f"repos/{repo}/commits/{commit}"))["commit"]["tree"]["sha"]
    heads = [p["head"]["sha"] for p in json.loads(gh("api", f"repos/{repo}/commits/{sha}/pulls"))]
    want = tree(sha) if heads else ""
    return [h for h in heads if h != sha and tree(h) == want]


def judge(repo: str, sha: str, name: str, label: str, heads: list[str] | None) -> tuple[bool, str, list[str]]:
    """(green, line, same-tree heads) for one required check: green on SHA, else on a same-tree head of its pull request."""
    conclusion = check_conclusion(repo, sha, name)
    if conclusion == "success":
        return True, f"OK: {sha} has a green {label}", heads or []
    if heads is None:
        try:
            heads = same_tree_heads(repo, sha)
        except (RuntimeError, ValueError, KeyError, TypeError) as e:
            print(f"WARNING: cannot read the pull requests of {sha}: {e}", file=sys.stderr)
            heads = []
    for head in heads:
        if check_conclusion(repo, head, name) == "success":
            return True, f"OK: {sha} has a green {label} on {head}, the head of its pull request with the same tree", heads
    return False, f"ERROR: {sha} has no green {label} ({conclusion}): do not tag it", heads


def cmd_gate(sha: str) -> int:
    lines: list[str] = []
    green = True
    heads: list[str] | None = None
    try:
        repo = os.environ.get("GITHUB_REPOSITORY") or json.loads(gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
        for name, label in ((E2E_NAME, "upgrade e2e"), (RENDER_NAME, "upgrade render check")):
            ok, line, heads = judge(repo, sha, name, label, heads)
            green &= ok
            lines.append(line)
    except (RuntimeError, ValueError, KeyError, TypeError) as e:   # #557: an unreadable answer is not a red one; say which it is
        print(f"ERROR: cannot read the check runs of {sha} ({e}): nothing was decided, run the gate again")
        return 1
    print("\n".join(lines))
    return 0 if green else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("rows", "needs-major", "needs-upgrade-e2e"):
        sub.add_parser(name).add_argument("--base", metavar="REF")
    sub.add_parser("from-tag").add_argument("which", choices=("previous", "oldest"))
    sub.add_parser("gate").add_argument("sha")
    ns = ap.parse_args(argv)
    try:
        if ns.cmd == "from-tag":
            return cmd_from_tag(ns.which)
        if ns.cmd == "gate":
            return cmd_gate(ns.sha)
        base = ns.base or default_base()
        if ns.cmd == "needs-major":
            return cmd_needs_major(base)
        return cmd_rows(base) if ns.cmd == "rows" else cmd_needs(base)
    except Exception as e:  # noqa: BLE001  (a readable one-line failure, never a traceback)
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
