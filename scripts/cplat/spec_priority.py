"""A spec's priority and where it came from (spec 196): resolved by `spec new`, proposed or changed by `spec priority`.

The provenance is the last `priority …` line of the spec's Changelog; `state` reads it back for `show` and `list --json`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import core
import priority
from core import PlatformError

LINE = re.compile(r"^- \d{4}-\d{2}-\d{2} (priority (P[0-2]) (proposed: (.+)|given by you|changed by you|set on the issue #\d+.*))\s*$")
APPROVED = re.compile(r"^- \d{4}-\d{2}-\d{2} approved(?: by (.+?))?[;\s]*$")


def headless() -> bool:
    return os.environ.get("CPLAT_HEADLESS") == "1"


def _changelog(body: str) -> list[str]:
    import spec
    return spec.sections(body).get("changelog", "").splitlines()


def state(spec) -> dict:
    """`{"state", "reason", "decide"}` from the last priority line: proposed (approved once the user approved the spec),
    given, changed, issue, or unset."""
    import claim
    found, approved = None, False
    for ln in _changelog(spec.body):
        if m := LINE.match(ln):
            found, approved = m, False
        elif found and (a := APPROVED.match(ln)) and a.group(1) != claim.DISPATCH:
            approved = True
    if not found:
        return {"state": "unset", "reason": "", "decide": False}
    text = found.group(3)
    if text.startswith("proposed: "):
        return {"state": "approved" if approved else "proposed", "reason": found.group(4), "decide": False}
    if text == "given by you":
        return {"state": "given", "reason": text, "decide": False}
    if text == "changed by you":
        return {"state": "changed", "reason": text, "decide": False}
    return {"state": "issue", "reason": text, "decide": text.endswith(": decide)")}


def _labels(root: Path, issue: int) -> list[str] | None:
    res = core.run(["gh", "issue", "view", str(issue), "--json", "labels"], cwd=root, check=False)
    if res.returncode != 0:
        return None
    try:
        return [str(x["name"]) for x in json.loads(res.stdout).get("labels", [])]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def _from_issues(root: Path, tracks: list[int]) -> tuple[str, int, list[str]] | None:
    """The most urgent level of the tracked issues' labels, its issue and every level found."""
    by_issue: dict[int, set[str]] = {}
    for n in tracks:
        labels = _labels(root, n)
        if labels is None:
            print(f"note: could not read the labels of #{n}; the priority is a proposal", file=sys.stderr)
            continue
        by_issue[n] = {priority.level_of(lb) for lb in labels if priority.level_of(lb) in priority.LEVELS}
    found = {lv for lvs in by_issue.values() for lv in lvs}
    for level in priority.LEVELS:
        if level in found:
            first = next(n for n, lvs in by_issue.items() if level in lvs)
            return level, first, [priority.label_of(lv) for lv in priority.LEVELS if lv in found]
    return None


def resolve(root: Path, given: str | None, tracks: list[int], headless: bool) -> tuple[str, str]:
    """The level of a new spec and its Changelog line, in the order given option, tracked issues' labels, fallback."""
    if given:
        return given, (f"priority {given} proposed: {given}: named in the request" if headless else f"priority {given} given by you")
    if tracks and (hit := _from_issues(root, tracks)):
        level, n, levels = hit
        if headless:
            return level, f"priority {level} proposed: {level}: set on the issue #{n}"
        more = f" ({', '.join(levels)}: decide)" if len(levels) > 1 else ""
        return level, f"priority {level} set on the issue #{n}{more}"
    return "P1", f"priority P1 proposed: {priority.FALLBACK_REASON}"


def _replace_last(body: str, new_line: str | None) -> str:
    """Replace the last priority line of the Changelog with `new_line`, or append one after the last entry."""
    import spec
    lines = body.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if LINE.match(lines[i]):
            lines[i] = f"- {spec.today()} {new_line}"
            return "\n".join(lines)
    return spec.add_changelog(body, new_line)


def _row(sp, written: bool) -> dict:
    st = state(sp)
    return {"id": sp.id, "priority": sp.meta.get("priority", ""), "priority_state": st["state"],
            "priority_reason": st["reason"], "written": written}


def _is_definition(level: str, reason: str) -> bool:
    return reason == priority.FALLBACK_REASON or priority.proposal_reason_ok(level, reason)


def set_priority(sp, level: str, propose: str | None, as_json: bool) -> int:
    import spec
    if propose is not None and not priority.proposal_reason_ok(level, propose):
        raise PlatformError(f'the reason must be "{level}: <phrase>", one of: ' + ", ".join(priority.LEVELS[level]["phrases"]),
                            hint="pick the phrase of the level that names why")
    st = state(sp)
    current = sp.meta.get("priority", "")
    if propose is not None:
        if sp.status == "draft" and st["state"] == "proposed" and _is_definition(current, st["reason"]):
            sp.meta["priority"] = level
            spec.save(sp.dir / "spec.md", sp.meta, _replace_last(sp.body, f"priority {level} proposed: {propose}"))
            sp = spec.read(sp.dir)
            print(json.dumps(_row(sp, True), indent=2) if as_json else f"{sp.id}: priority {level} proposed ({propose})")
            return 0
        if as_json:
            print(json.dumps(_row(sp, False), indent=2))
        else:
            print(f"{sp.id}: priority kept {current} ({st['reason']}); a proposal replaces only a proposal")
        return 0
    if headless():
        raise PlatformError("a priority change needs the user", hint="run it in a Claude Code session")
    if sp.status in {"done", "superseded"}:
        raise PlatformError(f"{sp.id} is '{sp.status}', its priority is no longer changed", hint="amend or supersede with a new spec")
    if current == level and st["state"] != "proposed":
        print(json.dumps(_row(sp, False), indent=2) if as_json else f"{sp.id}: priority already {level}")
        return 0
    sp.meta["priority"] = level
    spec.save(sp.dir / "spec.md", sp.meta, spec.add_changelog(sp.body, f"priority {level} changed by you"))
    sp = spec.read(sp.dir)
    print(json.dumps(_row(sp, True), indent=2) if as_json else f"{sp.id}: priority {level} (changed by you)")
    return 0


def add_parser(sub) -> None:
    p = sub.add_parser("priority", help="propose (--propose REASON) or change a spec's priority (spec 196)")
    p.add_argument("id")
    p.add_argument("level", type=str.upper, choices=sorted(priority.LEVELS))
    p.add_argument("--propose", metavar="REASON", help='a proposal "<P>: <phrase>"; replaces only a proposal')
    p.add_argument("--json", action="store_true")
