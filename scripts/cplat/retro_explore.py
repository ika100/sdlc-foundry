"""The retro's Explore section (spec 188): explored vs other specs since the release that ships explore, and the kill rule.

The section holds counts and means only; it changes nothing itself."""
from __future__ import annotations

import datetime
import re

import spec as specmod

_RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})\s*$", re.M)
_LOG = re.compile(r"^\s*[-*]\s+(\d{4}-\d{2}-\d{2})\s+(\S+)", re.M)
_NOT_AMENDMENTS = {"created", "approved", "building", "done", "draft", "superseded"}
_DAYS = 42
_MIN_EXPLORED = 5
_KILL = "kill rule met: retire /component:explore and /system:explore as tombstones (your decision)"


def release(changelog_text: str) -> dict | None:
    """The oldest released section whose text names `/component:explore`."""
    marks = list(_RELEASE.finditer(changelog_text))
    found = [(m.group(2), m.group(1)) for i, m in enumerate(marks)
             if "/component:explore" in changelog_text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(changelog_text)]]
    if not found:
        return None
    date, version = min(found)
    return {"version": version, "date": date}


def _log(spec) -> tuple[datetime.date | None, int]:
    """(created date, amendment count) from the spec's Changelog."""
    created, amendments = None, 0
    for m in _LOG.finditer(specmod.sections(spec.body).get("changelog", "")):
        word = m.group(2).rstrip(":").lower()
        if word == "created" and created is None:
            created = datetime.date.fromisoformat(m.group(1))
        elif word not in _NOT_AMENDMENTS:
            amendments += 1
    return created, amendments


def _mean(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _group(rows: list[tuple[int, int]]) -> dict:
    return {"count": len(rows), "revised_assumptions_mean": _mean([r for r, _ in rows]), "amendments_mean": _mean([a for _, a in rows])}


def section(specs, changelog_text: str, until: datetime.date) -> dict:
    rel = release(changelog_text)
    if rel is None:
        return {"release": None}
    start = datetime.date.fromisoformat(rel["date"])
    due = start + datetime.timedelta(days=_DAYS)
    explored: list[tuple[int, int]] = []
    other: list[tuple[int, int]] = []
    for s in specs:
        try:
            created, amendments = _log(s)
        except ValueError:
            continue
        if created is None or not start <= created <= until:
            continue
        (explored if s.meta.get("explored") is True else other).append((len(s.assumptions(revised=True)), amendments))
    ex, ot = _group(explored), _group(other)
    met = until >= due and (ex["count"] < _MIN_EXPLORED or ex["revised_assumptions_mean"] is None
                            or ot["revised_assumptions_mean"] is None or ex["amendments_mean"] is None or ot["amendments_mean"] is None
                            or ex["revised_assumptions_mean"] >= ot["revised_assumptions_mean"])
    return {"release": rel, "explored": ex, "other": ot, "kill_rule": {"due": due.isoformat(), "met": met},
            "until": until.isoformat()}


def _cell(v: float | None) -> str:
    return "none" if v is None else f"{v:.2f}"


def render(sec: dict) -> str:
    out = ["## Explore"]
    rel = sec.get("release")
    if rel is None:
        return "\n".join(out + ["explore not released yet"]) + "\n"
    out += [f"explored vs other specs created since {rel['version']} ({rel['date']})",
            "| specs | count | mean revised assumptions | mean amendments |", "|---|---|---|---|"]
    for name in ("explored", "other"):
        g = sec[name]
        out.append(f"| {name} | {g['count']} | {_cell(g['revised_assumptions_mean'])} | {_cell(g['amendments_mean'])} |")
    kill = sec["kill_rule"]
    if kill["met"]:
        out.append(_KILL)
    elif sec["until"] >= kill["due"]:
        out.append("kill rule: not met")
    else:
        out.append(f"kill rule: checked from {kill['due']}")
    return "\n".join(out) + "\n"
