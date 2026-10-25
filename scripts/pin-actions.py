#!/usr/bin/env python3
"""Pin every GitHub Action in workflows to a full commit SHA (supply chain, ADR-019).

  pin-actions.py [PATH...]          rewrite `uses: owner/repo@v4` to `uses: owner/repo@<sha> # v4` (needs `gh`)
  pin-actions.py --check [PATH...]  exit 1 if any action is not pinned to a 40-character SHA, an action is pinned to
                                    different commits in different workflows (spec 055: the templates use the platform's
                                    pins), or a workflow has no top-level `permissions:` (offline; CI guard)

Default PATHs: .github templates scripts/cplat/assets. Dependabot's github-actions ecosystem keeps SHA pins up to date and understands the
`# vX` comment. Local (`./`) and `docker://` references are ignored.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

USES = re.compile(r"^(?P<head>\s*(?:-\s+)?uses:\s+)(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@(?P<ref>[^\s#]+)(?P<tail>.*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def workflow_files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        out += [f for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file() and "workflows" in f.parts and f.suffix in (".yml", ".yaml", ".jinja")]
    return sorted(out)


def resolve(action: str, ref: str, cache: dict[tuple[str, str], str]) -> str:
    repo = "/".join(action.split("/")[:2])
    if (repo, ref) not in cache:
        cache[(repo, ref)] = subprocess.run(["gh", "api", f"repos/{repo}/commits/{ref}", "-q", ".sha"], capture_output=True, text=True, check=True).stdout.strip()
    return cache[(repo, ref)]


def main(argv: list[str]) -> int:
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("--")] or [".github", "templates", "scripts/cplat/assets"]
    cache: dict[tuple[str, str], str] = {}
    unpinned = 0
    pins: dict[str, set[str]] = {}
    for f in workflow_files(paths):
        lines = f.read_text().splitlines(keepends=True)
        if check and not any(ln.startswith("permissions:") for ln in lines):
            print(f"{f}: no top-level `permissions:` (default token rights are too broad)", file=sys.stderr)
            unpinned += 1
        changed = False
        for i, line in enumerate(lines):
            m = USES.match(line.rstrip("\n"))
            if m and SHA.match(m["ref"]):
                pins.setdefault(m["action"], set()).add(m["ref"])
            if not m or m["action"].startswith(("./", "docker://")) or SHA.match(m["ref"]):
                continue
            unpinned += 1
            if check:
                print(f"{f}:{i + 1}: {m['action']}@{m['ref']} is not pinned to a commit SHA", file=sys.stderr)
                continue
            lines[i] = f"{m['head']}{m['action']}@{resolve(m['action'], m['ref'], cache)} # {m['ref']}\n"
            changed = True
        if changed:
            f.write_text("".join(lines))
    if check:
        for action, shas in sorted(pins.items()):
            if len(shas) > 1:
                print(f"{action} is pinned to {len(shas)} different commits ({', '.join(sorted(s[:7] for s in shas))}): use one pin everywhere", file=sys.stderr)
                unpinned += 1
        if unpinned:
            print(f"ERROR: {unpinned} finding(s): run `uv run scripts/pin-actions.py`", file=sys.stderr)
            return 1
        print("OK: all actions are pinned")
        return 0
    print(f"pinned {unpinned} reference(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
