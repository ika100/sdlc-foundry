"""Python parsers (service-python, library-python): pytest, pytest-cov, ruff check, ruff format and mypy (spec 108)."""
from __future__ import annotations

import re

from failsum.core import MAX_EXCERPT, Context, Entry, FuncParser, Result, message

_TYPE = r"[A-Za-z_][\w.]*(?:Error|Exception|Failed|Exit|Interrupt)"
_SUMMARY = re.compile(r"^(?P<what>FAILED|ERROR) (?P<id>\S+?)(?: - (?P<msg>.+))?$")
_BLOCK = re.compile(r"^_{2,} (?P<name>.+?) _{2,}$")
_LOC = re.compile(r"^(?P<path>[^\s:]+\.py):(?P<line>\d+):(?: (?P<rest>.*))?$")
_TBLINE = re.compile(rf"^(?P<path>\S+?\.py):(?P<line>\d+): (?P<type>{_TYPE})(?:: (?P<msg>.*))?$")
_TYPED = re.compile(rf"^(?P<type>{_TYPE})(?:: ?(?P<msg>.*))?$")
_E_LINE = re.compile(r"^E +(?P<text>.*)$")
_TOTAL = re.compile(r"(?:^|\s)(?P<counts>\d+ \w+(?:, \d+ \w+)*) in [\d.:]+s")   # one ", " between counts: no backtracking
_SETUP = re.compile(r"^ERROR (?:at (?:setup|teardown) of|collecting) ")


def _reported(lines: list[str]) -> int | None:
    best = None
    for ln in lines:
        m = _TOTAL.search(ln)
        if not m or not re.search(r"failed|errors?\b", m.group("counts")):
            continue
        n = sum(int(c) for c, w in re.findall(r"(\d+) (\w+)", m.group("counts")) if w in ("failed", "error", "errors"))
        best = max(best or 0, n)
    return best


def _blocks(lines: list[str]) -> list[tuple[str, int, list[str]]]:
    out: list[tuple[str, int, list[str]]] = []
    cur: tuple[str, int, list[str]] | None = None
    for i, ln in enumerate(lines):
        m = _BLOCK.match(ln)
        if m:
            cur = (_SETUP.sub("", m.group("name")), i, [])
            out.append(cur)
        elif ln.startswith("==="):
            cur = None
        elif cur is not None:
            cur[2].append(ln)
    return out


def _match(block: str, test_id: str) -> bool:
    tail = test_id.split("::", 1)[1].replace("::", ".") if "::" in test_id else test_id
    last = test_id.split("::")[-1]
    return block in (test_id, tail) or block.split(".")[-1] == last


def pytest(lines: list[str], ctx: Context) -> Result | None:
    failed = []
    for i, ln in enumerate(lines):
        m = _SUMMARY.match(ln)
        if m and ("::" in m.group("id") or ".py" in m.group("id")) and m.group("id") not in [f[1] for f in failed]:
            failed.append((i, m.group("id"), m.group("msg") or ""))
    if not failed:
        return None
    blocks = _blocks(lines)
    used: set[int] = set()
    slots = [(m, i) for i, ln in enumerate(lines) if (m := _TBLINE.match(ln))] if not blocks else []
    pair_slots = len(slots) == len(failed)
    entries = []
    for n, (at, test_id, msg) in enumerate(failed):
        block, start = [], at
        for j, (name, bi, body) in enumerate(blocks):
            if j not in used and _match(name, test_id):
                used.add(j)
                block, start = body, bi
                break
        where, kind, detail, excerpt = None, None, msg, []
        tm = _TYPED.match(msg)
        if tm:
            kind, detail = tm.group("type"), tm.group("msg") or ""
        if block:
            locs = [(m.group("path"), m.group("line"), m.group("rest") or "") for ln in block if (m := _LOC.match(ln))]
            own = [(ctx.own(p), n_) for p, n_, _ in locs if ctx.own(p)]
            if own:
                where = f"{own[-1][0]}:{own[-1][1]}"
            if locs:
                lm = _TYPED.match(locs[-1][2])
                if lm:
                    kind = kind or lm.group("type")
                    detail = detail or lm.group("msg") or ""
            for ln in block:
                m = _E_LINE.match(ln)
                lm = _LOC.match(ln)
                if m:
                    em = _TYPED.match(m.group("text"))
                    if em and not kind:
                        kind = em.group("type")
                    if em and not detail:
                        detail = em.group("msg") or ""
                    excerpt.append(ln)
                elif lm and ctx.own(lm.group("path")):
                    excerpt.append(ln)
        elif pair_slots:
            sm, line_at = slots[n]
            own_path = ctx.own(sm.group("path"))
            if own_path:
                where = f"{own_path}:{sm.group('line')}"
                excerpt.append(lines[line_at])
            kind = kind or sm.group("type")
            detail = detail or sm.group("msg") or ""
        if where is None:
            where = test_id.split("::", 1)[0]
        if not kind:
            kind = "AssertionError" if detail.startswith("assert") else "error"
        entries.append(Entry(start, True, test_id, where, kind, message(detail), tuple(excerpt[:MAX_EXCERPT])))
    return Result(tuple(entries), _reported(lines))


