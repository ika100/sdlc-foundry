"""cplat adr add: the next ADR from the template and its row in the ADR index (spec 183)."""
from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path

import adr
import core
from core import PlatformError

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TEMPLATE = core.PLATFORM_ROOT / "scripts" / "cplat" / "assets" / "adr-template.md"
HEADER = "| ADR | Decision |\n|---|---|\n"


def _existing(adr_dir: Path, slug: str) -> Path | None:
    if not adr_dir.is_dir():
        return None
    for p in sorted(adr_dir.iterdir()):
        if re.fullmatch(rf"\d{{3,4}}-{re.escape(slug)}\.md", p.name):
            return p
    return None


def _with_row(text: str | None, row: str) -> str:
    """The index text with `row` after the last table line; every other byte unchanged."""
    if text is None:
        return f"# Architecture decision records\n\n{HEADER}{row}\n"
    lines = text.splitlines(keepends=True)
    last = max((i for i, ln in enumerate(lines) if ln.startswith("|")), default=None)
    if last is None:
        sep = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{sep}\n{HEADER}{row}\n"
    line = lines[last]
    if line.endswith("\n"):
        lines.insert(last + 1, row + "\n")
    else:
        lines[last] = line + "\n"
        lines.insert(last + 1, row)
    return "".join(lines)


def add(root: Path, slug: str, decision: str, offline: bool) -> str:
    decision = " ".join(decision.split())
    if not SLUG.match(slug):
        raise PlatformError(f"slug '{slug}' must be lowercase words joined by hyphens")
    if not decision:
        raise PlatformError("--decision is empty")
    adr_dir = root / adr.ADR_DIR
    used = _existing(adr_dir, slug)
    if used:
        raise PlatformError(f"slug '{slug}' is already used by {adr.ADR_DIR}/{used.name}")
    number = f"{adr.next_number(root, with_prs=not offline):03d}"
    title = slug.replace("-", " ")
    title = title[0].upper() + title[1:]
    body = (TEMPLATE.read_text().replace("@@NUMBER@@", number).replace("@@TITLE@@", title)
            .replace("@@DATE@@", datetime.date.today().isoformat()).replace("@@DECISION@@", decision))
    name = f"{number}-{slug}.md"
    index = adr_dir / "README.md"
    row = f"| [{number}]({name}) | {decision.replace('|', chr(92) + '|')} |"
    new_index = _with_row(index.read_text() if index.is_file() else None, row)
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / name).write_text(body)
    index.write_text(new_index)
    return f"{adr.ADR_DIR}/{name}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat adr")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="the next ADR from the template and its index row")
    p.add_argument("slug")
    p.add_argument("--decision", required=True, help="the decision in one line")
    p.add_argument("--offline", action="store_true", help="do not ask GitHub for open PRs")
    p.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    print(add(Path(ns.repo).resolve(), ns.slug, ns.decision, ns.offline))
    return 0
