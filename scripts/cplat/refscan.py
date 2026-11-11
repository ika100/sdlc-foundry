"""Shared reading of git refs and open PRs for numbers that must not clash across parallel branches (ADR/spec numbers).

No fetch and no other network call: the refs are those of the last fetch; only `gh pr list` asks GitHub.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return p.stdout if p.returncode == 0 else ""


def base(root: Path) -> str | None:
    """`origin/main`, else `main`, else None."""
    for ref in ("origin/main", "main"):
        if _git(root, "rev-parse", "--verify", "--quiet", ref).strip():
            return ref
    return None


def entries_at(root: Path, ref: str, directory: str) -> list[str]:
    """The entry names of `directory` at `ref` (empty when it does not exist there)."""
    return _git(root, "ls-tree", "--name-only", f"{ref}:{directory}").splitlines()


def other_branches(root: Path, directory: str) -> dict[str, list[str]]:
    """Entries of `directory` on every pushed branch except main and the branch checked out here."""
    current = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    refs = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").split()
    skip = {"origin/main", "origin/HEAD", "origin", f"origin/{current}"}
    return {ref: entries_at(root, ref, directory) for ref in refs if ref not in skip}


def open_pr_paths(root: Path) -> dict[str, list[str]] | None:
    """File paths of each open PR by `#<n>`, without the current branch's PR; None when the PRs cannot be read."""
    try:
        p = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "100", "--json", "number,headRefName,files"],
                           cwd=root, capture_output=True, text=True, timeout=60, check=False)
        if p.returncode != 0:
            return None
        rows = json.loads(p.stdout)
        current = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        return {f"#{r['number']}": [f["path"] for f in r.get("files") or [] if f.get("path")]
                for r in rows if r.get("headRefName") != current}
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, AttributeError):
        return None
