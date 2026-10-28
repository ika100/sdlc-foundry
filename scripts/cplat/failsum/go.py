"""Go parsers (service-go): `go test` (panics, build failures), `go build` and golangci-lint v2 (spec 108, t2)."""
from __future__ import annotations

import re

from failsum.core import MAX_EXCERPT, Context, Entry, FuncParser, Result, message

_FAIL = re.compile(r"^(?P<indent>\s*)--- FAIL: (?P<name>\S+)")
_PKG_FAIL = re.compile(r"^FAIL\t(?P<pkg>\S+)")
_END = re.compile(r"^(?:FAIL(?:\t.*)?|ok\s.*|PASS|=== .*|\?\s.*)$")
_GO_MSG = re.compile(r"^\s+(?P<file>[^\s:]+\.go):(?P<line>\d+): ?(?P<msg>.*)$")
_PANIC = re.compile(r"^\s*panic: (?P<msg>.*?)(?: \[recovered\])?$")
_GO_FRAME = re.compile(r"^\t(?P<path>/\S+\.go|\S+\.go):(?P<line>\d+)(?: \+0x[0-9a-f]+)?$")


def go_test(lines: list[str], ctx: Context) -> Result | None:
    fails = [(i, m) for i, ln in enumerate(lines) if (m := _FAIL.match(ln))]
    names = [m.group("name") for _, m in fails]
    entries = []
    for n, (i, m) in enumerate(fails):
        name = m.group("name")
        if any(o.startswith(name + "/") for o in names):
            continue  # the parent of a failing subtest
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if _FAIL.match(lines[j]) or _END.match(lines[j]):
                end = j
                break
        body = lines[i + 1:end]
        pkg = next((p.group("pkg") for ln in lines[end:] if (p := _PKG_FAIL.match(ln))), None)
        tid = f"{pkg}.{name}" if pkg else name
        where, kind, detail, excerpt = None, "fail", "", []
        msgs = [(mm.group("file"), mm.group("line"), mm.group("msg")) for ln in body if (mm := _GO_MSG.match(ln))]
        if msgs:
            where, detail = f"{msgs[0][0]}:{msgs[0][1]}", msgs[0][2]
            excerpt = [ln.strip() for ln in body if _GO_MSG.match(ln)][1:]
        panic = next((p for ln in body if (p := _PANIC.match(ln))), None)
        if panic:
            kind, detail = "panic", panic.group("msg")
            for k, ln in enumerate(body):
                f = _GO_FRAME.match(ln)
                own = ctx.own(f.group("path")) if f else None
                if own:
                    where = where if (where and not msgs) else f"{own}:{f.group('line')}"
                    excerpt = [x.strip() for x in body[k - 1:k + 1]] + excerpt
                    break
        entries.append(Entry(i, True, tid, where or tid, kind, message(detail), tuple(excerpt[:MAX_EXCERPT])))
    return Result(tuple(entries)) if entries else None


_BUILD_HEAD = re.compile(r"^# \S+(?: \[.*\])?$")
_BUILD_LINE = re.compile(r"^(?:vet: )?(?P<file>[^\s:]+\.go):(?P<line>\d+):(?:\d+:)? (?P<msg>.+)$")


def go_build(lines: list[str], ctx: Context) -> Result | None:
    entries, active = [], False
    for i, ln in enumerate(lines):
        if _BUILD_HEAD.match(ln):
            active = True
            continue
        m = _BUILD_LINE.match(ln) if active else None
        if m:
            f = ctx.own(m.group("file")) or m.group("file")
            entries.append(Entry(i, False, f"{f}:{m.group('line')}", None, "compile", message(m.group("msg"))))
        elif not ln.startswith(("\t", " ")) and not ln.startswith("too many errors"):
            active = False
    return Result(tuple(entries)) if entries else None


_LINT = re.compile(r"^(?P<file>[^\s:]+\.go):(?P<line>\d+):(?:\d+:)? (?P<msg>.+) \((?P<linter>[\w-]+)\)$")
_LINT_TOTAL = re.compile(r"^(?P<n>\d+) issues?:")


def golangci(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        t = _LINT_TOTAL.match(ln)
        if t:
            reported = int(t.group("n"))
        m = _LINT.match(ln)
        if not m:
            continue
        frame = []
        for x in lines[i + 1:]:
            if not x.startswith(("\t", " ")) or not x.strip():
                break
            frame.append(x.rstrip())
        f = ctx.own(m.group("file")) or m.group("file")
        entries.append(Entry(i, False, f"{f}:{m.group('line')}", None, m.group("linter"), message(m.group("msg")),
                             tuple(frame[:MAX_EXCERPT])))
    return Result(tuple(entries), reported) if entries else None


PARSERS: tuple = (FuncParser("go-test", go_test), FuncParser("go-build", go_build), FuncParser("golangci-lint", golangci))
