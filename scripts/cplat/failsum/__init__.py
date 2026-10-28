"""Failure summaries for fix rounds (spec 108, ADR-071): a failing check reaches an agent as a compact, rule-made summary.

`summarize` reads a local log (split into checks at devbox's script markers), `summarize_ci` the saved logs of failed CI checks.
`Summary.render()` is the text an agent sees, `Summary.normalized()` the failure of record for spec 102's no-progress check.
Fixed rules only: no model, no network, no clock. One parser per tool output format lives in the sibling modules; anything
unread is `format: unknown` with the last 40 lines. This package imports neither `budget`, `ship` nor `runs`.
"""
from __future__ import annotations

import json
from pathlib import Path

from failsum import docker, gitops, go, java, python, web
from failsum.core import (FORMAT_UNKNOWN, MAX_ENTRIES, MAX_EXCERPT, MAX_LINES, MIN_TAIL, TAIL, Check, CiCheck, Context, Entry,
                          Parser, Result, Summary, build_check, ci_check, clean_lines, message, normalise, raw, segments)

__all__ = ["FORMAT_UNKNOWN", "MAX_ENTRIES", "MAX_EXCERPT", "MAX_LINES", "MIN_TAIL", "TAIL", "Check", "CiCheck", "Context", "Entry",
           "Parser", "Result", "Summary", "PARSERS", "enabled", "message", "normalise", "raw", "read_sidecar", "sidecar",
           "summarize", "summarize_ci", "write_sidecar"]

PARSERS: tuple = tuple(p for mod in (python, java, go, web, gitops, docker) for p in mod.PARSERS)


def enabled(repo: Path) -> tuple[bool, str]:
    """(on, reason) from the project setting `failure_summary`; the reason is empty when summaries are on."""
    import settings
    return settings.failure_summary(Path(repo))


def summarize(text: str, *, title: str, check: str, command: str, exit_code: int, log: Path, root: Path | None) -> Summary:
    """Summarize a local log: one check per devbox script segment that has entries, and always the last non-empty one."""
    ctx = Context(Path(root) if root else None)
    segs = segments(clean_lines(text), check)
    checks = []
    for i, (name, lines, marked) in enumerate(segs):
        cmd = f"devbox run {name}" if marked else command
        c = build_check(name, cmd, str(exit_code), str(log), lines, ctx, PARSERS)
        if c.entries or i == len(segs) - 1:
            checks.append(c)
    return Summary(title, checks)


def summarize_ci(title: str, checks: list[CiCheck], *, root: Path | None) -> Summary:
    """Summarize the failed checks of a CI run, in the given order; a check without a log still gets its header."""
    ctx = Context(Path(root) if root else None)
    return Summary(title, [ci_check(c, ctx, PARSERS) for c in checks])


def sidecar(log: Path) -> Path:
    return Path(str(log) + ".summary.json")


def write_sidecar(log: Path, s: Summary) -> None:
    """Keep the printed summary next to the log for `cplat budget attempt --error-file`; never raises."""
    try:
        sidecar(log).write_text(json.dumps({"text": s.render(), "normalized": s.normalized()}))
    except Exception:  # noqa: BLE001  (a missing sidecar only costs the reuse, never the run)
        pass


def read_sidecar(log: Path) -> dict | None:
    try:
        data = json.loads(sidecar(Path(log)).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "text" in data and "normalized" in data else None
