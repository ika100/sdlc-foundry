#!/usr/bin/env python3
"""A pull request that closes an issue and changes the platform carries its spec (spec 082).

  check-spec-required.py            reads PR_BODY, PR_LABELS (comma-separated), BASE_SHA and HEAD_SHA from the environment

"Platform changes start with a spec" (CLAUDE.md): when the body closes an issue (`Closes #N`, `Fixes #N`, `Resolves #N`)
and the diff touches scripts/, plugins/ or templates/, the diff must also touch docs/specs/. One-line fixes and docs
carry the `no-spec` label instead. The rule lives in scripts/cplat/pr_rules.py (spec 126).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("pr_rules", Path(__file__).resolve().parent / "cplat" / "pr_rules.py")
pr_rules = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pr_rules)

verdict = pr_rules.spec_error   # the rule moved to pr_rules; kept under its old name


def main() -> int:
    files = pr_rules.changed_files(".", os.environ["BASE_SHA"], os.environ["HEAD_SHA"])
    labels = [x.strip() for x in os.environ.get("PR_LABELS", "").split(",") if x.strip()]
    err = verdict(os.environ.get("PR_BODY", ""), labels, files)
    if err:
        print(f"ERROR: {err}")
        return 1
    print("OK: spec rule satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
