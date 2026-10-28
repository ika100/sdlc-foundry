"""The failure-summary core (spec 108, ADR-071): model, own-code paths, segments, deduplication, limits, render, redaction.

It never knows a tool: parsers (one per tool output format, in the sibling modules) turn log lines into `Entry` values.
Pure and deterministic: the same log gives the same bytes. Nothing here reads a clock, a network or a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import feedback

MAX_ENTRIES = 20
MAX_EXCERPT = 10
MAX_LINES = 80
TAIL = 40
MIN_TAIL = 10
FORMAT_UNKNOWN = "unknown"

# ---------------- normalise (moved unchanged from budget, spec 102) ----------------

_NORMALISE = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), ""),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), ""),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|m)\b"), ""),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"(?:\.{0,2}/)?(?:[\w.~@+-]+/)+[\w.~@+-]+"), "<path>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,}\b"), "<id>"),
    (re.compile(r"(?i)\bline \d+"), "line"),
    (re.compile(r"(?<=[\w>]):\d+(?::\d+)?\b"), ""),
]


def normalise(text: str) -> str:
    """The error without what changes between equivalent runs: times, paths, ids, line numbers, whitespace."""
    for pattern, repl in _NORMALISE:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")


def message(text: str) -> str:
    """An entry's message: `normalise`, and every remaining number as `<n>` (so equal findings compare equal)."""
    return _NUMBER.sub("<n>", normalise(text))


# ---------------- model ----------------

@dataclass(frozen=True)
class Entry:
    at: int
    test: bool
    locator: str
    where: str | None
    kind: str
    message: str
    excerpt: tuple[str, ...] = ()
    count: int = 1
    lines: tuple[int, ...] = ()


@dataclass(frozen=True)
class Result:
    entries: tuple[Entry, ...]
    reported: int | None = None


class Parser(Protocol):
    name: str

    def parse(self, lines: list[str], ctx: "Context") -> Result | None: ...


@dataclass(frozen=True)
class FuncParser:
    """A parser made of a name and a function `(lines, ctx) -> Result | None`."""
    name: str
    fn: Callable[[list[str], "Context"], "Result | None"]

    def parse(self, lines: list[str], ctx: "Context") -> Result | None:
        return self.fn(lines, ctx)


_BAD_PARTS = frozenset({".venv", "venv", "site-packages", "dist-packages", "node_modules", "vendor", "target", ".devbox"})
_WORKSPACE = re.compile(r"^.*?/_?work/([^/]+)/\1/(.+)$")
_FOREIGN_JAVA = ("java.", "javax.", "jdk.", "sun.", "org.junit.", "org.opentest4j.", "org.mockito.", "org.assertj.",
                 "org.springframework.", "org.apache.maven.")


@dataclass(frozen=True)
class Context:
    root: Path | None = None

    def own(self, path: str) -> str | None:
        """The relative own-code path, or None for library, tool and unknown absolute paths."""
        p = path.strip()
        if not p or p.startswith("<"):
            return None
        while p.startswith("./"):
            p = p[2:]
        if p.startswith("/"):
            rel = None
            if self.root is not None:
                for r in (str(self.root), str(self.root.resolve())):
                    prefix = r.rstrip("/") + "/"
                    if p.startswith(prefix):
                        rel = p[len(prefix):]
                        break
            if rel is None:
                m = _WORKSPACE.match(p)
                if m:
                    rel = m.group(2)
            if rel is None:
                return None
            p = rel
        if not p or any(part in _BAD_PARTS for part in p.split("/")) or "go/pkg/mod/" in p:
            return None
        return p

    def own_java_frame(self, frame: str) -> bool:
        """`at a.b.C.m(C.java:12)`: False for JDK, test-framework, Spring and Maven frames."""
        name = re.sub(r"^\s*at\s+", "", frame.strip())
        return not name.startswith(_FOREIGN_JAVA)


@dataclass(frozen=True)
class CiCheck:
    name: str
    link: str
    log: Path | None
    text: str | None


@dataclass(frozen=True)
class Check:
    name: str
    command: str
    exit: str
    log: str
    formats: tuple[str, ...]
    entries: tuple[Entry, ...]
    reported: int | None
    tail: tuple[str, ...]
    read: int = 0


