"""Replaced criteria (spec 183): `(replaces AC-<NNN>.<n>)` on a criterion, and the "superseded by" strike on the old one.

`spec` imports this module lazily; this module imports `spec` only inside functions.
"""
from __future__ import annotations

import re
from pathlib import Path

MARKER = re.compile(r"\(replaces (AC-\d{3,}\.\d+)\)(\s*\(smoke\))?\s*$")
SUPERSEDED = re.compile(r"^\s*[-*]\s+~~\*\*(AC-\d{3,}\.\d+)\*\*~~\s+superseded by (AC-\d{3,}\.\d+)")
SUPERSEDED_TEXT = re.compile(r"^(\s*[-*]\s+)~~\*\*(AC-\d{3,}\.\d+)\*\*~~\s+superseded by \S+ on \d{4}-\d{2}-\d{2}: (.*)$")


def markers(spec) -> list[tuple[str, str]]:
    """(new, old) for every active criterion of the spec that ends with `(replaces AC-…)`."""
    import spec as specmod
    text = specmod.sections(spec.body).get("acceptance criteria", "")
    found = []
    for ln in text.splitlines():
        m = specmod.AC_LINE.match(ln)
        if m and not m.group(1) and (r := MARKER.search(ln)):
            found.append((m.group(2), r.group(1)))
    return found


def hash_text(text: str) -> str:
    """Criteria text with a superseded line that keeps its old text read as the active line it was (keeps `spec_hash`)."""
    return "\n".join(SUPERSEDED_TEXT.sub(r"\1**\2** \3", ln) for ln in text.splitlines())


def errors(spec, by_number: dict) -> list[str]:
    import spec as specmod
    errs = []
    for new, old in markers(spec):
        target = by_number.get(old.split("-", 1)[1].split(".", 1)[0])
        ac = next((a for a in target.acs() if a.id == old), None) if target else None
        if ac is None:
            errs.append(f"{new} replaces {old}, which does not exist")
        elif not ac.withdrawn:
            errs.append(f'{new} replaces {old}, which is still active; strike it through in docs/specs/{target.id}/spec.md '
                        f'as "~~**{old}**~~ superseded by {new} on {specmod.today()}: <old text>" with one Changelog line')
    return errs


def strike(spec_dir: Path, old: str, new: str) -> bool:
    """Rewrite the active criterion `old` of the spec in `spec_dir` as superseded by `new` and log it; False if not active."""
    import spec as specmod
    if not any(a.id == old and not a.withdrawn for a in specmod.read(spec_dir).acs()):
        return False
    path = spec_dir / "spec.md"
    pat = re.compile(rf"^(\s*[-*]\s+)\*\*{re.escape(old)}\*\*[ \t]*(.*)$", re.M)
    m = pat.search(path.read_text())
    if not m:
        return False
    text = path.read_text()
    old_text = m.group(2).strip()
    line = f"{m.group(1)}~~**{old}**~~ superseded by {new} on {specmod.today()}" + (f": {old_text}" if old_text else "")
    text = text[:m.start()] + line + text[m.end():]
    path.write_text(specmod.add_changelog(text, f"{old} superseded by {new}"))
    return True
