"""The changelog and version text of `cplat platform release` (spec 129): move [Unreleased], read a section body, find
plugin/marketplace version mismatches. Pure text and file reading: no git, no gh, nothing here writes a file."""
from __future__ import annotations

import json
import re
from pathlib import Path

HEADING = re.compile(r"^## \[", re.M)
UNRELEASED = re.compile(r"^## \[Unreleased\][^\n]*(?:\n|$)", re.M)


def _body_after(text: str, start: int) -> tuple[str, int]:
    """The text from `start` up to the next `## [` heading, and the index where it ends."""
    nxt = HEADING.search(text, start)
    end = nxt.start() if nxt else len(text)
    return text[start:end], end


def unreleased_body(text: str) -> str:
    m = UNRELEASED.search(text)
    return _body_after(text, m.end())[0] if m else ""


def move_unreleased(text: str, version: str, date: str) -> str:
    if re.search(rf"^## \[{re.escape(version)}\]", text, re.M):
        return text
    m = UNRELEASED.search(text)
    if not m:
        return text
    body, end = _body_after(text, m.end())
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
