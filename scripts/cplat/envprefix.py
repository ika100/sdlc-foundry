"""Environment-prefixed devbox commands named in a spec folder (spec 184, AC-184.10).

A verification command written as `NAME=value devbox run <script>` in the committed plan.md or design.md is allowed
verbatim; anything else of that form is listed as not allowed. This module must not import `headless`.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import units
from core import run

REFUSED_NAMES = ("PATH", "HOME", "SHELL", "ENV", "BASH_ENV", "NODE_OPTIONS", "PYTHONPATH")
REFUSED_PREFIXES = ("LD_", "DYLD_", "CPLAT_", "GIT_", "GH_")

_SPAN = re.compile(r"`([^`\n]+)`")
_FIRST = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_ASSIGN = re.compile(r"^([^=\s]+)=")
_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_CHAINING = (";", "&&", "||", "|", "&", ">", "<", "$(", "`", "\n")


def candidates(text: str) -> list[str]:
    """Every inline code span whose first word is NAME=value and that has at least one more word."""
    found = []
    for m in _SPAN.finditer(text):
        span = m.group(1).strip()
        words = span.split()
        if len(words) >= 2 and _FIRST.match(words[0]):
            found.append(span)
    return found


def verdict(command: str) -> str | None:
    """None when allowed, else the reason."""
    for token in _CHAINING:
        if token in command:
            return f"contains {token!r}"
    try:
        words = shlex.split(command)
    except ValueError as e:
        return f"cannot be parsed: {e}"
    i = 0
    while i < len(words) and (m := _ASSIGN.match(words[i])):
        name = m.group(1)
        if not _NAME.match(name):
            return f"name {name} is not uppercase"
        if name in REFUSED_NAMES or name.startswith(REFUSED_PREFIXES):
            return f"name {name} is refused"
        i += 1
    if i == 0:
        return "no NAME=value prefix"
    rest = words[i:]
    if len(rest) < 3 or rest[0] != "devbox" or rest[1] != "run":
        return "not `devbox run <script>`"
    return None


def _show(repo: Path, head: str, path: str) -> str:
    p = run(["git", "show", f"{head}:{path}"], cwd=repo, check=False)
    return p.stdout if p.returncode == 0 else ""


def commands(repo: Path, spec_ids: list[str]) -> tuple[list[str], list[str]]:
    """(allowed, not allowed) from the committed plan.md and design.md at the feature head, de-duplicated in order."""
    allowed: list[str] = []
    refused: list[str] = []
    for spec_id in spec_ids:
        head = units.feature_head(repo, spec_id)
        for name in ("plan.md", "design.md"):
            for cmd in candidates(_show(repo, head, f"docs/specs/{spec_id}/{name}")):
                target = allowed if verdict(cmd) is None else refused
                if cmd not in target:
                    target.append(cmd)
    return allowed, refused
