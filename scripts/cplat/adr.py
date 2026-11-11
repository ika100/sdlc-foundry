"""ADR numbers that do not clash across parallel branches (#337).

Two specs planned while the first one's PR was open both wrote ADR-073; `cplat spec check` passed because main had no 073
yet. `next_number` hands out a number no pushed branch and no open PR uses, and `clashes` reports a number this branch
adds that is already taken: twice in docs/adr, or by another branch.
"""
from __future__ import annotations

import re
from pathlib import Path

import refscan

ADR_DIR = "docs/adr"
NUMBER = re.compile(r"^(\d{3,4})-.+\.md$")


def numbered(names: list[str]) -> dict[int, set[str]]:
    """ADR number → the file names that carry it."""
    out: dict[int, set[str]] = {}
    for name in names:
        m = NUMBER.match(Path(name).name)
        if m:
            out.setdefault(int(m.group(1)), set()).add(Path(name).name)
    return out


def local(root: Path) -> dict[int, set[str]]:
    d = root / ADR_DIR
    return numbered([p.name for p in d.iterdir()]) if d.is_dir() else {}


def at_ref(root: Path, ref: str) -> dict[int, set[str]]:
    return numbered(refscan.entries_at(root, ref, ADR_DIR))


def _base(root: Path) -> str | None:
    return refscan.base(root)


def other_branches(root: Path) -> dict[str, dict[int, set[str]]]:
    """The ADRs of every pushed branch except main and the branch checked out here (no network: the last fetch)."""
    return {ref: numbered(names) for ref, names in refscan.other_branches(root, ADR_DIR).items()}


def open_prs(root: Path) -> dict[str, set[str]]:
    """ADR file names each open PR adds, by PR number (empty when `gh` cannot be asked)."""
    prs = refscan.open_pr_paths(root) or {}
    return {pr: {Path(p).name for p in paths if p.startswith(ADR_DIR + "/")} for pr, paths in prs.items()}


def added_here(root: Path) -> dict[int, set[str]]:
    """The ADRs in the working tree that the base branch does not have."""
    base = _base(root)
    have = local(root)
    if base is None:
        return {}
    old = {n for names in at_ref(root, base).values() for n in names}
    return {num: names - old for num, names in have.items() if names - old}


def clashes(root: Path) -> list[str]:
    """Errors: a number used by two files here, or a number this branch adds that another branch already uses."""
    errors = [f"{ADR_DIR}: ADR-{num:03d} is used by {len(names)} files ({', '.join(sorted(names))}); renumber all but one"
              for num, names in sorted(local(root).items()) if len(names) > 1]
    mine = added_here(root)
    if not mine:
        return errors
    base = _base(root)
    on_base = at_ref(root, base) if base else {}
    for ref, theirs in sorted(other_branches(root).items()):
        for num, names in sorted(mine.items()):
            other = theirs.get(num, set()) - names - on_base.get(num, set())   # the base's own file is the error above
            if other:
                errors.append(f"{ADR_DIR}: ADR-{num:03d} ({', '.join(sorted(names))}) is also used on {ref} "
                              f"({', '.join(sorted(other))}); take a free number from `cplat spec adr-next`")
    return errors


def next_number(root: Path, with_prs: bool = True) -> int:
    """One more than the highest ADR number here, on any pushed branch, or in an open PR."""
    taken = set(local(root))
    base = _base(root)
    if base:
        taken |= set(at_ref(root, base))
    for theirs in other_branches(root).values():
        taken |= set(theirs)
    if with_prs:
        for names in open_prs(root).values():
            taken |= set(numbered(list(names)))
    return max(taken, default=0) + 1
