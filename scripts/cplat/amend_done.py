"""#1109: the build of an amendment leaves a `done` bullet in the spec's Changelog.

A spec that is already `done` can be amended in place (an `amended` bullet, no `draft` -> `done` round trip) and built by a
fix or a ship. Without a new `done` bullet the red check of the next amendment (AC-205.8) compares with the old `done`
commit and judges the already-built criteria again. `cplat pr open` calls `add` before it commits: a done spec whose
Changelog ends in an `amended` bullet after its last `done` bullet, in a PR that also changes files outside `docs/`, gets
a dated `done` bullet.
"""
from __future__ import annotations

import re
from pathlib import Path

import red_scope
import spec as specmod
from core import PlatformError

_SPEC_FILE = re.compile(r"^docs/specs/(\d{3,}-[a-z0-9][a-z0-9-]*)/spec\.md$")


def pending(sp: specmod.Spec) -> bool:
    """A done spec whose last `done` bullet is followed by an `amended` bullet."""
    marks = [b for b in red_scope._bullets(sp.body) if red_scope.DONE.match(b) or red_scope.AMENDED.match(b)]
    return sp.status == "done" and bool(marks) and bool(red_scope.AMENDED.match(marks[-1])) and red_scope.amended(sp)


def add(repo: Path, files: list[str]) -> list[str]:
    """Append the `done` bullet to each amended done spec among `files`; returns the spec ids changed."""
    if not any(not f.startswith("docs/") for f in files):
        return []                              # a docs-only change is the amendment itself, not its build
    changed: list[str] = []
    for f in files:
        m = _SPEC_FILE.match(f)
        if not m:
            continue
        try:
            sp = specmod.find(repo, m.group(1))
        except PlatformError:
            continue
        if pending(sp):
            specmod.save(sp.dir / "spec.md", sp.meta, specmod.add_changelog(sp.body, "done: the amendment is built"))
            changed.append(sp.id)
    return changed
