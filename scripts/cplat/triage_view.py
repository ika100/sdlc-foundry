"""`triage_view`: the screens of `cplat issue triage` and the exact actions of each row (spec 176).

The triager writes only judgement (the proposals file); this module validates it against the saved batch, places each issue in a
group, words the action and renders the overview, the question pages and the confirmation, so that the screens are the same on
every run. `actions` builds the labels and the `Triage:` comment of a row, shared by `confirm --show` and `act`.
"""
from __future__ import annotations

import json
import os
import tempfile
import textwrap
from pathlib import Path

import priority as prio
import triage
import triage_batch
from core import PlatformError

CLASSES = ("bug", "small-change", "feature", "question", "duplicate", "wontfix", "needs-exploring", "needs-info")
PRIORITY_CLASSES = ("bug", "small-change", "feature")
COMMENT_CLASSES = ("question", "duplicate", "wontfix", "needs-info")
CHECK_CLASSES = ("bug", "small-change", "feature", "needs-info", "question", "wontfix")
CHANGED_BY_YOU = "changed by you"
SET_ON_ISSUE = "set on the issue"
WIDTH = 80
PAGE = 4
CHOICES = ["OK, do it", "Change one", "Cancel"]
HANDLED_ORDER = ("spec", "claimed", "fixed", "duplicate")
GROUPS = (("decide", "Needs your decision"), ("clear", "Clear"), ("handled", "Already handled"))
ACTION = {"bug": "fix on its own", "small-change": "fix on its own", "question": "answer in comment", "duplicate": "mark as duplicate",
          "wontfix": "explain, no work", "needs-exploring": "explore it first", "needs-info": "ask the reporter"}
PLAN = {"bug": "queue the fix, it runs on its own", "small-change": "queue the fix, it runs on its own",
        "question": "post the answer, label question", "wontfix": "explain why, label wontfix",
        "needs-info": "ask the reporter, label needs-info", "needs-exploring": "nothing posted, explore it next"}


def _wrap(text: str, first: str, rest: str = " " * 8) -> str:
    return textwrap.fill(text, width=WIDTH, initial_indent=first, subsequent_indent=rest, break_on_hyphens=False)


def _number(spec_id: str) -> str:
    return spec_id.split("-", 1)[0]


# ---------------- the proposals file ----------------

