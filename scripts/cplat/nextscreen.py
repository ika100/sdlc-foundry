"""`cplat next` screen (spec 192): the three parts of the text the person reads, as pure functions of the state.

Public API:
- `render(state, *, ascii, later, judgement, show=None, choose=None, actions=None, judgement_error=False) -> dict`:
  `{"bar": {steps, label}, "waiting": {group, items, also, later}, "running": [...], "screen": str}`. `state` comes from
  `nextstate.collect`; `later` is the ids put off; `judgement` is the parsed `--judgement` file (`{"specs": {key:
  {"you_get", "assumption"}}}`, keyed by spec id or number) or None; `judgement_error` adds the line `Could not read the
  judgement file.`. `show="assumptions"`, `show="details:<QID>"` and `choose="approve"` replace part 2 with a sub-screen;
  `actions` maps an item id (assumptions) or a question id (details) to a list of `{what, target, undo}` dicts, the data
  of `nextquestions.actions`, so this module does not import `nextquestions`.
- `wrap(line, indent)`: the line broken at spaces to 80 columns, continuation lines indented by `indent` columns.
- `age(minutes)`: `42 min`, `1 h 5 min`, `2 days`.

The screen has three parts separated by one blank line: the bar, what is happening, `Your part:`. No line is wider than
80 columns; every line goes through `nextstate.plain`. Nothing here does any I/O.
"""
from __future__ import annotations

import textwrap

import nextstate
import stages

WIDTH = 80
LIMIT = 5
_GLYPHS = "①②③④⑤⑥"
_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
_SOURCES = {
    "github": ("GitHub", "a GitHub login (gh auth status) or the network"),
    "runs": ("the run records", "the private run store (cplat platform doctor)"),
    "dispatcher": ("the run queue", "its state files"),
    "cluster": ("the cluster", "a kube context"),
    "notifications": ("the notification settings", "a valid notify.yaml"),
}
_ALSO = {"escalation": ("stopped run", "stopped runs"), "stuck": ("stuck run", "stuck runs"),
         "budget": ("daily budget reached", "daily budget reached"),
         "answer": ("spec with questions", "specs with questions"), "approve": ("spec to approve", "specs to approve"),
         "triage": ("new issue", "new issues"), "release": ("release ready", "release ready"),
         "promote": ("release to promote", "releases to promote"), "review": ("fix to review", "fixes to review")}