# ---------------- text preparation ----------------

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_MARKER = re.compile(r'^Info: Running script "(?P<name>[^"]+)"')
_CI_PREFIX = re.compile(r"^(?P<job>[^\t]*)\t(?P<step>[^\t]*)\t﻿?\d{4}-\d{2}-\d{2}T[\d:.]+Z ?")
_EXIT_CODE = re.compile(r"Process completed with exit code (\d+)")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def clean_lines(text: str) -> list[str]:
    return [ln.rstrip() for ln in strip_ansi(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")] if text else []


def segments(lines: list[str], default: str) -> list[tuple[str, list[str] | None, bool]]:
    """(name, lines, marked): the text between devbox script markers, named by the first marker; no marker: one segment."""
    out: list[tuple[str, list[str], bool]] = []
    name, cur, marked = default, [], False
    for ln in lines:
        m = _MARKER.match(ln)
        if m:
            out.append((name, cur, marked))
            name, cur, marked = m.group("name"), [], True
        else:
            cur.append(ln)
    out.append((name, cur, marked))
    return [(n, ls, mk) for n, ls, mk in out if any(x.strip() for x in ls)] or [(default, [], False)]


def _tail_of(lines: list[str]) -> tuple[str, ...]:
    kept = list(lines)
    while kept and not kept[-1].strip():
        kept.pop()
    return tuple(kept[-TAIL:])


def dedup(entries: list[Entry]) -> list[Entry]:
    """Findings with the same file, kind and message become one entry at the first location (tests never merge)."""
    out: list[Entry] = []
    index: dict[tuple[str, str, str], int] = {}
    for e in entries:
        if e.test:
            out.append(e)
            continue
        m = re.match(r"^(.*):(\d+)$", e.locator)
        file, line = (m.group(1), int(m.group(2))) if m else (e.locator, None)
        key = (file, e.kind, e.message)
        if key not in index:
            index[key] = len(out)
            out.append(e)
            continue
        first = out[index[key]]
        more = first.lines + ((line,) if line is not None and len(first.lines) < 10 else ())
        out[index[key]] = Entry(first.at, first.test, first.locator, first.where, first.kind, first.message, first.excerpt,
                                first.count + 1, more)
    return out


def build_check(name: str, command: str, exit_code: str, log: str, lines: list[str], ctx: Context, parsers) -> Check:
    found: list[tuple[str, Result]] = []
    for p in parsers:
        try:
            r = p.parse(lines, ctx)
        except Exception:  # noqa: BLE001  (a parser that breaks on odd output degrades to the unknown format)
            r = None
        if r is not None and r.entries:
            found.append((p.name, r))
    raw = sorted((e for _, r in found for e in r.entries), key=lambda e: e.at)
    reported = [r.reported for _, r in found if r.reported is not None]
    entries = tuple(dedup(raw))
    return Check(name, command, exit_code, log, tuple(n for n, _ in found) if entries else (), entries,
                 max(reported) if reported and entries else None, _tail_of(lines), len(raw))


def ci_check(c: CiCheck, ctx: Context, parsers) -> Check:
    log = str(c.log) if c.log is not None else f"none (not a GitHub Actions run: {c.link})"
    lines, step, code = [], None, "?"
    for ln in clean_lines(c.text or ""):
        m = _CI_PREFIX.match(ln)
        if m:
            ln = ln[m.end():]
            col = m.group("step")
        else:
            col = None
        if ln.startswith(("##[group]", "##[endgroup]")):
            continue
        if ln.startswith("##[error]"):
            ln = ln[len("##[error]"):]
            if step is None:
                step = col
        e = _EXIT_CODE.search(ln)
        if e:
            code = e.group(1)
        lines.append(ln)
    command = f"{c.name} / {step}" if step else c.name
    return build_check(c.name, command, code, log, lines, ctx, parsers)


# ---------------- render ----------------

@dataclass
class Summary:
    title: str
    checks: list[Check] = field(default_factory=list)

    def render(self) -> str:
        for ec, tl, sh in _schedule():
            lines = self._lines(ec, tl, sh)
            if len(lines) <= MAX_LINES:
                break
        keep = {c.log for c in self.checks if c.log and not c.log.startswith("none")}
        return "\n".join(_redact(ln, keep) for ln in lines)

    def normalized(self) -> str:
        out = []
        for c in self.checks:
            if c.entries:
                out.extend(f"{c.name}|{e.kind}|{e.message}" for e in c.entries)
            else:
                out.append(f"{c.name}|{FORMAT_UNKNOWN}|{normalise(chr(10).join(c.tail))}")
        return "\n".join(out)

    def _lines(self, ec: int, tl: int, sh: int) -> list[str]:
        out = [self.title]
        for c in self.checks:
            head = (f"== check: {c.name} | format: {', '.join(c.formats) or FORMAT_UNKNOWN} | command: {c.command} "
                    f"| exit: {c.exit} | log: {c.log}")
            if not c.entries:
                out.append(head)
                out.extend(c.tail[-tl:] if c.tail else ["(no output)"])
                continue
            out.append(f"{head} | entries: {len(c.entries)}")
            for e in c.entries[:sh]:
                loc = f"{e.locator} at {e.where}" if e.test and e.where else e.locator
                line = f"- {loc} | {e.kind} | {e.message}"
                if e.count > 1:
                    line += f" | x{e.count}" + (f" (lines {', '.join(str(n) for n in e.lines)})" if e.lines else "")
                out.append(line)
                out.extend(f"    > {x}" for x in e.excerpt[:ec])
            rest = len(c.entries) - min(len(c.entries), sh)
            if rest:
                out.append(f"- ... {rest} more entries not shown (log: {c.log})")
            if c.reported is not None and c.reported > c.read:
                out.append(f"  (the tool reports {c.reported} failures, {c.read} read; last lines of the check:)")
                out.extend(c.tail[-tl:])
        return out


def _schedule():
    for ec in range(MAX_EXCERPT, -1, -1):
        yield ec, TAIL, MAX_ENTRIES
    for sh in range(MAX_ENTRIES, 0, -1):
        yield 0, MIN_TAIL, sh


def _redact(line: str, keep: set[str]) -> str:
    hits = [k for k in sorted(keep, key=len, reverse=True) if k in line]
    if not hits:
        return feedback.redact(line)
    parts = [line]
    for k in hits:
        parts = [q for p in parts for q in _split_keep(p, k)]
    return "".join(p if p in keep else feedback.redact(p) for p in parts)


def _split_keep(text: str, key: str) -> list[str]:
    if text in (key,) or key not in text:
        return [text]
    out: list[str] = []
    for i, piece in enumerate(text.split(key)):
        if i:
            out.append(key)
        if piece:
            out.append(piece)
    return out


def raw(title: str, text: str, reason: str, tail: int = TAIL) -> str:
    """The summaries-off rendering of a local log: the title, the reason, the last lines."""
    return "\n".join([title, f"summaries: off ({reason})", *text.splitlines()[-tail:]])