_COV = re.compile(r"^FAIL Required test coverage of (?P<req>[\d.]+)% not reached\. Total coverage: (?P<got>[\d.]+)%")


def pytest_cov(lines: list[str], ctx: Context) -> Result | None:
    for i, ln in enumerate(lines):
        m = _COV.match(ln)
        if m:
            return Result((Entry(i, False, "TOTAL", None, "coverage",
                                 f"total coverage {m.group('got')}% is below the required {m.group('req')}%"),))
    return None


_RUFF_HEAD = re.compile(r"^(?P<code>[A-Z]{1,5}\d{2,4}) (?:\[\*\] )?(?P<msg>.+)$")
_RUFF_AT = re.compile(r"^\s*--> (?P<file>.+?):(?P<line>\d+):(?P<col>\d+)$")
_RUFF_CONCISE = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):(?P<col>\d+): (?P<code>[A-Z]{1,5}\d{2,4}) (?:\[\*\] )?(?P<msg>.+)$")
_RUFF_FRAME = re.compile(r"^\s*(?:\d+ )?\|\s*\S")
_RUFF_TOTAL = re.compile(r"^Found (?P<n>\d+) errors?\.$")


def ruff(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        t = _RUFF_TOTAL.match(ln)
        if t:
            reported = int(t.group("n"))
        c = _RUFF_CONCISE.match(ln)
        if c:
            f = ctx.own(c.group("file")) or c.group("file")
            entries.append(Entry(i, False, f"{f}:{c.group('line')}", None, c.group("code"), message(c.group("msg"))))
            continue
        h = _RUFF_HEAD.match(ln)
        a = _RUFF_AT.match(lines[i + 1]) if h and i + 1 < len(lines) else None
        if h and a:
            f = ctx.own(a.group("file")) or a.group("file")
            frame = []
            for x in lines[i + 2:]:
                if not x.strip():
                    break
                if _RUFF_FRAME.match(x):
                    frame.append(x)
            entries.append(Entry(i, False, f"{f}:{a.group('line')}", None, h.group("code"), message(h.group("msg")),
                                 tuple(frame[:MAX_EXCERPT])))
    return Result(tuple(entries), reported) if entries else None


_FORMAT_FILE = re.compile(r"^Would reformat: (?P<file>.+)$")
_FORMAT_TOTAL = re.compile(r"^(?P<n>\d+) files? would be reformatted")


def ruff_format(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        m = _FORMAT_FILE.match(ln)
        if m:
            entries.append(Entry(i, False, ctx.own(m.group("file")) or m.group("file"), None, "format", "would be reformatted"))
        t = _FORMAT_TOTAL.match(ln)
        if t:
            reported = int(t.group("n"))
    return Result(tuple(entries), reported) if entries else None


_MYPY = re.compile(r"^(?P<file>[^\s:]+\.pyi?):(?P<line>\d+)(?::\d+)?: error: (?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$")
_MYPY_NOTE = re.compile(r"^[^\s:]+\.pyi?:\d+(?::\d+)?: note: ")
_MYPY_TOTAL = re.compile(r"^Found (?P<n>\d+) errors? in \d+ files?")


def mypy(lines: list[str], ctx: Context) -> Result | None:
    entries, reported = [], None
    for i, ln in enumerate(lines):
        t = _MYPY_TOTAL.match(ln)
        if t:
            reported = int(t.group("n"))
        m = _MYPY.match(ln)
        if not m:
            continue
        notes, j = [], i + 1
        while j < len(lines) and _MYPY_NOTE.match(lines[j]):
            notes.append(lines[j])
            j += 1
        f = ctx.own(m.group("file")) or m.group("file")
        entries.append(Entry(i, False, f"{f}:{m.group('line')}", None, m.group("code") or "error", message(m.group("msg")),
                             tuple(notes[:MAX_EXCERPT])))
    return Result(tuple(entries), reported) if entries else None


PARSERS: tuple = (FuncParser("pytest", pytest), FuncParser("pytest-cov", pytest_cov), FuncParser("ruff", ruff),
                  FuncParser("ruff-format", ruff_format), FuncParser("mypy", mypy))
