"""Steering items (spec 175): what `skip`, `prioritize` and `resume <item>` name, a spec or an issue, and never a guess.

The explicit forms (`#N`, `issue-N`, `spec-N`, `0N`, `<N>-<slug>`) name what they say. A bare number is the spec with that value or
the open issue with that number; it is refused when it is both, neither, or a spec while the open issues cannot be read. Specs come
from `docs/specs/` of the repo and the cached snapshot (no GitHub read); open issues are read only for a bare number: from the
cached snapshot when it is fresh, else with one `gh issue list` that is not stored. This module only reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import dispatch_backlog as db
import dispatch_state as ds
from core import PlatformError


@dataclass
class Item:
    key: str     # issue-<N> | spec-<NNN>
    label: str   # "issue #<N>" | "spec <id>"


def _value(spec_id: str) -> int | None:
    head = spec_id.split("-", 1)[0]
    return int(head) if head.isdigit() else None


def _snapshot(slug: str) -> db.Snapshot | None:
    doc = ds.load(slug).get("snapshot") or {}
    return db.Snapshot.from_dict(doc) if doc.get("read_at") else None


def _spec_ids(repo: Path, snap: db.Snapshot | None) -> list[str]:
    ids = {p.parent.name for p in (repo / "docs" / "specs").glob("*/spec.md")}
    if snap is not None:
        ids |= {str(r["id"]) for r in [*snap.specs, *snap.drafts] if r.get("id")}
    return sorted(ids)


def _open_issues(repo: Path, slug: str, snap: db.Snapshot | None) -> tuple[set[int] | None, str]:
    """The numbers of the open issues, or None and the reason when they cannot be read."""
    if snap is not None and snap.age() < db.MAX_AGE and "issues" not in snap.unavailable:
        return {int(r["number"]) for r in snap.issues if "number" in r}, ""
    try:
        rows = db._json(db.gh(["issue", "list", *db._repo_args(slug), "--state", "open", "--limit", "500", "--json", "number"],
                              cwd=repo))
        if not isinstance(rows, list):
            raise PlatformError("gh issue list did not answer a list")
        return {int(r["number"]) for r in rows}, ""
    except (PlatformError, OSError, ValueError, KeyError, TypeError) as e:
        return None, (str(e).splitlines() or [type(e).__name__])[0]


def resolve(repo: Path, slug: str, text: str) -> Item:
    form, n = ds.parse_form(text)
    t = text.strip()
    if form == "issue":
        return Item(f"issue-{n}", f"issue #{n}")
    snap = _snapshot(slug)
    specs = [i for i in _spec_ids(repo, snap) if _value(i) == n]
    if len(specs) > 1:
        raise ds.ItemRefused(f"{t} matches more than one spec ({', '.join(specs)}): give one of them a new number")
    write = f"write spec-{n} or #{n}"
    if form == "spec":
        if not specs:
            raise ds.ItemRefused(f"{t} names no spec (no docs/specs/{n:03d}-*): write spec-{n} for an existing spec or #{n} for an issue")
        return Item(f"spec-{n:03d}", f"spec {specs[0]}")
    issues, why = _open_issues(repo, slug, snap)
    if issues is None:
        what = f"is spec {specs[0]}, but" if specs else "is no spec and"
        raise ds.ItemRefused(f"{t} {what} the open issues cannot be read ({why}): {write}")
    if specs and n in issues:
        raise ds.ItemRefused(f"{t} is both spec {specs[0]} and open issue #{n}: {write}")
    if specs:
        return Item(f"spec-{n:03d}", f"spec {specs[0]}")
    if n in issues:
        return Item(f"issue-{n}", f"issue #{n}")
    raise ds.ItemRefused(f"{t} is neither a spec nor an open issue: {write}")
