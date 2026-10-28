"""Claim the issues a spec tracks, so parallel sessions see who works on what (spec 082).

A claim is the `in-progress` label, the user as assignee, and a comment naming the branch. A session that finds an
issue claimed for another branch stops instead of building it a second time; `--take-over` moves the claim.
`cplat component ship escalate` releases it. Claims are best effort where GitHub is unreachable: they never block offline work.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import PlatformError, run

LABEL = "in-progress"
MARK = "<!-- cplat-claim -->"
RELEASE = "<!-- cplat-release -->"


def gh(args: list[str], *, cwd: Path) -> tuple[int, str]:   # tests replace this
    try:
        p = run(["gh", *args], cwd=cwd, check=False)
    except PlatformError:
        return 127, ""
    return p.returncode, p.stdout


def holder(issue: dict) -> str | None:
    """The branch of the last claim that was not released, if the issue still carries the label."""
    if LABEL not in {lb.get("name") for lb in issue.get("labels") or []}:
        return None
    branch = None
    for c in issue.get("comments") or []:
        body = c.get("body") or ""
        if body.startswith(MARK):
            m = re.search(r"branch `([^`]+)`", body)
            branch = m.group(1) if m else branch
        elif body.startswith(RELEASE):
            branch = None
    return branch


def claim(repo: Path, issues: list[int], branch: str, *, take_over: bool = False, what: str = "") -> list[str]:
    """Claim each open issue for `branch`; raises when another branch holds one (unless take_over). Returns notes."""
    notes: list[str] = []
    for n in issues:
        rc, out = gh(["issue", "view", str(n), "--json", "state,labels,comments"], cwd=repo)
        if rc != 0:
            notes.append(f"#{n}: not claimed (GitHub not reachable)")
            continue
        try:
            issue = json.loads(out or "{}")
        except ValueError:
            notes.append(f"#{n}: not claimed (unreadable answer from GitHub)")
            continue
        if issue.get("state") != "OPEN":
            continue
        who = holder(issue)
        if who == branch:
            continue
        if who and not take_over:
            raise PlatformError(f"#{n} is already being worked on, on branch {who}",
                                hint="coordinate with that session; pass --take-over to move the claim to this branch")
        gh(["label", "create", LABEL, "--color", "FBCA04", "--description", "claimed by a session (spec 082)"], cwd=repo)
        gh(["issue", "edit", str(n), "--add-assignee", "@me", "--add-label", LABEL], cwd=repo)
        gh(["issue", "comment", str(n), "--body", f"{MARK}\nClaimed for branch `{branch}`{(' (' + what + ')') if what else ''}."
            + (f" Taken over from `{who}`." if who else "")], cwd=repo)
        notes.append(f"#{n}: claimed for {branch}")
    return notes


def release(repo: Path, issues: list[int], reason: str) -> None:
    for n in issues:
        gh(["issue", "edit", str(n), "--remove-label", LABEL], cwd=repo)
        gh(["issue", "comment", str(n), "--body", f"{RELEASE}\nReleased: {reason}"], cwd=repo)
