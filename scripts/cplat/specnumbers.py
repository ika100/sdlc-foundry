"""Spec numbers that do not clash across parallel branches (spec 183).

`next_number` hands out a number no spec folder on main, on any pushed branch or in any open PR uses; `clashes`
reports a number this branch adds that another pushed branch or open PR also uses.
"""
from __future__ import annotations

import re
from pathlib import Path

import refscan

SPECS_DIR = "docs/specs"
BACKLOG = "docs/backlog.md"
FOLDER = re.compile(r"^(\d{3,})-")

NOT_CHECKED_NEW = ("WARNING: open PRs were not checked (could not read them with gh); "
                   "spec {number:03d} comes from main and the pushed branches")
NOT_CHECKED_CHECK = "WARNING: open PRs were not checked for spec numbers (could not read them with gh)"


def numbered(names: list[str]) -> dict[int, set[str]]:
    """Spec number → the folder names that carry it."""
    out: dict[int, set[str]] = {}
    for name in names:
        m = FOLDER.match(name)
        if m:
            out.setdefault(int(m.group(1)), set()).add(name)
    return out


def local(root: Path) -> dict[int, set[str]]:
    d = root / SPECS_DIR
    return numbered([p.name for p in d.iterdir() if p.is_dir()]) if d.is_dir() else {}


def at_ref(root: Path, ref: str) -> dict[int, set[str]]:
    return numbered(refscan.entries_at(root, ref, SPECS_DIR))


def other_branches(root: Path) -> dict[str, dict[int, set[str]]]:
    return {ref: numbered(names) for ref, names in refscan.other_branches(root, SPECS_DIR).items()}


def open_prs(root: Path) -> dict[str, dict[int, set[str]]] | None:
    """Spec folders each open PR's files are in, by `#<n>`; None when the PRs cannot be read."""
    prs = refscan.open_pr_paths(root)
    if prs is None:
        return None
    prefix = SPECS_DIR + "/"
    return {pr: numbered([p[len(prefix):].split("/", 1)[0] for p in paths if p.startswith(prefix)])
            for pr, paths in prs.items()}


def next_number(root: Path) -> tuple[int, str | None]:
    """One more than the highest spec number here, on main, on any pushed branch or in an open PR, and a warning line."""
    if not root.is_dir():  # a repo not created yet: nothing to read, nothing to clash with
        return 1, None
    taken = set(local(root))
    backlog = root / BACKLOG
    if backlog.is_file():  # continue after legacy STORY-NNN ids so old references stay unique
        taken |= {int(n) for n in re.findall(r"STORY-(\d+)", backlog.read_text())}
    base = refscan.base(root)
    if base:
        taken |= set(at_ref(root, base))
    for theirs in other_branches(root).values():
        taken |= set(theirs)
    prs = open_prs(root)
    for theirs in (prs or {}).values():
        taken |= set(theirs)
    number = max(taken, default=0) + 1
    return number, (NOT_CHECKED_NEW.format(number=number) if prs is None else None)


def clashes(root: Path) -> tuple[list[str], str | None]:
    """Error texts for each number this branch adds that is used elsewhere under another folder name, and a warning line.

    `cplat spec check` prints each as `ERROR: docs/specs: <text>`.
    """
    base = refscan.base(root)
    if base is None:
        return [], None
    on_base = at_ref(root, base)
    old = {n for names in on_base.values() for n in names}
    mine = {num: names - old for num, names in local(root).items() if names - old}
    if not mine:
        return [], None
    places: list[tuple[str, dict[int, set[str]]]] = [(base, on_base)]
    for ref, theirs in sorted(other_branches(root).items()):
        places.append((ref, {num: names - old for num, names in theirs.items()}))
    prs = open_prs(root)
    for pr, theirs in sorted((prs or {}).items()):
        places.append((f"open PR {pr}", {num: names - old for num, names in theirs.items()}))
    errors = []
    for where, theirs in places:
        for num, names in sorted(mine.items()):
            for a in sorted(names):
                for b in sorted(theirs.get(num, set()) - {a}):
                    errors.append(f"spec {num:03d} ({a}) is also used on {where} ({b}); take a new number from `cplat spec new`")
    return errors, (NOT_CHECKED_CHECK if prs is None else None)
