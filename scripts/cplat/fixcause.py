"""The cause line of a platform fix entry (spec 223): its form, its parse, the entries of a `### Fixed` section, the numbers an
entry names, and its check against GitHub.

A `fixed` changelog fragment ends in one line `Caused by: #<PR>[, #<PR>…] | v<X.Y.Z> | none | unknown`, written directly under
the entry text. pr-check, the CI fragment check and change-quality all import this module, so they agree on what is valid.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import core

FORM = "Caused by: #<PR> | v<X.Y.Z> | none | unknown"
CAUSE_LINE = re.compile(r"^Caused by: (?:#\d+(?:, #\d+)*|v\d+\.\d+\.\d+|none|unknown)$")
_PR_NUMBER = re.compile(r"\(#(\d+)\)")
_LEADING_ID = re.compile(r"^(\d+)-")

GhRun = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Cause:
    kind: Literal["prs", "version", "none", "unknown"]
    prs: tuple[int, ...] = ()        # kind "prs"
    version: str | None = None       # kind "version", "X.Y.Z" without the v


def _last_line(entry: str) -> str:
    lines = [ln.strip() for ln in entry.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def parse_cause(entry: str) -> Cause | None:
    """The cause of an entry, or None when its last non-blank line is not a valid cause line."""
    line = _last_line(entry)
    if not CAUSE_LINE.match(line):
        return None
    value = line[len("Caused by: "):]
    if value in ("none", "unknown"):
        return Cause(value)  # type: ignore[arg-type]
    if value.startswith("v"):
        return Cause("version", version=value[1:])
    return Cause("prs", prs=tuple(int(n) for n in re.findall(r"\d+", value)))


def form_error(path: str, text: str) -> str | None:
    """The problem of a fragment's cause line; None for `added` and `changed` fragments and valid `fixed` ones."""
    if not path.endswith(".fixed.md"):
        return None
    if parse_cause(text) is not None:
        return None
    return f"{path}: a fixed fragment ends in a cause line; expected {FORM}"


def entries(fixed_section: str) -> list[str]:
    """The paragraphs of a Fixed section; a paragraph that is only a cause line joins the one before."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", fixed_section.strip()):
        para = para.strip()
        if not para:
            continue
        if out and CAUSE_LINE.match(para):
            out[-1] += "\n" + para
        else:
            out.append(para)
    return out


def numbers(entry: str, fragment_id: str | None = None) -> set[int]:
    """Every `(#NNN)` of the entry outside its cause line, plus the fragment's numeric id."""
    body = entry
    if parse_cause(entry) is not None:
        body = "\n".join(entry.rstrip().splitlines()[:-1])
    found = {int(n) for n in _PR_NUMBER.findall(body)}
    if fragment_id is not None:
        m = _LEADING_ID.match(fragment_id) or re.fullmatch(r"(\d+)", fragment_id)
        if m:
            found.add(int(m.group(1)))
    return found


def _gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return core.run(["gh", *args], check=False)


def _first_line(p: subprocess.CompletedProcess[str]) -> str:
    text = (p.stderr or p.stdout or "").strip()
    return text.splitlines()[0] if text else f"gh exited {p.returncode}"


def _not_found(p: subprocess.CompletedProcess[str]) -> bool:
    return "404" in (p.stderr or "") or "Not Found" in (p.stderr or "")


def slug_of(repo: Path | str) -> str | None:
    """`owner/name` of the repo, None when gh cannot say."""
    p = core.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=repo, check=False)
    return p.stdout.strip() or None if p.returncode == 0 else None


def verify(slug: str, cause: Cause, *, gh: GhRun | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) of a cause against GitHub. A PR must be merged, a version must be a tag; GitHub that cannot answer
    is a warning that it was not checked."""
    run = gh or _gh
    errors: list[str] = []
    warnings: list[str] = []
    if cause.kind == "prs":
        for n in cause.prs:
            p = run(["api", f"repos/{slug}/pulls/{n}", "-q", ".merged_at"])
            if p.returncode == 0:
                if p.stdout.strip() in ("", "null", "None"):
                    errors.append(f"Caused by #{n} is not a merged PR of {slug}")
            elif _not_found(p):
                errors.append(f"Caused by #{n} is not a merged PR of {slug}")
            else:
                warnings.append(f"GitHub unreachable, Caused by #{n} was not checked ({_first_line(p)})")
    elif cause.kind == "version":
        p = run(["api", f"repos/{slug}/git/ref/tags/v{cause.version}"])
        if p.returncode != 0:
            if _not_found(p):
                errors.append(f"Caused by v{cause.version} names no tag of {slug}")
            else:
                warnings.append(f"GitHub unreachable, Caused by v{cause.version} was not checked ({_first_line(p)})")
    return errors, warnings
