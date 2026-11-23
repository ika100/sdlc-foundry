""".NET parsers (service-dotnet): `dotnet test` (VSTest console output) and MSBuild diagnostics of `dotnet build` and
`dotnet format` (spec 218)."""
from __future__ import annotations

import re

from failsum.core import MAX_EXCERPT, Context, Entry, FuncParser, Result, message

_FAILED = re.compile(r"^\s*Failed (?P<id>[\w.`<>+,]+(?:\([^)]*\))?) \[[^\]]*\]$")
_SECTION = re.compile(r"^\s*(?P<name>Error Message|Stack Trace|Standard Output Messages):\s*$")
_FRAME = re.compile(r"^\s*at (?P<frame>.+?) in (?P<file>\S+\.cs):line (?P<line>\d+)\s*$")
_END = re.compile(r"^\s*(?:Failed |Passed |Skipped |Data collector |Results File:|\[xUnit\.net |Failed!|Passed!)")
_TOTAL = re.compile(r"^(?:Failed|Passed)!\s+-\s+Failed:\s+(?P<n>\d+),")


def dotnet_test(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for ln in lines:
        t = _TOTAL.match(ln.strip())
        if t:
            reported = (reported or 0) + int(t.group("n"))
    for i, ln in enumerate(lines):
        h = _FAILED.match(ln)
        if not h:
            continue
        body = []
        for x in lines[i + 1:]:
            if _END.match(x):
                break
            body.append(x)
        msg, section, where = [], None, None
        for x in body:
            s = _SECTION.match(x)
            if s:
                section = s.group("name")
                continue
            if section == "Error Message" and x.strip():
                msg.append(x.strip())
            elif section == "Stack Trace" and where is None:
                f = _FRAME.match(x)
                own = ctx.own(f.group("file")) if f else None
                if own:
                    where = f"{own}:{f.group('line')}"
        detail = msg[0] if msg else ""
        entries.append(Entry(i, True, h.group("id"), where or h.group("id"), "fail", message(detail), tuple(msg[1:MAX_EXCERPT + 1])))
    return Result(tuple(entries), reported) if entries else None


_DIAG = re.compile(r"^\s*(?P<file>\S[^(]*\.(?:cs|csproj|props|targets|slnx?))\((?P<line>\d+),\d+\): "
                   r"(?P<sev>error|warning) (?P<code>[A-Z]+\d*|[A-Z]+): (?P<msg>.*?)(?: \[[^\]]*\])?\s*$")


def msbuild(lines: list[str], ctx: Context) -> Result | None:
    entries, seen = [], set()
    for i, ln in enumerate(lines):
        m = _DIAG.match(ln)
        if not m or m.group("sev") != "error":
            continue
        f = ctx.own(m.group("file")) or m.group("file")
        key = (f, m.group("line"), m.group("code"), m.group("msg"))
        if key in seen:
            continue   # MSBuild repeats every error in its closing summary
        seen.add(key)
        entries.append(Entry(i, False, f"{f}:{m.group('line')}", None, m.group("code"), message(m.group("msg"))))
    return Result(tuple(entries)) if entries else None


PARSERS: tuple = (FuncParser("dotnet-test", dotnet_test), FuncParser("msbuild", msbuild))
