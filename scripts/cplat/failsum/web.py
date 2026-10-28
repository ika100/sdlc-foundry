"""Web parsers (web-nextjs): Vitest (with coverage thresholds), ESLint stylish, `tsc` and `next build` (spec 108, t3)."""
from __future__ import annotations

import re

from failsum.core import MAX_EXCERPT, Context, Entry, FuncParser, Result, message

_FAIL = re.compile(r"^\s*FAIL\s+(?:\[[^\]]+\]\s+)?(?P<name>\S+\.[cm]?[jt]sx?(?:\s.*?)?)\s*$")
_TYPED = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Failure))(?:: ?(?P<msg>.*))?$")
_FRAME = re.compile(r"^\s*❯ (?P<path>\S+?):(?P<line>\d+):\d+\s*$")
_VI_TOTAL = re.compile(r"^\s*Tests\s+(?P<n>\d+) failed")
_VI_COV = re.compile(r"^ERROR: Coverage for (?P<metric>[\w ]+?) \((?P<got>[\d.]+)%\) does not meet (?:global )?threshold "
                     r"\((?P<req>[\d.]+)%\)(?: for (?P<file>\S+))?")


def vitest(lines: list[str], ctx: Context) -> Result | None:
    entries: list[Entry] = []
    seen: set[str] = set()
    reported = None
    for i, ln in enumerate(lines):
        t = _VI_TOTAL.match(ln)
        if t:
            reported = int(t.group("n"))
        c = _VI_COV.match(ln)
        if c:
            loc = ctx.own(c.group("file")) if c.group("file") else None
            entries.append(Entry(i, False, loc or "TOTAL", None, "coverage",
                                 f"{c.group('metric')} coverage {c.group('got')}% is below the required {c.group('req')}%"))
            continue
        m = _FAIL.match(ln)
        if not m or m.group("name") in seen:
            continue
        name = m.group("name")
        seen.add(name)
        block = []
        for x in lines[i + 1:]:
            if x.startswith("⎯") or _FAIL.match(x):
                break
            block.append(x)
        kind, detail, excerpt, where = "error", "", [], None
        first = next((x for x in block if x.strip()), "")
        tm = _TYPED.match(first.strip())
        if tm:
            kind, detail = tm.group("type"), tm.group("msg") or ""
            excerpt.append(first.strip())
        elif first:
            detail = first.strip()
            excerpt.append(first.strip())
        for x in block:
            fm = _FRAME.match(x)
            if fm and ctx.own(fm.group("path")):
                where = where or f"{ctx.own(fm.group('path'))}:{fm.group('line')}"
                excerpt.append(x.strip())
        if where is None:
            file = name.split(" > ")[0].strip()
            where = ctx.own(file) or file
        entries.append(Entry(i, True, name, where, kind, message(detail), tuple(excerpt[:MAX_EXCERPT])))
    return Result(tuple(entries), reported) if entries else None


_ES_ITEM = re.compile(r"^\s+(?P<line>\d+):(?P<col>\d+)\s+(?P<sev>error|warning)\s+(?P<msg>.*?)(?:\s{2,}(?P<rule>\S+))?\s*$")
_ES_TOTAL = re.compile(r"^✖ (?P<n>\d+) problems? \((?P<e>\d+) errors?")


def eslint(lines: list[str], ctx: Context) -> Result | None:
    entries, reported, file = [], None, None
    for i, ln in enumerate(lines):
        t = _ES_TOTAL.match(ln)
        if t:
            reported = int(t.group("e"))
            continue
        m = _ES_ITEM.match(ln)
        if m and file:
            if m.group("sev") == "error":
                entries.append(Entry(i, False, f"{file}:{m.group('line')}", None, m.group("rule") or "error",
                                     message(m.group("msg"))))
        elif ln.strip() and not ln[0].isspace() and not ln.startswith("✖"):
            file = ctx.own(ln.strip()) or ln.strip()
    return Result(tuple(entries), reported) if entries else None


_TSC_PAREN = re.compile(r"^(?P<file>[^\s(]+)\((?P<line>\d+),\d+\): error (?P<code>TS\d+): (?P<msg>.*)$")
_TSC_COLON = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\d+ - error (?P<code>TS\d+): (?P<msg>.*)$")
_TSC_TOTAL = re.compile(r"^Found (?P<n>\d+) errors?")


def tsc(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        t = _TSC_TOTAL.match(ln)
        if t:
            reported = int(t.group("n"))
        m = _TSC_PAREN.match(ln) or _TSC_COLON.match(ln)
        if not m:
            continue
        more, j = [], i + 1
        while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
            more.append(lines[j])
            j += 1
        f = ctx.own(m.group("file")) or m.group("file")
        entries.append(Entry(i, False, f"{f}:{m.group('line')}", None, m.group("code"), message(m.group("msg")),
                             tuple(more[:MAX_EXCERPT])))
    return Result(tuple(entries), reported) if entries else None


_NB_FILE = re.compile(r"^(?P<file>\.?/?[^\s:]+?)(?::(?P<line>\d+):\d+)?$")
_NB_FRAME = re.compile(r"^\s*(?:>\s*)?(?:\d+\s)?\|")
_NB_KINDS = (("Type error:", "type-error"), ("Module not found:", "module-not-found"), ("Syntax error:", "syntax-error"))


def next_build(lines: list[str], ctx: Context) -> Result | None:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "Failed to compile."), None)
    if start is None:
        return None
    entries, i = [], start + 1
    while i < len(lines):
        m = _NB_FILE.match(lines[i]) if lines[i].startswith(".") else None
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            break
        text = lines[j].strip()
        kind = "error"
        for prefix, k in _NB_KINDS:
            if text.startswith(prefix):
                kind, text = k, text[len(prefix):].strip()
                break
        frame, k = [], j + 1
        while k < len(lines) and (not lines[k].strip() or _NB_FRAME.match(lines[k])):
            if lines[k].strip():
                frame.append(lines[k])
            k += 1
        f = ctx.own(m.group("file")) or m.group("file")
        loc = f"{f}:{m.group('line')}" if m.group("line") else f
        entries.append(Entry(i, False, loc, None, kind, message(text), tuple(frame[:MAX_EXCERPT])))
        i = k
    return Result(tuple(entries)) if entries else None


PARSERS: tuple = (FuncParser("vitest", vitest), FuncParser("eslint", eslint), FuncParser("tsc", tsc),
                  FuncParser("next-build", next_build))
