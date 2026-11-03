"""The changelog and version text of `cplat platform release` (spec 129): move [Unreleased], read a section body, find
plugin/marketplace version mismatches. Pure text and file reading: no git, no gh, nothing here writes a file.

Spec 132 (ADR-078, #321): an entry may be a fragment `docs/changelog.d/<id>-<slug>.<added|changed|fixed>.md`; the release assembles
the fragments with the [Unreleased] text (Added, Changed, Fixed; [Unreleased] entries first, then fragments by file name)."""
from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

HEADING = re.compile(r"^## \[", re.M)
LINK = re.compile(r"(\]\(\s*)([^)\s]+)")
ABSOLUTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|/)", re.I)
UNRELEASED = re.compile(r"^## \[Unreleased\][^\n]*(?:\n|$)", re.M)
CHANGELOG = "docs/CHANGELOG.md"
FRAGMENTS = "docs/changelog.d"
SECTIONS = ("Added", "Changed", "Fixed")
FORM = "<id>-<slug>.<added|changed|fixed>.md"
FRAGMENT_NAME = re.compile(r"^[0-9a-z][0-9a-z.-]*?\.(added|changed|fixed)\.md$")
SUBHEAD = re.compile(r"^### +(.+?)\s*$", re.M)
UP_LINK = re.compile(r"(\]\()\.\./")


class FragmentError(ValueError):
    """A file in docs/changelog.d that is not a valid fragment (spec 132)."""


def parse_fragment(name: str, text: str) -> tuple[str, str]:
    """(section title, body) of one fragment; relative links lose one `../` so they resolve from docs/CHANGELOG.md."""
    m = FRAGMENT_NAME.match(name)
    if not m:
        raise FragmentError(f"{FRAGMENTS}/{name}: not a changelog fragment name; expected {FORM}")
    body = text.strip()
    if not body:
        raise FragmentError(f"{FRAGMENTS}/{name}: the fragment is empty; expected {FORM} with the entry text")
    return m[1].capitalize(), UP_LINK.sub(r"\1", body)


def read_fragments(repo: Path | str) -> list[tuple[str, str]]:
    """(name, text) of every fragment in the working tree, by name; README.md is the format's description, not a fragment."""
    d = Path(repo) / FRAGMENTS
    if not d.is_dir():
        return []
    out = [(f.name, f.read_text()) for f in sorted(d.iterdir()) if f.is_file() and f.name != "README.md"]
    for name, text in out:
        parse_fragment(name, text)
    return out


def assemble(body: str, fragments: list[tuple[str, str]] | tuple = ()) -> str:
    """The [Unreleased] body plus the fragments: the text before the first `###`, then Added, Changed, Fixed, then any other
    subsection in its original order. Without fragments the body is returned unchanged."""
    if not fragments:
        return body
    parts = SUBHEAD.split(body)
    preamble = parts[0].strip()
    sections: dict[str, list[str]] = {}
    for title, text in zip(parts[1::2], parts[2::2]):
        sections.setdefault(title.strip(), []).extend([text.strip()] if text.strip() else [])
    for name, text in sorted(fragments):
        title, entry = parse_fragment(name, text)
        sections.setdefault(title, []).append(entry)
    order = [s for s in SECTIONS if s in sections] + [s for s in sections if s not in SECTIONS]
    blocks = [preamble] if preamble else []
    blocks += [f"### {s}\n\n" + "\n\n".join(sections[s]) for s in order if sections[s]]
    return "\n\n".join(blocks) + "\n"


def unreleased_text(repo: Path | str) -> str:
    """What the next release will hold: the [Unreleased] body of the working tree assembled with its fragments (the version
    proposal reads this)."""
    f = Path(repo) / CHANGELOG
    return assemble(unreleased_body(f.read_text()) if f.is_file() else "", read_fragments(repo))


def _body_after(text: str, start: int) -> tuple[str, int]:
    """The text from `start` up to the next `## [` heading, and the index where it ends."""
    nxt = HEADING.search(text, start)
    end = nxt.start() if nxt else len(text)
    return text[start:end], end


def unreleased_body(text: str) -> str:
    m = UNRELEASED.search(text)
    return _body_after(text, m.end())[0] if m else ""


def move_unreleased(text: str, version: str, date: str, fragments: list[tuple[str, str]] | tuple = ()) -> str:
    if re.search(rf"^## \[{re.escape(version)}\]", text, re.M):
        return text
    m = UNRELEASED.search(text)
    if not m:
        return text
    body, end = _body_after(text, m.end())
    body = assemble(body, fragments)
    rest = text[end:]
    section = f"## [{version}] - {date}\n\n"
    if body.strip():
        section += body.strip() + "\n"
    out = text[: m.start()] + "## [Unreleased]\n\n" + section
    return out + ("\n" + rest if rest else "")


def section_body(text: str, version: str) -> str | None:
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*(?:\n|$)", text, re.M)
    if not m:
        return None
    return _strip_blank(_body_after(text, m.end())[0])


def absolute_links(body: str, slug: str, tag: str, base: str = "docs") -> str:
    """Rewrite Markdown links relative to `base` (`specs/...`, `adr/...`, `../README.md`) to
    https://github.com/<slug>/blob/<tag>/<path>, so they resolve on the GitHub release page (#336)."""
    def fix(m: re.Match) -> str:
        target = m[2]
        if ABSOLUTE.match(target):
            return m[0]
        path = posixpath.normpath(posixpath.join(base, target))
        if path.startswith(".."):
            return m[0]
        return f"{m[1]}https://github.com/{slug}/blob/{tag}/{path}"
    return LINK.sub(fix, body)


def _strip_blank(body: str) -> str:
    lines = body.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def plugin_mismatches(repo: Path | str) -> list[str]:
    repo = Path(repo)
    market: dict[str, str] = {}
    catalog = repo / ".claude-plugin" / "marketplace.json"
    if catalog.is_file():
        for p in json.loads(catalog.read_text()).get("plugins", []):
            market[p.get("name", "")] = str(p.get("version", "-"))
    lines = []
    for manifest in sorted((repo / "plugins").glob("*/.claude-plugin/plugin.json")):
        name = manifest.parent.parent.name
        have = str(json.loads(manifest.read_text()).get("version", "-"))
        want = market.get(name, "-")
        if want != have:
            lines.append(f"{name}: marketplace {want}, plugin.json {have}")
    return sorted(lines)
