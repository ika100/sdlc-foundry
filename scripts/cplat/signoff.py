"""Sign-off checks for a branch about to be merged into the platform repo (spec 172, AC-172.7)."""
from __future__ import annotations

from pathlib import Path

import core
import house_rules


def _git(repo: Path, *args: str) -> str:
    return core.run(["git", "-C", str(repo), *args], check=False).stdout


def unsigned(repo: Path, rev_range: str) -> list[tuple[str, str]]:
    """(short sha, subject) of every commit in `rev_range`, merge commits included, without a Signed-off-by line."""
    found: list[tuple[str, str]] = []
    for rec in _git(repo, "log", "--format=%h%x00%s%x00%B%x1e", rev_range).split("\x1e"):
        if not rec.strip():
            continue
        sha, _, rest = rec.lstrip("\n").partition("\x00")
        subject, _, body = rest.partition("\x00")
        if not house_rules.SIGNED.search(body):
            found.append((sha, subject))
    return found


def worktree_of(repo: Path, branch: str) -> Path | None:
    """The worktree that has `branch` checked out, from `git worktree list --porcelain`."""
    path: str | None = None
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}" and path:
            return Path(path)
    return None
