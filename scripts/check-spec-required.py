#!/usr/bin/env python3
"""A pull request that closes an issue and changes the platform carries its spec (spec 082).

  check-spec-required.py            reads PR_BODY, PR_LABELS (comma-separated), BASE_SHA and HEAD_SHA from the environment

"Platform changes start with a spec" (CLAUDE.md): when the body closes an issue (`Closes #N`, `Fixes #N`, `Resolves #N`)
and the diff touches scripts/, plugins/ or templates/, the diff must also touch docs/specs/. One-line fixes and docs
carry the `no-spec` label instead.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

CLOSES = re.compile(r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#\d+", re.I)
CODE = ("scripts/", "plugins/", "templates/")


def verdict(body: str, labels: list[str], files: list[str]) -> str | None:
    """None when the PR is fine, else the error message."""
    if "no-spec" in labels or not CLOSES.search(body or ""):
        return None
    code = [f for f in files if f.startswith(CODE)]
    if not code or any(f.startswith("docs/specs/") for f in files):
        return None
    return (f"this PR closes an issue and changes {len(code)} platform file(s) ({', '.join(code[:3])}{' …' if len(code) > 3 else ''}) "
            "but no spec under docs/specs/. Write one with /svc:spec (CLAUDE.md: platform changes start with a spec), "
            "or add the label `no-spec` for a one-line fix or docs.")


def main() -> int:
    rng = f"{os.environ['BASE_SHA']}...{os.environ['HEAD_SHA']}"
    files = subprocess.run(["git", "diff", "--name-only", rng], capture_output=True, text=True, check=True).stdout.split()
    labels = [x.strip() for x in os.environ.get("PR_LABELS", "").split(",") if x.strip()]
    err = verdict(os.environ.get("PR_BODY", ""), labels, files)
    if err:
        print(f"ERROR: {err}")
        return 1
    print("OK: spec rule satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
