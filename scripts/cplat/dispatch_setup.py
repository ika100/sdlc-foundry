"""Spec 193 (AC-193.2): the run queue's policy written for the person, landed like every other change (design.md `setup`).

  suggest(slug) -> int | None   the highest known day of the 7-day hint, rounded up to the next 1,000,000 (None: no known day above 0)
  text(tokens) -> str           the fixed policy file; None renders `<your number>` (for `--show` only)
  apply(repo, tokens) -> lines  branch `chore/dispatch-setup` from origin/main in a temporary worktree, commit -s, push, open the
                                PR, wait for green CI and merge it, then fast-forward the local main when it is checked out and clean

`apply` refuses (`PlatformError`) when `.platform/dispatch.yml` exists or the number is below 1, raises with the `pr wait` lines when a
check is red (the PR stays open) and ends with `SWITCH` when the local main could not be moved (the verb exits 1 then). The checkout
the person works in is never touched except for that fast-forward. `git`, `gh` and the wait are the seams tests replace (`git`, `gh`, `wait`).
"""
from __future__ import annotations

import math
import re
import shutil
import tempfile
from pathlib import Path

import dispatch_budget
import land_merge
import pr as prmod
import ship
from core import PlatformError, run

POLICY = ".platform/dispatch.yml"
BRANCH = "chore/dispatch-setup"
TITLE = "chore(dispatch): set up the run queue policy"
SWITCH = "the policy is on main; switch to main to build"
PLACEHOLDER = "<your number>"
STEP = 1_000_000
WAIT_TIMEOUT = 7200
WAIT_INTERVAL = 20

_FILE = """# The run queue's policy (docs/dispatch.md), written by /platform:next.
budget:
  tokens_per_day: {n}
sources: [issues, specs]
gates:
  approve_specs: human
"""
_BODY = """Sets up the run queue's policy (`.platform/dispatch.yml`) with a budget of {n} tokens per day.

Written by `/platform:next` (`cplat dispatch setup`); it merges once CI is green. Edit the file later to change the budget
or the sources (docs/dispatch.md).
"""


def git(repo: Path, *args: str, check: bool = True):   # tests replace this
    return run(["git", *args], cwd=repo, check=check)


def gh(repo: Path, *args: str):   # tests replace this
    return run(["gh", *args], cwd=repo)


def wait(repo: Path, url: str) -> tuple[bool, list[str]]:   # tests replace this
    return prmod.wait(repo, url, True, WAIT_TIMEOUT, WAIT_INTERVAL, ship.QUEUE_TIMEOUT, mode=land_merge.CATCH_UP)


def suggest(slug: str) -> int | None:
    """The highest known day of the 7-day hint (days with no number left out) rounded up to the next million; None without one above 0."""
    known = [int(d["tokens"]) for d in dispatch_budget.history_hint(slug) if isinstance(d.get("tokens"), int)]
    top = max(known, default=0)
    return math.ceil(top / STEP) * STEP if top > 0 else None


def text(tokens: int | None) -> str:
    return _FILE.format(n=PLACEHOLDER if tokens is None else tokens)


def apply(repo: Path, tokens: int) -> list[str]:
    if tokens < 1:
        raise PlatformError(f"--tokens-per-day must be at least 1, not {tokens}")
    if (repo / POLICY).exists():
        raise PlatformError(f"{POLICY} exists already", "edit it, or change the budget with `cplat dispatch budget`")
    git(repo, "fetch", "-q", "origin", "main")
    tmp = Path(tempfile.mkdtemp(prefix="dispatch-setup-"))
    tree = tmp / "tree"
    try:
        git(repo, "worktree", "add", "-q", "-B", BRANCH, str(tree), "origin/main")
        (tree / POLICY).parent.mkdir(parents=True, exist_ok=True)
        (tree / POLICY).write_text(text(tokens))
        git(tree, "add", "--", POLICY)
        git(tree, "commit", "-q", "-s", "-m", TITLE)
        git(tree, "push", "-q", "-u", "origin", BRANCH)
        made = gh(tree, "pr", "create", "--base", "main", "--head", BRANCH, "--title", TITLE, "--body", _BODY.format(n=tokens))
        urls = (made.stdout or "").strip().splitlines()
        if not urls:
            raise PlatformError("`gh pr create` printed no pull request")
        url = urls[-1]
    finally:
        git(repo, "worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
        git(repo, "branch", "-D", BRANCH, check=False)
    ok, lines = wait(repo, url)
    if not ok:
        raise PlatformError("the pull request is not green: " + " | ".join(lines), f"it stays open: {url}")
    number = re.search(r"(\d+)\s*$", url)
    out = [f"merged: PR #{number.group(1) if number else url}"]
    return out + _fast_forward(repo)


def _fast_forward(repo: Path) -> list[str]:
    git(repo, "fetch", "-q", "origin", "main", check=False)
    on_main = git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip() == "main"
    clean = not git(repo, "status", "--porcelain", check=False).stdout.strip()
    if on_main and clean and git(repo, "merge", "--ff-only", "-q", "origin/main", check=False).returncode == 0:
        return []
    return [SWITCH]