_KIND_STAGE = {"answer": "Spec", "approve": "Spec", "triage": "Issue", "release": "Release", "promote": "Prod", "review": "Build"}
_CHANNEL_WORDS = {"desktop": "on the desktop", "github": "on GitHub", "slack": "in Slack", "email": "by e-mail"}
_KEEP = (*_CHANNEL_WORDS.values(), "look here again")     # phrases wrap() never breaks
_ASCII = {"…": "...", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "✓": "x", "●": ">"}


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def age(minutes: int) -> str:
    """A waiting time as the screen shows it."""
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        h, m = divmod(minutes, 60)
        return f"{h} h {m} min" if m else f"{h} h"
    return _n(minutes // (24 * 60), "day", "days")


def wrap(line: str, indent: int = 0) -> list[str]:
    """Break `line` at spaces so none is wider than 80 columns; continuation lines get `indent` spaces."""
    lead = " " * (len(line) - len(line.lstrip(" ")))
    text = line.strip(" ")
    for phrase in _KEEP:
        text = text.replace(phrase, phrase.replace(" ", "\xa0"))
    lines = textwrap.wrap(text, WIDTH, initial_indent=lead, subsequent_indent=" " * max(indent, len(lead)),
                          break_long_words=True, break_on_hyphens=False)
    return [ln.replace("\xa0", " ") for ln in lines] or [""]


class _Lines:
    def __init__(self) -> None:
        self.out: list[str] = []

    def add(self, text: str, indent: int = 0) -> None:
        self.out.extend(wrap(nextstate.plain(text), indent))

    def more(self, items: list, shown: int = LIMIT, lead: str = "  ") -> None:
        if len(items) > shown:
            self.add(f"{lead}and {len(items) - shown} more")


def _minutes_text(minutes: int) -> str:
    return age(int(minutes))


def _age_of(item: dict) -> str | None:
    m = item.get("waiting_minutes")
    return age(m) if isinstance(m, int) else None


def _number(spec_id: str) -> str:
    return spec_id.split("-", 1)[0].lstrip("0") or "0"


# ---------------- part 1: the bar ----------------

def _bar(state: dict, group: str | None, shown: list[dict], ascii: bool) -> tuple[list[str], dict]:
    shape = state.get("shape")
    names = stages.bar(shape)
    here = running = None
    if group and shown:
        first = shown[0]
        here = stages.bar_step(first.get("stage") or _KIND_STAGE.get(first.get("kind"), "Issue"), shape)
    else:
        found = [r.get("bar_step") for r in state.get("running") or [] if r.get("bar_step") in names]
        running = min(found, key=names.index) if found else None
    marked = here or running
    steps, segments, col = [], [], 1
    for i, name in enumerate(names):
        st = "here" if name == here else "running" if name == running else \
            "done" if marked and i < names.index(marked) else "todo"
        steps.append({"n": i + 1, "name": name, "what": stages.explain(name)["what"], "state": st})
        num = f"{i + 1}." if ascii else _GLYPHS[i]
        mark = {"done": "[x]" if ascii else "✓", "here": "[>]" if ascii else "●", "running": "[>]" if ascii else "●"}.get(st)
        segments.append((f"{num} {name}" + (f" {mark}" if mark else ""), st))
    sep = " -- " if ascii else " ── "
    line, label_col = " ", 0
    for i, (text, st) in enumerate(segments):
        if i:
            line += sep
        if st in ("here", "running"):
            label_col = len(line)
        line += text
    label = "you are here" if here else "running on its own" if running else None
    lines = [line]
    if label:
        start = max(0, min(label_col, WIDTH - len(label)))
        lines.append(" " * start + label)
    return lines, {"steps": steps, "label": label}


# ---------------- part 2: what is happening ----------------

def _draft_key(judgement: dict | None, draft: dict) -> dict:
    if not judgement:
        return {}
    specs = judgement.get("specs", judgement) if isinstance(judgement, dict) else {}
    if not isinstance(specs, dict):
        return {}
    sid = draft.get("spec") or ""
    entry = specs.get(sid) or specs.get(_number(sid)) or specs.get(sid.split("-", 1)[0])
    return entry if isinstance(entry, dict) else {}


def _draft_block(out: _Lines, item: dict, judgement: dict | None) -> None:
    draft = item.get("draft")
    if not draft:
        out.add(f"  {item.get('what') or item['id']}", 4)
        return
    tracks = draft.get("tracks") or []
    meta = [f"spec {_number(draft['spec'])}"]
    if tracks:
        meta.append(f"from #{tracks[0]}")
    if _age_of(item):
        meta.append(f"waiting {_age_of(item)}")
    out.add(f"  {draft['title']} ({', '.join(meta)})", 4)
    given = _draft_key(judgement, draft)
    if given.get("you_get"):
        out.add(f"    You get:   {given['you_get']}", 15)
    assumptions = draft.get("assumptions") or []
    text = given.get("assumption") or (assumptions[0] if assumptions else "")
    if text:
        count = max(len(assumptions), 1)
        out.add(f"    I assumed: {text} ({count} assumption{'s' if count != 1 else ''} in all)", 15)
    size = f"    Size:      {draft.get('size') or nextstate.size_of(draft.get('criteria') or 0)}"
    if draft.get("estimate_minutes"):
        size += f", about {_minutes_text(draft['estimate_minutes'])} to build"
    out.add(size, 15)


def _group_lines(out: _Lines, group: str, shown: list[dict], judgement: dict | None, ascii: bool) -> None:
    bang = "[!]" if ascii else "!"
    if group == "stopped":
        out.add(f"{_n(len(shown), 'run stopped and waits', 'runs stopped and wait')} for you.")
        for item in shown[:LIMIT]:
            reason = (item.get("reason") or "").rstrip(".")
            when = f" (waiting {_age_of(item)})" if _age_of(item) else ""
            out.add(f"  {bang} {item.get('what')}: {reason}{when}", 6 if ascii else 4)
        out.more(shown)
    elif group == "specs":
        questions = sum(1 for i in shown if i.get("kind") == "answer")
        out.add(f"{_n(len(shown), 'spec is written and waits', 'specs are written and wait')} for your approval."
                + (f" {_n(questions, 'has', 'have')} questions for you." if questions else ""))
        for item in shown[:LIMIT]:
            _draft_block(out, item, judgement)
        out.more(shown)
    elif group == "issues":
        out.add(f"{_n(len(shown), 'new issue waits', 'new issues wait')} for triage.")
        for item in shown[:LIMIT]:
            number = (item.get("object") or {}).get("issue")
            meta = [f"#{number}"] + ([f"waiting {_age_of(item)}"] if _age_of(item) else [])
            out.add(f"  {item.get('what')} ({', '.join(meta)})", 4)
        out.more(shown)
    else:
        for item in shown[:LIMIT]:
            _release_lines(out, item)
        out.more(shown)


def _release_lines(out: _Lines, item: dict) -> None:
    kind, when = item.get("kind"), f" (waiting {_age_of(item)})" if _age_of(item) else ""
    obj = item.get("object") or {}
    if kind == "release":
        cons = item.get("consequence") or {}
        changes = cons.get("changes") or []
        out.add(f"A release is ready: {_n(len(changes), 'change', 'changes')} since {cons.get('since_tag') or 'the start'}.{when}")
        for change in changes[:LIMIT]:
            out.add(f"  {change}", 4)
        out.more(changes)
    elif kind == "promote":
        out.add(f"{item.get('what')} is verified in staging and can go to prod.{when}")
    else:
        out.add(f"A fix waits for your review (PR #{obj.get('pr')}).{when}")


def _unavailable_lines(out: _Lines, state: dict) -> None:
    for u in state.get("unavailable") or []:
        name, hint = _SOURCES.get(u.get("source"), (u.get("source"), None))
        out.add(f"Could not read {name}; it may be missing {hint}." if hint else f"Could not read {name}.")


def _tail_lines(out: _Lines, state: dict, also: dict[str, int], later: int, waiting: bool) -> None:
    if also:
        parts = [(_ALSO[k][0 if n == 1 else 1] if k in ("budget", "release") else f"{n} {_ALSO[k][0 if n == 1 else 1]}")
                 for k, n in also.items()]
        out.add("Also waiting: " + ", ".join(parts) + ".", 14)
    if later:
        out.add(f"{later} put off for later.")
    running = state.get("running") or []
    if waiting and running:
        out.add(f"Also running: {_n(len(running), 'run', 'runs')}.")


def _running_lines(out: _Lines, state: dict) -> None:
    running, slots = state.get("running") or [], state.get("slots")
    words = _WORDS[slots] if isinstance(slots, int) and 0 <= slots < len(_WORDS) else str(slots)
    out.add(f"{_n(len(running), 'run', 'runs')}" + (f", {words} at a time." if slots else "."))
    for r in running[:LIMIT]:
        out.add(f"  {r.get('what')}: {r.get('step')}", 4)
    out.more(running)


def _action_lines(out: _Lines, acts: list[dict], lead: str = "  ") -> None:
    for a in acts:
        out.add(f"{lead}{a.get('what')}: {a.get('target')}", len(lead) + 2)
        out.add(f"{lead}  " + (f"Undo: {a['undo']}" if a.get("undo") else "Cannot be undone."), len(lead) + 4)


def _sub_screen(state: dict, items: list[dict], show: str | None, choose: str | None, actions: dict | None) -> tuple[list[str], str]:
    out, actions = _Lines(), actions or {}
    if choose == "approve":
        drafts = [i for i in items if i.get("kind") == "approve"]
        out.add("Which spec do you want to approve now?")
        for item in drafts[:LIMIT]:
            _draft_block(out, item, None)
        out.more(drafts)
        return out.out, "Your part: pick the spec to approve."
    if show == "assumptions":
        drafts = [i for i in items if i.get("kind") in ("approve", "answer") and i.get("draft")]
        out.add("Assumptions I made in the written specs:")
        for item in drafts[:LIMIT]:
            d = item["draft"]
            out.add(f"  {d['title']} (spec {_number(d['spec'])})", 4)
            for text in (d.get("assumptions") or [])[:LIMIT]:
                out.add(f"    - {text}", 6)
            out.more(d.get("assumptions") or [], lead="    ")
        out.more(drafts)
        out.add("Approving does this:")
        for item in drafts[:LIMIT]:
            if item.get("kind") == "approve":
                _action_lines(out, actions.get(item["id"]) or [])
        return out.out, "Your part: read the assumptions, then approve or go back."
    qid = (show or "").split(":", 1)[-1]
    out.add("What this choice does:")
    acts = actions.get(qid) or []
    _action_lines(out, acts) if acts else out.add("  Nothing leaves your machine.")
    return out.out, "Your part: choose, or go back."


# ---------------- part 3: your part ----------------

def _channels_text(channels: list[str] | None) -> str:
    words = [_CHANNEL_WORDS[c] for c in channels or [] if c in _CHANNEL_WORDS]
    if not words:
        return "notifications are off, so look here again"
    joined = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    return f"a question reaches you {joined} and shows up here first"


def _your_part(state: dict, group: str | None, shown: list[dict]) -> str:
    first = shown[0] if shown else {}
    if group == "stopped":
        return "Your part: decide how the stopped run goes on."
    if group == "specs":
        asked = sum(len((i.get("draft") or {}).get("questions") or []) for i in shown if i.get("kind") == "answer")
        if asked:
            return f"Your part: answer {_n(asked, 'question', 'questions')}, then approve."
        prs = [f"PR #{i['draft']['pr']}" for i in shown[:LIMIT] if (i.get("draft") or {}).get("pr")]
        return "Your part: approve, or read first" + (f" ({', '.join(prs)})." if prs else ".")
    if group == "issues":
        return "Your part: triage the new issues."
    if group == "release":
        return {"promote": "Your part: promote to prod, or hold it back.",
                "review": "Your part: review the fix."}.get(first.get("kind"), "Your part: release, or wait for more changes.")
    if state.get("unavailable"):
        return "Your part: check what is missing, then try again."
    if state.get("running"):
        return "Your part: nothing. You can walk away; " + _channels_text(state.get("channels")) + "."
    return "Your part: nothing. You can walk away."


# ---------------- render ----------------

def _asciify(text: str) -> str:
    for old, new in _ASCII.items():
        text = text.replace(old, new)
    return text.encode("ascii", "replace").decode("ascii")


def render(state: dict, *, ascii: bool = False, later=(), judgement: dict | None = None, show: str | None = None,
           choose: str | None = None, actions: dict | None = None, judgement_error: bool = False) -> dict:
    """The three parts of the screen with the bar and waiting data for the JSON document (see the module docstring)."""
    group, shown, also, later_count = nextstate.groups(state, later)
    bar_lines, bar = _bar(state, group, shown, ascii)
    out = _Lines()
    if show or choose:
        waiting = [i for i in state["items"] if i["id"] not in set(later)]
        body, part3 = _sub_screen(state, waiting if choose or show == "assumptions" else shown, show, choose, actions)
        out.out.extend(body)
    else:
        if group:
            _group_lines(out, group, shown, judgement, ascii)
        elif not state.get("unavailable") and not state.get("running"):
            out.add("Nothing is waiting for you.")
            out.add(f"{_n(state.get('parked') or 0, 'parked item', 'parked items')}.")
        if group is None and state.get("running"):
            _running_lines(out, state)
        _unavailable_lines(out, state)
        if judgement_error:
            out.add("Could not read the judgement file.")
        _tail_lines(out, state, also, later_count, group is not None)
        if group is None and not state.get("unavailable") and not state.get("running"):
            out.add("New issues will show up here.")
        part3 = _your_part(state, group, shown)
    part3_lines = wrap(nextstate.plain(part3), 1)
    screen = "\n\n".join("\n".join(p) for p in (bar_lines, out.out or [""], part3_lines))
    if ascii:
        screen = _asciify(screen)
    running = [{"what": r.get("what"), "step": r.get("step"), "bar_step": r.get("bar_step")} for r in state.get("running") or []]
    return {"bar": bar, "waiting": {"group": group, "items": [i["id"] for i in shown], "also": also, "later": later_count},
            "running": running, "screen": screen}
