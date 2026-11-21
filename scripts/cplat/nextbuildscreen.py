"""`cplat next` text of the build screens (spec 193): the lines of part 2 and `Your part:` for the build start, the set-up, the
progress, the stops, the raise confirmation, the log, the release and end of build, the promote and the last screen, as pure
functions of the `build` document (`nextbuild.collect`) and the judgement. Nothing here does any I/O.

Public API (every `*_lines` returns the lines as written, with their leading spaces; `nextscreen` wraps them to 80 columns,
puts them through `nextstate.plain` and ASCII):
- `build_lines(b, given)`: the queue, the total, the tokens line. `setup_lines(b, given)`: the queue and the set-up offer.
  `setup_details(b)`: the details of the set-up (the file it commits).
- `progress_lines(b, given)`: the head, the newest 5 event lines, `Building now:`.
- `stop_lines(item, b, given, bang)`: the block of one stopped item that has a `stop`.
- `raise_lines(b, value)`: the raise confirmation of `--show raise-budget:<value>`. `log_lines(item, key)`: `--show log:<key>`.
- `release_lines(item)`: `A release is ready: ...` and `Ready to release:` with the sections. `end_lines(b, sections)`: the end-of-build
  head. `promote_lines(item)`: staging and prod. `last_lines(b)`: the last screen.
- `your_part(case, channels=None)`: the `Your part:` line of a case (`build`, `setup`, `progress`, `stop`, `release`, `promote`,
  `last`, `raise`, `raise-invalid`, `log`).
- `given_of(judgement)`: the `items` of the judgement file (`{"<key>": {"you_get", "what_happened", "why_ask"}}`).
- `duration(minutes)`, `age(minutes)`, `count(n)`: the formats (`1 h 35 min`, `2 h 05 min`, `4,200,000`).
- `ref_of(key)`, `name_of(key, text, given)`: item words.
"""
from __future__ import annotations

import re

LIMIT = 5
EVENT_LIMIT = 5
_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
ASK_MINUTES = 5


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def count(n: int) -> str:
    """A number with thousands separators."""
    return f"{int(n):,}"


