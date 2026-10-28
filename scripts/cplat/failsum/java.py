"""Java parsers (service-java): Maven Surefire, the Maven compiler, Checkstyle, Spotless and the JaCoCo check (spec 108, t2)."""
from __future__ import annotations

import re

from failsum.core import MAX_EXCERPT, Context, Entry, FuncParser, Result, message

_PREFIX = r"^(?:\[(?:ERROR|WARN|WARNING|INFO)\] ?)?"
_HEAD = re.compile(_PREFIX + r"(?P<id>[\w.$]+(?:\([^)]*\))?)\s+Time elapsed: .*<<< (?:FAILURE|ERROR)!$")
_TYPE = re.compile(r"^(?P<type>[A-Za-z_][\w.$]*)(?:: ?(?P<msg>.*))?$")
_FRAME = re.compile(r"^\s+at (?P<frame>\S+)\((?P<file>[^:)]+):(?P<line>\d+)\)$")
_RUNS = re.compile(r"Tests run: \d+, Failures: (?P<f>\d+), Errors: (?P<e>\d+)")
_LISTED = re.compile(_PREFIX + r"\s+(?P<id>\w[\w.$]*\.\w+):(?P<line>\d+)\s+(?:» (?P<type>\S+)\s+)?(?P<msg>.*)$")


def _surefire_reported(lines: list[str]) -> int | None:
    best = None
    for ln in lines:
        m = _RUNS.search(ln)
        if m:
            n = int(m.group("f")) + int(m.group("e"))
            if n:
                best = max(best or 0, n)
    return best


def surefire(lines: list[str], ctx: Context) -> Result | None:
    entries = []
    for i, ln in enumerate(lines):
        h = _HEAD.match(ln)
        if not h:
            continue
        kind, detail, where, excerpt = "error", "", None, []
        if i + 1 < len(lines):
            t = _TYPE.match(lines[i + 1].strip())
            if t and not _FRAME.match(lines[i + 1]):
                kind, detail = t.group("type"), t.group("msg") or ""
        for x in lines[i + 2:]:
            f = _FRAME.match(x)
            if not f:
                if x.strip() and not x.startswith(("\t", " ")) or not x.strip():
                    break
                continue
            if ctx.own_java_frame(f.group("frame")):
                if where is None:
                    where = f"{f.group('file')}:{f.group('line')}"
                if len(excerpt) < MAX_EXCERPT:
                    excerpt.append(x.strip())
        entries.append(Entry(i, True, h.group("id"), where or h.group("id"), kind,
                             message(detail), tuple(excerpt)))
    if not entries:
        # no stack-trace blocks: fall back to the `Failures:` / `Errors:` summary lists
        in_list = False
        for i, ln in enumerate(lines):
            if re.match(_PREFIX + r"(?:Failures|Errors):$", ln):
                in_list = True
                continue
            m = _LISTED.match(ln) if in_list else None
            if m:
                tid = m.group("id")
                entries.append(Entry(i, True, tid, f"{tid.rsplit('.', 2)[-2]}.java:{m.group('line')}",
                                     m.group("type") or "AssertionError", message(m.group("msg"))))
            elif in_list and not ln.strip().startswith(("[ERROR]   ", "[ERROR]  ")):
                in_list = False
    return Result(tuple(entries), _surefire_reported(lines)) if entries else None


_JAVAC = re.compile(_PREFIX + r"(?P<file>\S+\.java):\[(?P<line>\d+),(?P<col>\d+)\] (?P<msg>.+)$")
_CHECKSTYLE_TAIL = re.compile(r"^\(\w+\) \w+: ")
_DETAIL = re.compile(r"^\s{2,}(?:symbol|location|required|found|reason):")


def javac(lines: list[str], ctx: Context) -> Result | None:
    entries = []
    for i, ln in enumerate(lines):
        m = _JAVAC.match(ln)
        if not m or _CHECKSTYLE_TAIL.match(m.group("msg")):
            continue
        extra = []
        for x in lines[i + 1:]:
            if not _DETAIL.match(x):
                break
            extra.append(x.strip())
        f = ctx.own(m.group("file")) or m.group("file")
        entries.append(Entry(i, False, f"{f}:{m.group('line')}", None, "compile", message(m.group("msg")),
                             tuple(extra[:MAX_EXCERPT])))
    return Result(tuple(entries)) if entries else None


_CHECKSTYLE = re.compile(_PREFIX + r"(?P<file>\S+\.java):\[(?P<line>\d+)(?:,\d+)?\] \((?P<cat>\w+)\) (?P<rule>\w+): (?P<msg>.*)$")
_CS_TOTAL = re.compile(r"You have (?P<n>\d+) Checkstyle violations?")


def checkstyle(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        t = _CS_TOTAL.search(ln)
        if t:
            reported = int(t.group("n"))
        m = _CHECKSTYLE.match(ln)
        if m:
            f = ctx.own(m.group("file")) or m.group("file")
            entries.append(Entry(i, False, f"{f}:{m.group('line')}", None, m.group("rule"), message(m.group("msg"))))
    return Result(tuple(entries), reported) if entries else None


_SPOTLESS_HEAD = "The following files had format violations:"
_SPOTLESS_FILE = re.compile(r"^(?:\[\w+\] )?    (?P<file>\S.*)$")
_SPOTLESS_BODY = re.compile(r"^(?:\[\w+\] )?\s{5,}(?P<text>.*)$")
_HUNK = re.compile(r"^@@ -(?P<line>\d+)")
_SPOTLESS_TOTAL = re.compile(r"(?P<n>\d+) needs changes to be clean")


def spotless(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        t = _SPOTLESS_TOTAL.search(ln)
        if t:
            reported = int(t.group("n"))
        if _SPOTLESS_HEAD not in ln:
            continue
        cur: list | None = None
        for j in range(i + 1, len(lines)):
            f = _SPOTLESS_FILE.match(lines[j])
            body = _SPOTLESS_BODY.match(lines[j])
            if f and not body:
                cur = [j, ctx.own(f.group("file")) or f.group("file"), None, []]
                entries.append(cur)
            elif body and cur is not None:
                text = body.group("text")
                h = _HUNK.match(text)
                if h and cur[2] is None:
                    cur[2] = h.group("line")
                elif text.startswith(("-", "+")) and len(cur[3]) < MAX_EXCERPT:
                    cur[3].append(text)
            else:
                break
    out = [Entry(j, False, f"{f}:{ln}" if ln else f, None, "spotless", "needs formatting", tuple(ex)) for j, f, ln, ex in entries]
    return Result(tuple(out), reported) if out else None


_JACOCO = re.compile(
    _PREFIX + r"Rule violated for (?P<scope>\w+) (?P<name>.+?): (?P<what>[\w ]+?) is (?P<got>[\d.]+), but expected (?P<kind>minimum|maximum) is (?P<req>[\d.]+)")


def jacoco(lines: list[str], ctx: Context) -> Result | None:
    entries = []
    for i, ln in enumerate(lines):
        m = _JACOCO.match(ln)
        if m:
            bound = "below the required" if m.group("kind") == "minimum" else "above the allowed"
            entries.append(Entry(i, False, m.group("name"), None, "coverage",
                                 f"{m.group('what')} {m.group('got')} is {bound} {m.group('req')}"))
    return Result(tuple(entries)) if entries else None


PARSERS: tuple = (FuncParser("surefire", surefire), FuncParser("javac", javac), FuncParser("checkstyle", checkstyle),
                  FuncParser("spotless", spotless), FuncParser("jacoco", jacoco))
