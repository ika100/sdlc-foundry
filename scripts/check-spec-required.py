#!/usr/bin/env python3
"""A pull request that closes an issue and changes the platform carries its spec (spec 082).

  check-spec-required.py            reads PR_BODY, PR_LABELS (comma-separated), BASE_SHA, HEAD_SHA and PR_NUMBER from the environment

"Platform changes start with a spec" (CLAUDE.md): when the PR closes an issue (GitHub's closingIssuesReferences for
PR_NUMBER when it can be read, else a line of the body that starts with `Closes #N`, `Fixes #N` or `Resolves #N`)
and the diff touches scripts/, plugins/ or templates/, the diff must also touch docs/specs/. One-line fixes and docs
carry the `no-spec` label instead. The rule lives in scripts/cplat/pr_rules.py (spec 126).
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

verdict = pr_rules.spec_error   # the rule moved to pr_rules; kept under its old name


def closing_issues() -> list[int] | None:
    """The issues GitHub says PR_NUMBER closes (its own parse of the body and linked issues), None when it cannot be asked."""
    number, repo = os.environ.get("PR_NUMBER"), os.environ.get("GITHUB_REPOSITORY")
    if not number or not repo:
        return None
    try:
        p = subprocess.run(["gh", "pr", "view", number, "--repo", repo, "--json", "closingIssuesReferences"],
                           capture_output=True, text=True, timeout=60, check=False)
        refs = json.loads(p.stdout)["closingIssuesReferences"] if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return None
    return None if refs is None else [r["number"] for r in refs]


def main() -> int:
    files = pr_rules.changed_files(".", os.environ["BASE_SHA"], os.environ["HEAD_SHA"])
    labels = [x.strip() for x in os.environ.get("PR_LABELS", "").split(",") if x.strip()]
    err = verdict(os.environ.get("PR_BODY", ""), labels, files, closing_issues())
    if err:
        print(f"ERROR: {err}")
        return 1
    print("OK: spec rule satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
