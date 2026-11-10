#!/usr/bin/env python3
"""Settings check (spec 171, AC-171.2): the platform repo's committed `.claude/settings.json` holds every `allow` and `ask` rule
of the library template's `.claude/settings.json`, so an unattended run in this repo is not stopped by a permission prompt.

One line per missing rule, `ERROR: .claude/settings.json lacks the library template's <allow|ask> rule "<rule>"`, then
`FAILED: <n> rule(s) missing` (exit 1); else `OK: .claude/settings.json holds the library template's <a> allow and <k> ask rules`
(exit 0). An unreadable or invalid file is one `ERROR: <path>: <reason>` line (exit 1). Standard library only.
Run it from the repository root: `python3 scripts/check-settings.py [--root DIR]`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLATFORM = ".claude/settings.json"
TEMPLATE = "templates/library-python/.claude/settings.json"
KINDS = ("allow", "ask")


def load_rules(root: Path, rel: str) -> dict[str, list[str]]:
    """The `permissions.allow` and `permissions.ask` lists of one settings file; raises ValueError with the reason."""
    path = root / rel
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{rel}: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise ValueError(f"{rel}: invalid JSON ({exc})") from exc
    perms = data.get("permissions", {}) if isinstance(data, dict) else None
    if not isinstance(perms, dict):
        raise ValueError(f"{rel}: not a settings object with a `permissions` object")
    out: dict[str, list[str]] = {}
    for kind in KINDS:
        rules = perms.get(kind, [])
        if not isinstance(rules, list) or not all(isinstance(r, str) for r in rules):
            raise ValueError(f"{rel}: permissions.{kind} is not a list of strings")
        out[kind] = rules
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent, help="repository root")
    root = parser.parse_args(argv).root
    try:
        template = load_rules(root, TEMPLATE)
        platform = load_rules(root, PLATFORM)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    missing = 0
    for kind in KINDS:
        for rule in template[kind]:
            if rule not in platform[kind]:
                print(f'ERROR: {PLATFORM} lacks the library template\'s {kind} rule "{rule}"')
                missing += 1
    if missing:
        print(f"FAILED: {missing} rule(s) missing")
        return 1
    print(f"OK: {PLATFORM} holds the library template's {len(template['allow'])} allow and {len(template['ask'])} ask rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
