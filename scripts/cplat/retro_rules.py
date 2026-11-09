"""The "Rules to retire" section of the weekly retro (spec 168, AC-168.8).

`section` reads the rule register (docs/rules, spec 168) and the run records of the 4 complete ISO weeks ending with the
covered week, and proposes at most 3 `practice` or `experience` entries that the platform may now retire: one that a
`cplat` command or a CI job enforces, or an `experience` entry whose source issue is closed and whose cause did not occur
in the window. It reads files and the issue states it is given; it writes nothing.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import promptrules
import retro_report
import runs_report

TITLE = "## Rules to retire"
NONE = "none this week"
MAX_ENTRIES = 3
WINDOW_WEEKS = 4
_ISSUE = re.compile(r"#(\d+)")
_SIGNATURE = re.compile(r"^Signature: platform:([0-9a-f]{16})\s*$", re.M)
_CLASSES = ("practice", "experience")


def weeks_of(week: str) -> list[str]:
    """The `WINDOW_WEEKS` complete ISO weeks ending with `week`, oldest first."""
    weeks = [week]
    for _ in range(WINDOW_WEEKS - 1):
        weeks.insert(0, retro_report.previous_week(weeks[0]))
    return weeks


def _window(records: list[dict], week: str) -> tuple[list[dict], list[dict]]:
    """(the records that ended in the window, those of the covered week), each run id once."""
    start = retro_report.week_bounds(weeks_of(week)[0])[0]
    cur_start, end = retro_report.week_bounds(week)
    seen: set = set()
    window: list[dict] = []
    covered: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        rid = r.get("run_id")
        if rid is not None:
            if rid in seen:
                continue
            seen.add(rid)
        ended = runs_report._ts(r.get("ended_at"))
        if ended is None or not start <= ended < end:
            continue
        window.append(r)
        if ended >= cur_start:
            covered.append(r)
    return window, covered


def _reason_of(r: dict) -> str:
    esc = r.get("escalation")
    reason = esc.get("reason") if isinstance(esc, dict) else None
    return reason if isinstance(reason, str) else ""


def _signatures(r: dict) -> set[str]:
    filed = r.get("filed")
    out = set()
    for f in filed if isinstance(filed, list) else []:
        sig = f.get("signature") if isinstance(f, dict) else None
        if isinstance(sig, str):
            out.add(sig.removeprefix("platform:"))
    return out


def _failures(by: str, covered: list[dict], jobs: dict[str, str]) -> int:
    if by.startswith("ci:"):
        job = by[3:].strip()
        name = jobs.get(job, job)

        def hit(check: str) -> bool:
            return check in (job, name) or check.startswith(name + " (")
        return sum(1 for r in covered if any(hit(c) for c in runs_report.red_check_names(r)))
    return sum(1 for r in covered if by in _reason_of(r))


def _occurrences(number: int, body: str, window: list[dict]) -> int:
    m = _SIGNATURE.search(body)
    named = re.compile(rf"#{number}(?!\d)")
    return sum(1 for r in window if (m and m.group(1) in _signatures(r)) or named.search(_reason_of(r)))


def _candidates(root: Path) -> list[tuple[str, promptrules.Entry, promptrules.Sentence]]:
    """(entry key, entry, its sentence) of every `practice` and `experience` entry found in its prompt."""
    try:
        register = promptrules.load_register(root)
    except (promptrules.RegisterError, OSError, ValueError):
        return []
    found = []
    for prompt, entries in register.entries.items():
        try:
            text = (root / prompt).read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        sents = promptrules.sentences(prompt, text)
        for entry in entries:
            if entry.cls not in _CLASSES or not entry.id or not entry.text:
                continue
            wanted = " ".join(entry.text.split())
            sentence = next((s for s in sents if wanted in s.text), None)
            if sentence is not None:
                found.append((f"{prompt}#{entry.id}", entry, sentence))
    return found


def section(root: Path, records: list[dict], *, week: str, issues: Callable[[list[int]], dict[int, dict]]) -> dict:
    root = Path(root)
    window, covered = _window(records, week)
    out: dict = {"weeks": weeks_of(week), "runs": len(window), "entries": []}
    candidates = _candidates(root)
    jobs = promptrules.workflow_jobs(root) if candidates else {}
    valid: dict[str, bool] = {}
    quiet: dict[str, int] = {}
    for key, entry, _ in candidates:
        by = (entry.enforced_by or "").strip()
        if by:
            if by not in valid:
                valid[by] = promptrules.enforcement_error(by, root) is None
        elif entry.cls == "experience" and entry.source and (m := _ISSUE.search(entry.source)):
            quiet[key] = int(m.group(1))
    states = issues(sorted(set(quiet.values()))) if quiet and window else {}
    found = []
    for key, entry, sentence in candidates:
        by = (entry.enforced_by or "").strip()
        if by and valid.get(by):
            evidence = {"kind": "enforced", "by": by, "failures": _failures(by, covered, jobs)}
        elif key in quiet and (state := states.get(quiet[key])) and state.get("state") == "closed":
            n = _occurrences(quiet[key], str(state.get("body") or ""), window)
            if n:
                continue
            evidence = {"kind": "quiet", "issue": quiet[key], "occurrences": n, "runs": len(window)}
        else:
            continue
        found.append({"entry": key, "class": entry.cls, "bytes": len(sentence.text.encode("utf-8")), "text": entry.text,
                      "reason": promptrules.reason_clause(sentence.scope) or "", "evidence": evidence})
    found.sort(key=lambda x: (-x["bytes"], x["entry"]))
    out["entries"] = [{"rank": i, **x} for i, x in enumerate(found[:MAX_ENTRIES], 1)]
    return out


def render(sec: dict) -> str:
    lines = [TITLE]
    entries = sec.get("entries") or []
    weeks = sec.get("weeks") or ["?"]
    if not entries:
        lines.append(NONE)
    for x in entries:
        ev = x["evidence"]
        lines.append(f"{x['rank']}. **{x['entry']}** ({x['class']}, {x['bytes']} bytes): \"{x['text']}\"")
        lines.append(f"   Reason: {x.get('reason') or 'none stated'}")
        if ev.get("kind") == "enforced":
            lines.append(f"   Evidence: enforced by `{ev['by']}`; {ev['failures']} failure(s) of it in {weeks[-1]}")
        else:
            lines.append(f"   Evidence: #{ev['issue']} is closed; its cause occurred in {ev['occurrences']} of {ev['runs']} runs "
                         f"({weeks[0]} to {weeks[-1]})")
    return "\n".join(lines) + "\n"