def load_proposals(path: str | Path, batch: dict, *, for_act: bool = False, root: Path | None = None) -> list[dict]:
    """The validated rows (class and mark filled in); every error of the file is listed in one `PlatformError`."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise PlatformError("cannot read the proposals file", hint=f"{path}: {e}") from e
    rows = raw.get("rows") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise PlatformError("the proposals file has no `rows` list", hint='write {"rows": [{"number": 560, "summary": "…", …}]}')
    issues = {i["number"]: i for i in batch["issues"]}
    errors: list[str] = []
    seen: dict[int, dict] = {}
    for r in rows:
        n = r.get("number") if isinstance(r, dict) else None
        if not isinstance(n, int) or n not in issues:
            errors.append(f"#{n}: not an issue of the batch")
        elif n in seen:
            errors.append(f"#{n}: more than one row")
        else:
            seen[n] = r
    out = []
    for n, issue in issues.items():
        if issue["handled"]:
            continue
        if n not in seen:
            errors.append(f"#{n}: no row")
            continue
        row, problems = _row(seen[n], issue, for_act, root or Path.cwd())
        errors += [f"#{n}: {p}" for p in problems]
        out.append(row)
    if errors:
        raise PlatformError("the proposals file is not valid", hint="\n".join(errors))
    return out


def _text(value, limit: int | None = None) -> bool:
    return isinstance(value, str) and bool(value.strip()) and (limit is None or len(value) <= limit)


def _priority_problems(row: dict) -> list[str]:
    """Check the priority and the reason of a priority row; a missing P1 reason becomes the fallback."""
    level = row.get("priority")
    if level not in prio.LEVELS:
        return ["priority must be P0, P1 or P2"]
    reason = row.get("priority_reason")
    if not _text(reason):
        if level != "P1":
            return ["priority_reason is missing"]
        row["priority_reason"] = prio.FALLBACK_REASON
    elif len(reason) <= prio.MAX_REASON and reason not in (CHANGED_BY_YOU, SET_ON_ISSUE) and not prio.proposal_reason_ok(level, reason):
        return [f'priority_reason must be "{level}: <phrase>" with a phrase of {level}: ' + ", ".join(prio.LEVELS[level]["phrases"])]
    return []


def _row(src: dict, issue: dict, for_act: bool, root: Path) -> tuple[dict, list[str]]:
    row, bad = dict(src), []
    engine = issue.get("engine")
    mismatch = False
    if row.get("class") is None and engine and engine.get("class"):
        row["class"] = engine["class"]
        row.setdefault("mark", engine["mark"])
    elif engine and engine.get("class") and row.get("class") != engine["class"]:
        mismatch = True
    row.setdefault("mark", "sure")
    if mismatch:
        row["mark"] = "check"
    cls = row.get("class")
    if cls not in CLASSES:
        bad.append(f"class must be one of {', '.join(CLASSES)}")
    if row["mark"] not in ("sure", "check"):
        bad.append("mark must be sure or check")
    summary = row.get("summary")
    if not (isinstance(summary, str) and 1 <= len(summary) <= 80 and "\n" not in summary):
        bad.append("summary must be 1-80 characters on one line")
    labels = issue.get("priority_labels") or []
    if cls in PRIORITY_CLASSES and labels and not row.get("priority_decided"):
        row["priority"], row["priority_reason"] = prio.most_urgent(labels), SET_ON_ISSUE   # the issue's own label wins (AC-196.3)
    elif cls in PRIORITY_CLASSES:
        bad += _priority_problems(row)
    elif cls in CLASSES and row.get("priority") is not None:
        bad.append(f"a {cls} row has no priority")
    if len(str(row.get("priority_reason") or "")) > 60:
        bad.append("priority_reason is longer than 60 characters")
    q = row.get("question")
    if q is not None:
        opts = q.get("options") if isinstance(q, dict) else None
        if not (isinstance(q, dict) and _text(q.get("text")) and isinstance(opts, list) and 1 <= len(opts) <= 4
                and all(_text(o) for o in opts)):
            bad.append("question needs a text and 1-4 options")
    if cls in COMMENT_CLASSES and not _text(row.get("comment")):
        bad.append(f"a {cls} row needs a comment")
    if cls == "duplicate" and not isinstance(row.get("duplicate_of"), int):
        bad.append("a duplicate row needs duplicate_of")
    if cls in ("bug", "small-change") and not _text(row.get("expected")):
        bad.append(f"a {cls} row needs the expected result")
    if for_act and cls == "feature" and not (row.get("spec") and (root / "docs" / "specs" / row["spec"]).is_dir()):
        bad.append("a feature row needs `spec` naming a spec in docs/specs/")
    return row, bad


# ---------------- groups ----------------

def _decide(issue: dict, row: dict) -> bool:
    """Several priority labels on the issue and the user has not chosen yet."""
    return len(issue["priority_labels"]) > 1 and not row.get("priority_decided")


def _entries(batch: dict, rows: list[dict]) -> list[dict]:
    """Every issue of the batch, in batch order, with its row (none when handled) and its group."""
    by_number = {r["number"]: r for r in rows}
    out = []
    for issue in batch["issues"]:
        row = None if issue["handled"] else by_number.get(issue["number"])
        if issue["handled"]:
            group = "handled"
        elif row and (row.get("question") or row["mark"] == "check" or _decide(issue, row)):
            group = "decide"
        else:
            group = "clear"
        out.append({"issue": issue, "row": row, "group": group})
    return out


def group(batch: dict, rows: list[dict]) -> dict:
    """{"decide": [numbers], "clear": [...], "handled": [...]} in batch order."""
    found = _entries(batch, rows)
    return {key: [e["issue"]["number"] for e in found if e["group"] == key] for key, _ in GROUPS}


def action_word(row: dict) -> str:
    if row["class"] == "feature":
        return f"add to spec {_number(row['spec'])}" if row.get("spec") and not row.get("new_spec") else "write new spec"
    return ACTION[row["class"]]


def auto_question(row: dict, issue: dict) -> dict:
    n = issue["number"]
    if row["mark"] == "check":
        others = [c for c in CHECK_CLASSES if c != row["class"]][:3]
        return {"text": f"Is #{n} a {row['class']}?", "options": [row["class"], *others]}
    first = row.get("priority") or "P1"
    return {"text": f"Which priority for #{n}?", "options": [first, *[p for p in ("P0", "P1", "P2") if p != first]]}


def _question(row: dict, issue: dict) -> dict:
    q = row.get("question") or auto_question(row, issue)
    options = [{"label": o + (" (Recommended)" if i == 0 else ""), "recommended": i == 0} for i, o in enumerate(q["options"])]
    return {"number": issue["number"], "header": f"#{issue['number']}", "text": q["text"], "options": options}


def pages(batch: dict, rows: list[dict]) -> list[dict]:
    questions = [_question(e["row"], e["issue"]) for e in _entries(batch, rows) if e["group"] == "decide"]
    chunks = [questions[i:i + PAGE] for i in range(0, len(questions), PAGE)]
    return [{"page": f"{i} of {len(chunks)}", "questions": c} for i, c in enumerate(chunks, 1)]


# ---------------- the overview ----------------

def _from(issue: dict) -> str | None:
    return f"from: {issue['role']}" if issue["role"] in ("contributor", "none") else None


def _line(e: dict) -> str:
    issue, row = e["issue"], e["row"]
    text = _wrap(row["summary"], f"  #{issue['number']}  ")
    if e["group"] == "decide":
        parts = ["check" if row["mark"] == "check" else None, _from(issue)]
    else:
        parts = [row["class"], row.get("priority"), action_word(row), _from(issue)]
    parts = [p for p in parts if p]
    return text + ("\n" + _wrap(", ".join(parts), " " * 8) if parts else "")


def overview(batch: dict, rows: list[dict]) -> str:
    found = _entries(batch, rows)
    total = len(found)
    out = [f"Triage of {batch['repo']}: {total} issue{'' if total == 1 else 's'}", ""]
    for key, name in GROUPS:
        members = [e for e in found if e["group"] == key]
        out.append(f"{name} ({len(members)})")
        if key == "handled":
            lines: dict[str, list[int]] = {}
            for kind in HANDLED_ORDER:
                for e in members:
                    h = e["issue"]["handled"]
                    if h["kind"] == kind:
                        lines.setdefault(h["line"], []).append(e["issue"]["number"])
            out += [_wrap(f"{line}: " + ", ".join(f"#{n}" for n in nums), "  ") for line, nums in lines.items()]
        else:
            out += [_line(e) for e in members]
    if batch["skipped"]:
        out.append(_wrap("Skipped: " + "; ".join(f"#{s['number']} {s['reason']}" if s["number"] else s["reason"] for s in batch["skipped"]), ""))
    count = len([e for e in found if e["group"] == "decide"])
    out += ["", "No questions follow." if not count else "1 question follows." if count == 1 else f"{count} questions follow."]
    return "\n".join(out)


def overview_json(batch: dict, rows: list[dict]) -> dict:
    return {"screen": overview(batch, rows), "groups": group(batch, rows), "pages": pages(batch, rows)}


# ---------------- actions and the plan ----------------

def _comment(row: dict) -> str:
    text = f"Triage: {row['summary']}\n\nClass: {row['class']}, priority {row['priority']}."
    if row.get("answers"):
        text += "\nAnswers: " + "; ".join(row["answers"])
    if row.get("expected"):
        text += f"\nExpected result: {row['expected']}"
    return text


def actions(issue: dict, row: dict | None) -> dict:
    """{"add", "remove", "comment"} of one issue as `act` makes them: only real changes, none for a row that needs no call."""
    have = set(issue["labels"])
    handled = (issue["handled"] or {}).get("kind")
    comment = None
    if handled:
        add, drop = {"spec": ["tracked"], "duplicate": ["duplicate"]}.get(handled, []), ["triage"] if handled in ("spec", "duplicate") else []
    else:
        cls = row["class"]
        if cls in ("bug", "small-change", "feature"):
            mine = "p" + row["priority"][1:]
            add = ["bug" if cls == "bug" else "enhancement", *(["tracked"] if cls == "feature" else []), "triaged", mine]
            drop = ["triage", "needs-info", *[p for p in issue["priority_labels"] if p != mine]]
            comment = f"Tracked as spec {row.get('spec') or '<new>'}" if cls == "feature" else _comment(row)
        elif cls == "needs-exploring":
            add, drop = [], []
        else:
            add, drop = [cls], ["triage"] + (["needs-info"] if cls != "needs-info" else [])
            comment = row["comment"]
    return {"add": [x for x in add if x not in have], "remove": [x for x in drop if x in have], "comment": comment}


def _plan_text(e: dict) -> tuple[str, str] | None:
    issue, row = e["issue"], e["row"]
    if e["group"] == "handled":
        kind, h = issue["handled"]["kind"], issue["status"]
        if kind == "spec":
            return "spec", f"tracked in spec {h['specs'][0]['number']}: label tracked"
        if kind == "duplicate":
            return "duplicate", f"duplicate of #{h['duplicate_of']}: label duplicate"
        return None
    cls = row["class"]
    head = cls
    if cls in PRIORITY_CLASSES:
        reason = row["priority_reason"]
        if _decide(issue, row):
            reason += "; " + ", ".join(issue["priority_labels"]) + ": decide"
        head = f"{cls}, {row['priority']} ({reason})"
    if cls == "feature":
        phrase = f"track the issue in spec {_number(row['spec'])}" if row.get("spec") and not row.get("new_spec") \
            else "write a new spec, track the issue in it"
    elif cls == "duplicate":
        phrase = f"mark as duplicate of #{row['duplicate_of']}"
    else:
        phrase = PLAN[cls]
    return cls, f"{head}: {phrase}"


def _plan_row(e: dict, step: tuple[str, str]) -> dict:
    row = e["row"] if e["group"] != "handled" else None
    has = bool(row) and step[0] in PRIORITY_CLASSES
    return {"number": e["issue"]["number"], "class": step[0], "text": step[1], "group": e["group"],
            "priority": row["priority"] if has else None, "priority_reason": row["priority_reason"] if has else None,
            "decide": bool(has and _decide(e["issue"], row))}


def plan(batch: dict, rows: list[dict]) -> list[dict]:
    lines = []
    entries = _entries(batch, rows)
    for e in [e for key, _ in GROUPS for e in entries if e["group"] == key]:
        step = _plan_text(e)
        if step:
            lines.append(_plan_row(e, step))
    return lines


def confirm(batch: dict, rows: list[dict]) -> str:
    lines = plan(batch, rows)
    head = f"The plan ({len(lines)} action{'' if len(lines) == 1 else 's'}):"
    return "\n".join([head, *[f"  #{l['number']}  {l['text']}" for l in lines], "Choose: " + " / ".join(CHOICES)])


def show(batch: dict, rows: list[dict], number: int) -> str:
    found = {e["issue"]["number"]: e for e in _entries(batch, rows)}
    if number not in found:
        raise PlatformError(f"#{number} is not an issue of the batch")
    e = found[number]
    a = actions(e["issue"], e["row"])
    labels = [f"+{x}" for x in a["add"]] + [f"-{x}" for x in a["remove"]]
    return "\n".join([f"#{number}", "labels: " + (", ".join(labels) if labels else "none"),
                      "comment:\n" + a["comment"] if a["comment"] else "comment: none"])


def set_priority(path: str | Path, batch: dict, pairs: list[str]) -> None:
    """Write the user's priorities (`N=P`) into the proposals file: all pairs are checked first, the file is replaced atomically."""
    parsed = []
    for pair in pairs:
        n, _, level = pair.partition("=")
        if not n.strip().isdigit() or level.upper() not in prio.LEVELS:
            raise PlatformError("--set takes N=P0|P1|P2")
        parsed.append((int(n), level.upper()))
    effective = {r["number"]: r for r in load_proposals(path, batch)}
    known = {i["number"] for i in batch["issues"]}
    for n, _ in parsed:
        if n not in known:
            raise PlatformError(f"#{n} is not an issue of the batch")
        cls = effective[n]["class"] if n in effective else "handled issue"
        if cls not in PRIORITY_CLASSES:
            raise PlatformError(f"#{n} is a {cls}: it gets no priority")
    target = Path(path)
    raw = json.loads(target.read_text())
    for n, level in parsed:
        now = effective[n]
        for r in raw["rows"]:
            if r.get("number") == n:
                r["priority_reason"] = now["priority_reason"] if level == now["priority"] else CHANGED_BY_YOU
                r["priority"], r["priority_decided"] = level, True
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(raw, f, indent=2)
    os.replace(tmp, target)


def run(slug: str, proposals: str, *, show_number: int | None = None, as_json: bool = False, what: str,
        sets: list[str] | None = None) -> str:
    """The text `overview` or `confirm` prints (JSON when asked); `sets` are `confirm --set N=P` pairs written first."""
    batch = triage_batch.load(slug)
    if sets:
        set_priority(proposals, batch, sets)
    rows = load_proposals(proposals, batch)
    if what == "overview":
        return json.dumps(overview_json(batch, rows), indent=2) if as_json else overview(batch, rows)
    if show_number is not None:
        return show(batch, rows, show_number)
    if as_json:
        return json.dumps({"lines": [{k: l[k] for k in ("number", "class", "text", "priority", "priority_reason", "decide")} for l in plan(batch, rows)], "choices": CHOICES}, indent=2)
    return confirm(batch, rows)
