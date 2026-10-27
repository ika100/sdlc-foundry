#!/usr/bin/env python3
"""Keep the copies in templates/cluster-gitops equal to their gitops-app sources (spec 125, design decision 13).

  sync-template-copies.py --check   exit 1 naming each copy that differs and the fix
  sync-template-copies.py           rewrite the copies from their sources
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, DST = ROOT / "templates" / "gitops-app" / "scripts", ROOT / "templates" / "cluster-gitops" / "scripts"
COPIES = {"render.py": "system_render.py", "local-cluster.sh": "local-cluster.sh", "ports.sh": "ports.sh"}


def differing() -> list[tuple[Path, Path]]:
    return [(SRC / s, DST / d) for s, d in COPIES.items() if not (DST / d).is_file() or (DST / d).read_bytes() != (SRC / s).read_bytes()]


def main(argv: list[str]) -> int:
    bad = differing()
    if "--check" in argv:
        for src, dst in bad:
            print(f"{dst.relative_to(ROOT)} differs from {src.relative_to(ROOT)}; fix: uv run scripts/sync-template-copies.py", file=sys.stderr)
        return 1 if bad else 0
    for src, dst in bad:
        dst.write_bytes(src.read_bytes())
        print(f"rewrote {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
