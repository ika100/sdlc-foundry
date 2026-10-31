#!/usr/bin/env python3
"""Keep template script copies equal to their gitops-app sources (spec 125 design decision 13; spec 130 gate.sh).

  sync-template-copies.py --check   exit 1 naming each copy that differs and the fix
  sync-template-copies.py           rewrite the copies from their sources
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
APP, CLUSTER = TEMPLATES / "gitops-app" / "scripts", TEMPLATES / "cluster-gitops" / "scripts"
# (source, copy) pairs; a pair whose source does not exist is skipped.
COPIES: list[tuple[Path, Path]] = [
    (APP / "render.py", CLUSTER / "system_render.py"),
    (APP / "local-cluster.sh", CLUSTER / "local-cluster.sh"),
    (APP / "ports.sh", CLUSTER / "ports.sh"),
] + [
    (APP / "gate.sh", TEMPLATES / t / "scripts" / "gate.sh")
    for t in ("cluster-gitops", "service-python", "library-python", "service-go", "service-java", "web-nextjs")
]


def differing() -> list[tuple[Path, Path]]:
    return [(s, d) for s, d in COPIES if s.is_file() and (not d.is_file() or d.read_bytes() != s.read_bytes())]


def main(argv: list[str]) -> int:
    bad = differing()
    if "--check" in argv:
        for src, dst in bad:
            print(f"{dst.relative_to(ROOT)} differs from {src.relative_to(ROOT)}; fix: uv run scripts/sync-template-copies.py", file=sys.stderr)
        return 1 if bad else 0
    for src, dst in bad:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        print(f"rewrote {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