def duration(minutes: int | float) -> str:
    """A time of work: `45 min`, `1 h`, `1 h 35 min`, `2 days`."""
    minutes = int(round(minutes))
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        h, m = divmod(minutes, 60)
        return f"{h} h {m} min" if m else f"{h} h"
    return _n(minutes // (24 * 60), "day", "days")


def age(minutes: int) -> str:
    """The age of a stop: `<m> min`, `<h> h <mm> min`, `<d> day(s)`."""
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        h, m = divmod(minutes, 60)
        return f"{h} h {m:02d} min"
    return _n(minutes // (24 * 60), "day", "days")


def ref_of(key: str) -> str:
    """`#123` for `issue-123`, `spec 123` for `spec-123`."""
    return f"#{key[6:]}" if key.startswith("issue-") else f"spec {int(key[5:])}"


def given_of(judgement: dict | None) -> dict:
    """The per-item judgement of the file (`items`), `{}` when there is none."""
    items = (judgement or {}).get("items") if isinstance(judgement, dict) else None
    return {k: v for k, v in items.items() if isinstance(v, dict)} if isinstance(items, dict) else {}


def name_of(key: str | None, text: str | None, given: dict) -> str:
    """`<what you get> (<ref>)`: the judgement's `you_get`, else `text`; an issue without a title reads `A fix (#N)`."""
    if not key:
        return str(text or "")
    ref = ref_of(key)
    got = str((given.get(key) or {}).get("you_get") or "").strip()
    text = got or re.sub(r"\s*\(spec \d+\)$", "", str(text or "")).strip()
    if text == f"a fix for {ref}" or not text:
        text = "A fix"
    return text if ref in text else f"{text} ({ref})"


def _pr_number(pr: object) -> str | None:
    m = re.search(r"(\d+)\D*$", str(pr or ""))
    return m.group(1) if m else None


# ---------------- build start and set-up ----------------

def build_lines(b: dict, given: dict) -> list[str]:
    """Part 2 of the Build step: the numbered queue, the total, the tokens line."""
    queue = b.get("queue") or []
    out = [f"{_n(len(queue), 'item is', 'items are')} ready to build."]
    for q in queue[:LIMIT]:
        got = str((given.get(q["key"]) or {}).get("you_get") or "").strip() or str(q.get("you_get") or q.get("title") or "")
        line = f"  {q['n']}. {got} ({q['ref']})"
        if q.get("minutes"):
            line += f", about {duration(q['minutes'])}"
        out.append(line)
        if q.get("after"):
            out.append(f"     starts after {q['after']}: one spec builds at a time")
    if len(queue) > LIMIT:
        out.append(f"  and {len(queue) - LIMIT} more")
    if b.get("total_minutes"):
        out.append(f"Total: about {duration(b['total_minutes'])} of work.")
    tokens = b.get("tokens") or {}
    if tokens.get("limit") is not None:
        line = f"Tokens today: {count(tokens.get('used') or 0)} of {count(tokens['limit'])}"
        if tokens.get("raised"):
            line += " (raised for today)"
        if b.get("need_tokens"):
            line += f"; this queue needs about {count(b['need_tokens'])}"
        out.append(line)
    return out


def setup_lines(b: dict, given: dict) -> list[str]:
    """Part 2 of the Build step without a policy file."""
    return [*build_lines(b, given), "Building needs a run policy; I can set one up."]


def setup_details(b: dict) -> list[str]:
    """The details of the set-up: the file it commits, indented by two (blank lines stay blank)."""
    text = str((b.get("setup") or {}).get("file") or "")
    return ["It commits this file through a pull request that merges on green CI:",
            *[("  " + ln) if ln else "" for ln in text.splitlines()]]


# ---------------- progress ----------------

def _event_lines(e: dict, given: dict) -> list[str]:
    key, ref, when = e.get("key"), e.get("ref") or "", e.get("time") or ""
    kind = e.get("kind")
    if kind == "started":
        got = str((given.get(key) or {}).get("you_get") or "").strip() or str(e.get("what") or "")
        return [f"  {when} started {ref} {got}".rstrip()]
    if kind == "done":
        number = _pr_number(e.get("pr"))
        return [*([f"  {when} merged {ref} (PR #{number})"] if number else []), f"  {when} finished {ref}"]
    if kind == "stale":
        return [f"  {when} closed {ref}: already fixed on main"]
    return [f"  {when} stopped {ref}"]


def progress_lines(b: dict, given: dict) -> list[str]:
    """Part 2 while dispatcher units run: the head, the newest 5 event lines (`and <n> earlier` first), `Building now:`."""
    events, running = b.get("events") or [], b.get("running") or []
    items = {e["key"] for e in events if e.get("key") and e.get("kind") == "started"} | {r["key"] for r in running}
    slots = b.get("slots")
    words = _WORDS[slots] if isinstance(slots, int) and 0 <= slots < len(_WORDS) else str(slots)
    out = [f"Building {_n(len(items), 'item', 'items')}" + (f", {words} at a time." if slots else ".")]
    lines = [ln for e in events for ln in _event_lines(e, given)]
    if len(lines) > EVENT_LIMIT:
        out.append(f"  and {len(lines) - EVENT_LIMIT} earlier")
    out += lines[-EVENT_LIMIT:]
    if running:
        out.append("Building now:")
        for r in running[:LIMIT]:
            out.append(f"  {name_of(r['key'], r.get('what'), given)}: {r.get('step')}")
        if len(running) > LIMIT:
            out.append(f"  and {len(running) - LIMIT} more")
    return out


# ---------------- stops ----------------

def _first_open(stop: dict) -> str | None:
    answered = set(stop.get("answered") or [])
    for i, q in enumerate(stop.get("questions") or [], 1):
        if i not in answered and q.get("text"):
            return str(q["text"])
    return None


def stop_lines(item: dict, b: dict, given: dict, bang: str = "!") -> list[str]:
    """The block of one stopped item that has a `stop`: what happened, why I ask or what was tried, what keeps running."""
    stop, key = item["stop"], item["stop"].get("key")
    judged = given.get(key or "") or {}
    out = [f"  {bang} {name_of(key, item.get('what'), given) if key else item.get('what')}"]
    kind = stop.get("kind")
    if kind == "budget":
        tokens = b.get("tokens") or {}
        happened = f"The day's token budget is reached: {count(tokens.get('used') or 0)} of {count(tokens.get('limit') or 0)}."
    else:
        happened = str(judged.get("what_happened") or "").strip() or str(stop.get("reason") or item.get("reason") or "").strip()
    out.append(f"    What happened: {happened}")
    if kind == "decision":
        out.append(f"    Why I ask: {str(judged.get('why_ask') or '').strip() or _first_open(stop) or 'it needs your decision to go on'}")
        keeps = [f"      {name_of(r['key'], r.get('what'), given)} keeps running." for r in b.get("running") or [] if r["key"] != key]
        waits = [f"      {name_of(q['key'], q.get('you_get') or q.get('title'), given)} waits for this one."
                 for q in b.get("queue") or [] if q.get("after") and q["after"] == stop.get("ref")]
        if keeps or waits:
            out += ["    While you think:", *keeps, *waits]
        else:
            out.append("    While you think: nothing else runs.")
    else:
        out.append(f"    Already tried: {', '.join(stop.get('tried') or []) or 'nothing yet'}")
    minutes = int(stop.get("asked_minutes") or 0)
    if minutes >= ASK_MINUTES:
        out.append(f"    asked {age(minutes)} ago")
    return out


def raise_lines(b: dict, value: str) -> list[str]:
    """The confirmation of `--show raise-budget:<value>`; a value that is not an integer above the limit is named and not offered."""
    tokens = b.get("tokens") or {}
    limit = tokens.get("limit") or 0
    out = [f"Tokens today: {count(tokens.get('used') or 0)} of {count(limit)}."]
    if b.get("need_tokens"):
        out.append(f"This queue needs about {count(b['need_tokens'])}.")
    if valid_raise(b, value):
        out.append(f"New budget for today: {count(int(value))}.")
    else:
        out.append(f"{value} is not above today's budget of {count(limit)}.")
    return out


def valid_raise(b: dict, value: str) -> bool:
    """True when `value` is an integer above today's limit."""
    return bool(re.fullmatch(r"\d+", str(value))) and int(value) > ((b.get("tokens") or {}).get("limit") or 0)


def log_lines(item: dict | None, key: str) -> list[str]:
    """`--show log:<key>`: the log path of the item's run, or that none is recorded."""
    log = ((item or {}).get("stop") or {}).get("log")
    return [f"Log: {log}"] if log else [f"No log is recorded for {ref_of(key)}."]


# ---------------- release, promote, end of build ----------------

def _sections(sections: dict | None) -> list[str]:
    out = []
    for title in ("Fixed", "Added", "Changed"):
        lines = (sections or {}).get(title) or []
        if lines:
            out.append(f"  {title}")
            out += [f"    {ln}" for ln in lines[:LIMIT]]
            if len(lines) > LIMIT:
                out.append(f"    and {len(lines) - LIMIT} more")
    return out


def release_lines(item: dict, when: str = "") -> list[str]:
    """Part 2 of the Release step: the count since the last tag and the sections."""
    cons = item.get("consequence") or {}
    changes = cons.get("changes") or []
    out = [f"A release is ready: {_n(len(changes), 'change', 'changes')} since {cons.get('since_tag') or 'the start'}.{when}"]
    sections = cons.get("sections")
    if sections is None:
        sections = {"Changed": changes}
    return [*out, "Ready to release:", *_sections(sections)]


def end_lines(b: dict, sections: dict | None = None) -> list[str]:
    """The end-of-build head: the totals that can be read and, when the release item is shown, the sections."""
    totals = b.get("totals") or {}
    out = ["The build is done."]
    if totals.get("wall_minutes") is not None:
        out.append(f"Wall time: {duration(totals['wall_minutes'])}")
    if totals.get("tokens") is not None:
        out.append(f"Tokens: {count(totals['tokens'])}")
    if totals.get("questions") is not None:
        out.append(f"Questions to you: {totals['questions']}")
    if sections is not None:
        out += ["Ready to release:", *_sections(sections)]
    return out


def promote_lines(item: dict, when: str = "") -> list[str]:
    """Part 2 of a promote item: `<component> <version> can go to staging.` / `... to prod.`"""
    obj = item.get("object") or {}
    env = (item.get("consequence") or {}).get("env") or "prod"
    out = [f"{obj.get('component')} {obj.get('version')} can go to {env}.{when}"]
    if (item.get("consequence") or {}).get("first"):     # #920: no staging instance yet, so nothing can be released
        app = (item.get("consequence") or {}).get("app")
        out.append(f"Not in staging yet: the first promotion is manual ({item.get('command')}{' in ' + app if app else ''}); "
                   "the release follows once staging runs it.")
    return out


# ---------------- last screen ----------------

def last_lines(b: dict) -> list[str]:
    """The last screen: what was closed and released, the time of the person, nothing waits, the parked items."""
    flow = b.get("flow") or {}
    closed = flow.get("issues_closed") or []
    out = ["Issues closed: " + (", ".join(f"#{n}" for n in closed) if closed else "none"),
           f"Released: {flow.get('released')}"]
    if flow.get("your_minutes") is not None:
        out.append(f"Your time: {duration(flow['your_minutes'])}")
    parked = flow.get("parked") or []
    out += ["Nothing is waiting for you.",
            "Parked: " + (", ".join(f"{p['ref']} ({p['reason']})" if p.get("reason") else p["ref"] for p in parked) if parked else "none"),
            "New issues show up here in /platform:next"]
    return out


# ---------------- your part ----------------

def your_part(case: str, channels: str | None = None) -> str:
    """The `Your part:` line of a case; `channels` is the notification phrase of the progress case."""
    if case == "progress":
        return "Your part: nothing. You can walk away" + (f"; {channels}." if channels else ".")
    return {"build": "Your part: choose how many items build at once.",
            "setup": "Your part: set up the build, or leave it for now.",
            "stop": "Your part: decide how the stopped run goes on.",
            "release": "Your part: release, or wait for more changes.",
            "promote": "Your part: promote, or hold it back.",
            "raise": "Your part: confirm the new budget, or keep it.",
            "raise-invalid": "Your part: try another number, or keep the budget.",
            "log": "Your part: choose, or go back.",
            "last": "Your part: nothing. You can walk away."}[case]
