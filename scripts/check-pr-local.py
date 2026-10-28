#!/usr/bin/env python3
"""The `pr-title` and `spec-required` checks, locally (spec 126, AC-126.13): a step of scripts/ci-local.sh.

Checks PR_TITLE/PR_BODY/PR_LABELS when set, else the open pull request of the current branch (via `gh`). Without one both checks are skipped.
The rules live in scripts/cplat/pr_rules.py, the same module CI runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("pr_rules", Path(__file__).resolve().parent / "cplat" / "pr_rules.py")
pr_rules = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pr_rules)

SKIPPED = "skipped (no pull request yet)"


def _git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], capture_output=True).returncode == 0


def _pull_request() -> dict | None:
    """The open pull request of the current branch, or None (no gh, an error, not OPEN)."""
    try:
        p = subprocess.run(["gh", "pr", "view", "--json", "title,body,labels,baseRefName,state"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        pr = json.loads(p.stdout)
    except ValueError:
        return None
    return pr if isinstance(pr, dict) and pr.get("state") == "OPEN" else None


def main() -> int:
    title, body = os.environ.get("PR_TITLE", ""), os.environ.get("PR_BODY", "")
    base_name = "main"
    if title or body:
        labels = [x.strip() for x in os.environ.get("PR_LABELS", "").split(",") if x.strip()]
    else:
        pr = _pull_request()
        if pr is None:
            print(f"pr-title: {SKIPPED}")
            print(f"spec-required: {SKIPPED}")
            return 0
        title, body = pr.get("title") or "", pr.get("body") or ""
        labels = [x.get("name", "") if isinstance(x, dict) else str(x) for x in pr.get("labels") or []]
        base_name = pr.get("baseRefName") or "main"

    failed = False
    err = pr_rules.title_error(title)
    if err:
        failed = True
        print(f"pr-title: ERROR: {err}")
    else:
        print("pr-title: OK: PR title is valid.")

    base = f"origin/{base_name}" if _git_ok("rev-parse", "--verify", "--quiet", f"origin/{base_name}") else base_name
    try:
        files = pr_rules.changed_files(".", base)
    except (subprocess.CalledProcessError, OSError):
        files = []
    err = pr_rules.spec_error(body, labels, files)
    if err:
        failed = True
        print(f"spec-required: ERROR: {err}")
    else:
        print("spec-required: OK: spec rule satisfied")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
