"""Image build parser: `docker build` with BuildKit (spec 108, t3)."""
from __future__ import annotations

import re

from failsum.core import MAX_EXCERPT, Context, Entry, FuncParser, Result, message

_SOLVE = re.compile(r"^ERROR: failed to solve: (?P<msg>.+)$")
_STEP_ERR = re.compile(r"^#\d+ ERROR: (?P<msg>.+)$")
_STEP_ERR_OLD = re.compile(r"^ERROR \[(?P<step>[^\]]+)\] (?P<msg>.+)$")
_DOCKERFILE = re.compile(r"^(?P<file>(?:\S*/)?[Dd]ockerfile[\w.-]*):(?P<line>\d+)\s*$")
_INSTR = re.compile(r"^\s*>>>\s*(?P<ins>[A-Z]+)\b")
_EXIT = re.compile(r"exit code: (?P<n>\d+)")


def docker_build(lines: list[str], ctx: Context) -> Result | None:
    at = next((i for i, ln in enumerate(lines) if _SOLVE.match(ln)), None)
    msg = _SOLVE.match(lines[at]).group("msg") if at is not None else None
    if at is None:
        for i, ln in enumerate(lines):
            m = _STEP_ERR.match(ln) or _STEP_ERR_OLD.match(ln)
            if m and ("did not complete" in m.group("msg") or "ERROR [" in ln):
                at, msg = i, m.group("msg")
                break
    if at is None or msg is None:
        return None
    locator, kind, excerpt = "Dockerfile", "build", []
    for i in range(at - 1, max(-1, at - 40), -1):
        d = _DOCKERFILE.match(lines[i])
        if not d:
            continue
        locator = f"{d.group('file')}:{d.group('line')}"
        for x in lines[i + 1:at]:
            if x.startswith("---") or not x.strip():
                continue
            excerpt.append(x)
            ins = _INSTR.match(x)
            if ins:
                kind = ins.group("ins")
        break
    return Result((Entry(at, False, locator, None, kind, message(msg), tuple(excerpt[:MAX_EXCERPT])),))


PARSERS: tuple = (FuncParser("docker-build", docker_build),)
