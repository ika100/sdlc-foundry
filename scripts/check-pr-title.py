#!/usr/bin/env python3
"""The `pr-title` job: PR_TITLE follows Conventional Commits (spec 126). The rule lives in scripts/cplat/pr_rules.py."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("pr_rules", Path(__file__).resolve().parent / "cplat" / "pr_rules.py")
pr_rules = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pr_rules)


def main() -> int:
    err = pr_rules.title_error(os.environ.get("PR_TITLE", ""))
    if err:
        print(f"ERROR: {err}")
        return 1
    print("OK: PR title is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
