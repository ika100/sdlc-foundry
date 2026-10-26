#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The 4.7 -> 5.0 slash-command tombstones (spec 114, AC-114.27, AC-114.65).

    python scripts/tombstones.py write   write the 27 tombstone files
    python scripts/tombstones.py check   exit 1 and list the files that differ from the table

A tombstone runs nothing: it only tells the user where the command went.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MOVED: dict[str, str] = {
    "/svc:build": "/component:build",
    "/svc:fix-bug": "/component:fix",
    "/svc:plan": "/component:plan",
    "/svc:quick-task": "/component:fix",
    "/svc:release": "/component:release",
    "/svc:ship": "/component:ship",
    "/svc:spec": "/component:spec",
    "/svc:specs": "/component:spec",
    "/svc:verify": "/component:verify",
    "/app:build": "/system:ship",
    "/app:plan": "/system:plan",
    "/app:ship": "/system:ship",
    "/app:spec": "/system:spec",
    "/app:specs": "/system:spec",
    "/gitops:addon": (
        "/resource:add|remove (addon list: resources: in system.yaml; "
        "addon add observability: environments.<env>.observability in system.yaml)"
    ),
    "/gitops:compose": "/component:add",
    "/gitops:promote": "/instance:promote",
    "/gitops:secret": "/instance:secret (list: /instance:secret list)",
    "/shared:check-quality": "/component:check",
    "/shared:doctor": "/platform:doctor",
    "/shared:fleet": "/platform:fleet",
    "/shared:new-app": "/system:new",
    "/shared:new-service": "/component:new",
    "/shared:report-issue": "/issue:report",
    "/shared:status": "/system:status",
    "/shared:triage": "/issue:triage",
    "/shared:update-service": "/platform:update",
}


def path_of(old: str) -> Path:
    plugin, name = old[1:].split(":")
    return ROOT / "plugins" / plugin / "commands" / f"{name}.md"


def render(old: str, new: str) -> str:
    description = f"Moved in 5.0: {old} is {new}. Runs nothing."
    return (
        "---\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        f"moved-to: {json.dumps(new, ensure_ascii=False)}\n"
        "allowed-tools: Read, Glob\n"
        "---\n"
        "\n"
        f"`{old}` was renamed in sdlc-foundry 5.0. Run no script, start no agent, change no file.\n"
        "\n"
        "1. With Read and Glob only, check whether this repo is migrated: it is not when `.platform-version` is "
        "missing or its `platform:` is below 5.0.0, or when `applications/*/app.yaml` or "
        "`applications/*/services.yaml` exists.\n"
        "2. Answer with exactly one line and nothing else:\n"
        f"   - migrated: `{old}` is `{new}` in 5.0.\n"
        f"   - not migrated: `{old}` is `{new}` in 5.0; run `cplat platform update --migrate` first.\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("write", "check"):
        print("usage: tombstones.py write|check", file=sys.stderr)
        return 2
    drifted = []
    for old, new in MOVED.items():
        path, want = path_of(old), render(old, new)
        if argv[0] == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(want)
        elif not path.is_file() or path.read_text() != want:
            drifted.append(str(path.relative_to(ROOT)))
    if drifted:
        print("tombstones drifted (run: python scripts/tombstones.py write):", file=sys.stderr)
        print("\n".join(drifted))
        return 1
    if argv[0] == "check":
        print(f"OK: {len(MOVED)} tombstones match scripts/tombstones.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
