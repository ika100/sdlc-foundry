"""Find a changelog entry before and after the release (issue #1071).

A change is a fragment `docs/changelog.d/<id>-<slug>.<kind>.md` until `cplat platform release` moves it into a paragraph of
`docs/CHANGELOG.md`. A test of a changelog criterion calls `changelog_entry(match)` so that it holds on both sides of the release.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def changelog_entry(match: str | re.Pattern, *, fragment: str = "*.md", root: Path = ROOT) -> list[str]:
    """Every entry that contains `match` (a string, or a regex searched in it): fragments named like `fragment`
    (e.g. `216-*.added.md`) and the paragraphs of the released docs/CHANGELOG.md."""
    folder = root / "docs" / "changelog.d"
    entries = [p.read_text(encoding="utf-8") for p in sorted(folder.glob(fragment)) if p.name != "README.md"] if folder.is_dir() else []
    released = root / "docs" / "CHANGELOG.md"
    if released.is_file():
        entries += released.read_text(encoding="utf-8").split("\n\n")
    if isinstance(match, str):
        return [e for e in entries if match in e]
    return [e for e in entries if match.search(e)]
