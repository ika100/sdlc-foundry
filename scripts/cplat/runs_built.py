"""How a PR was built (spec 133, ADR-079): a generated, collapsed block from the run's local records.

  cplat platform runs report --pr <run-id> [--dir D]     print the block (in-progress record, else the local buffer)
  pr_section(repo, spec) -> str | None                   the block for `cplat pr open`, or None without a run for the spec

Only recorded facts: the run record and the local runs it resumes, the budget ledger, the spec's spec.md and verification.md,
and the findings the test review left open in the reviewed commit (spec 179).
Every value passes through the run records' redaction; no prompts, no diffs. Contract: docs/specs/133-*/design.md.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

import feedback
import runs
import testreview
from core import PlatformError

START, END = "<!-- cplat:how-built -->", "<!-- /cplat:how-built -->"
MAX_LINES = 10
MAX_CHARS = 200
MAX_CHAIN = 10
NOT_RECORDED = "not recorded"
LIMITS = ("minutes", "invocations", "reruns", "cost")
_BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n?", re.S)


def _v(value) -> str:
    """A record or file value as it may appear in the block: redacted, one line, at most MAX_CHARS."""
    text = " ".join(feedback.redact(str(value)).split())
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 1] + "…"


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


# ---------------- finding the run ----------------

def find(run_id: str | None) -> dict | None:
    """The in-progress record, else the newest record with that id in the local buffer."""
    if not run_id:
        return None
    rec = runs.active(run_id)
    if rec is not None:
        return rec
    try:
        found = [i for i in runs._read_buffer() if i.get("run_id") == run_id and not i.get("followup")]
    except Exception:  # noqa: BLE001
        return None
    return found[-1] if found else None


def chain(rec: dict) -> list[dict]:
    """The record and the local records it resumes, newest first."""
    out, seen = [rec], {rec.get("run_id")}
    while len(out) < MAX_CHAIN:
        prev = out[-1].get("resumes")
        if not prev or prev in seen:
            break
        found = find(prev)
        if found is None:
            break
        seen.add(prev)
        out.append(found)
    return out


# ---------------- facts ----------------

def _when(text) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _seconds(rec: dict) -> float | None:
    start = _when(rec.get("started_at"))
    end = _when(rec.get("ended_at")) if rec.get("ended_at") else runs.utcnow()
    return max(0.0, (end - start).total_seconds()) if start and end else None


def _dur(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return "<1m"
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def _events(rec: dict) -> list[tuple[str, dict]]:
    """(agent, event) for every agent event, in recording order per agent."""
    out = []
    for entry in _list(rec.get("agents")):
        if not isinstance(entry, dict):
            continue
        for ev in _list(entry.get("events")):
            if isinstance(ev, dict):
                out.append((str(entry.get("agent") or "unknown"), ev))
    return out


def _ledger(run_ids: list[str]) -> dict | None:
    try:
        import budget
        for _, data in budget._all():
            if set(run_ids) & set(data.get("roots") or []):
                return data
    except Exception:  # noqa: BLE001
        pass
    return None


def _num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _budget_line(data: dict | None) -> str:
    if data is None:
        return "budget: not recorded"
    try:
        import budget
        used = budget.used_of(data)
    except Exception:  # noqa: BLE001
        used = {}
    limits, parts = _dict(data.get("limits")), []
    for name in LIMITS:
        limit, value = limits.get(name), used.get(name)
        if name == "cost":
            spent = f"${value:.2f}" if isinstance(value, (int, float)) else "unknown"
            shown = "off" if limit is None else f"${_num(limit)}"
        else:
            spent = _num(int(round(value))) if isinstance(value, (int, float)) and name == "minutes" else \
                (_num(value) if value is not None else "unknown")
            shown = "off" if limit is None else _num(limit)
        parts.append(f"{name} {spent} of {shown}")
    return "budget: " + " · ".join(parts)


def _spec_dir(repo: Path, spec) -> Path | None:
    if not spec:
        return None
    m = re.match(r"(\d+)", str(spec))
    base = Path(repo) / "docs" / "specs"
    exact = base / str(spec)
    if exact.is_dir():
        return exact
    if m:
        found = sorted(base.glob(f"{m.group(1)}-*"))
        return found[0] if found else None
    return None


def _section(text: str, heading: str) -> list[str]:
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower() == heading.lower()
            continue
        if inside:
            lines.append(line)
    return lines


def answered(spec_dir: Path | None) -> int:
    try:
        text = (spec_dir / "spec.md").read_text() if spec_dir else ""
    except OSError:
        return 0
    return sum(1 for line in _section(text, "Open questions") if "Answered" in line)


def assumed(spec_dir: Path | None) -> tuple[int, int]:
    """(decisions taken by default, of them revised later) in spec.md's `## Assumptions` (spec 149)."""
    try:
        text = (spec_dir / "spec.md").read_text() if spec_dir else ""
    except OSError:
        return 0, 0
    items = [m.group(1) for ln in _section(text, "Assumptions") if (m := re.match(r"^\s*[-*]\s+(\S.*)$", ln))
             and m.group(1).rstrip(".").lower() not in {"none", "n/a"}]
    return len(items), sum(1 for i in items if i.startswith("~~"))


_ITEM = re.compile(r"^(?:[-*]|\d+\.)\s+(.*)$")


def accepted_deviations(spec_dir: Path | None) -> list[str] | None:
    """First sentences of the accepted top-level items of `## Deviations from the plan`; None without verification.md."""
    try:
        text = (spec_dir / "verification.md").read_text() if spec_dir else None
    except OSError:
        text = None
    if text is None:
        return None
    items: list[str] = []
    for line in _section(text, "Deviations from the plan"):
        m = _ITEM.match(line)
        if m:
            items.append(m.group(1))
        elif items and line.strip():
            items[-1] += " " + line.strip()
    out = []
    for item in items:
        if not re.search(r"\b(acceptable|accepted)\b", item, re.I) or re.search(r"\bnot acceptable\b", item, re.I):
            continue
        plain = item.replace("**", "").strip()
        out.append(re.split(r"(?<=[.!?])\s", plain, maxsplit=1)[0])
    return out


def collect(rec: dict, repo: Path) -> dict:
    """The facts of the block (unredacted; render redacts)."""
    recs = chain(rec)
    secs = [s for s in (_seconds(r) for r in recs) if s is not None]
    events = _events(rec)
    execution = _dict(rec.get("execution"))
    ledger = _ledger([str(r.get("run_id")) for r in recs])
    spec_dir = _spec_dir(repo, rec.get("spec"))

    decisions: list[str] = []
    for ch in _list(_dict(ledger).get("changes")):
        if isinstance(ch, dict):
            old, new = ch.get("from"), ch.get("to")
            verb = "raised" if isinstance(old, (int, float)) and isinstance(new, (int, float)) and new > old else \
                ("lowered" if isinstance(old, (int, float)) and isinstance(new, (int, float)) else "changed")
            decisions.append(f"budget {ch.get('limit')} {verb} from {'off' if old is None else _num(old)} "
                             f"to {'off' if new is None else _num(new)}")
    for r in recs:
        esc = _dict(r.get("escalation"))
        if esc.get("cause") == "decision":
            decisions.append(f"stopped for a decision: {esc.get('reason') or 'no reason given'} (run {r.get('run_id')})")
    for _, ev in events:
        if ev.get("kind") == "refused-test-diff":
            decisions.append(f"test-diff refused `{ev.get('file')}` (task {ev.get('task') or '-'}): {ev.get('reason')}")
    if isinstance(rec.get("approved_test_diffs"), list):     # the #324 hook (design.md)
        for item in rec["approved_test_diffs"]:
            if isinstance(item, dict):
                what = "test tightened by an agent" if item.get("kind") == "tightened" else "test change approved"
                decisions.append(f"{what} `{item.get('file')}` (task {item.get('task') or '-'}): "
                                 f"{item.get('reason') or 'no reason given'}")
    else:
        decisions.append("user-approved test changes: not recorded (#324)")
    n = answered(spec_dir)
    if n:
        decisions.append(f"open questions answered in spec.md: {n}")
    taken, revised = assumed(spec_dir)
    if taken:
        decisions.append(f"assumptions approved with the spec: {taken}" + (f", {revised} revised later" if revised else ""))

    handbacks: list[str] = []
    for agent, ev in events:
        kind = ev.get("kind")
        if kind == "fix-round":
            handbacks.append(f"{ev.get('task') or '(no task)'} → {agent}: {ev.get('cause')}")
        elif kind == "red-ci":
            checks = [str(c) for c in _list(ev.get("checks"))] or [str(ev.get("check"))]
            handbacks.append(f"red CI: {', '.join(checks)} → {agent}")
        elif kind == "finding":
            what = ev.get("criterion") or ev.get("task")
            handbacks.append(f"finding {what} ({ev.get('severity')}, cycle {ev.get('cycle')}) → {agent}")
        elif kind == "tester":
            handbacks.append(f"tester: {ev.get('criterion') or ev.get('test')} {ev.get('reason')}")
        elif kind == "merge-conflict":
            handbacks.append(f"merge conflict {ev.get('task')} with {ev.get('with') or 'unknown'}: {ev.get('outcome')}")
        elif kind == "re-plan":
            handbacks.append(f"re-plan {ev.get('task')} → {agent}")
        elif kind == "task-merge":
            handbacks.append(f"merged task {ev.get('task')} into {ev.get('into')}: {ev.get('reason')}")
        elif kind == "smoke":
            handbacks.append(f"smoke test tightened {ev.get('test')}: {ev.get('finding')}")
    if spec_dir is not None:
        try:
            for item in testreview.unresolved(repo, spec_dir.name):
                handbacks.append(f"test review left open: {item['test']} ({item['criterion']}): {item['what']}")
        except Exception:  # noqa: BLE001  # reading git must never break the block
            pass

    gates = _dict(rec.get("gates"))
    return {
        "run_id": rec.get("run_id"), "kind": rec.get("kind"),
        "wall": _dur(sum(secs)) if secs else NOT_RECORDED, "runs": len(recs),
        "execution": (f"{'sequentially' if execution['mode'] == 'sequential' else 'in parallel batches'}"
                      + (f" ({execution['reason']})" if execution.get("reason") else ""))
        if execution.get("mode") in ("parallel", "sequential") else NOT_RECORDED,
        "replans": len(_list(rec.get("replans"))),
        "ci_rounds": rec.get("ci_rounds") if isinstance(rec.get("ci_rounds"), int) else 0,
        "reruns": len(_list(rec.get("reruns"))),
        "gates": " · ".join(f"{k} {v}" for k, v in gates.items()) or NOT_RECORDED,
        "budget": _budget_line(ledger),
        "agents": sorted({str(e.get("agent")) for e in _list(rec.get("agents")) if isinstance(e, dict) and e.get("agent")}),
        "decisions": decisions, "handbacks": handbacks, "deviations": accepted_deviations(spec_dir),
    }


# ---------------- rendering ----------------

def _items(values: list[str], empty: str) -> list[str]:
    if not values:
        return [f"- {empty}"]
    out = [f"- {_v(v)}" for v in values[:MAX_LINES]]
    if len(values) > MAX_LINES:
        out.append(f"- … and {len(values) - MAX_LINES} more")
    return out


def render(f: dict) -> str:
    over = f" over {f['runs']} runs" if f["runs"] > 1 else ""
    ran = [f"run {f['run_id']} ({f['kind']}), wall time {f['wall']}{over}",
           f"tasks: {f['execution']}",
           f"re-plans: {f['replans']} · CI rounds: {f['ci_rounds']} · reruns: {f['reruns']}",
           f"gates: {f['gates']}", f['budget'],
           f"agents: {', '.join(f['agents']) or NOT_RECORDED}"]
    devs = f["deviations"]
    lines = [START, "<details><summary>How this was built</summary>", "",
             f"_Generated by `cplat platform runs report --pr {_v(f['run_id'])}` from the run's local records: "
             "no prompts, no diffs._", "",
             "#### How it ran", *[f"- {_v(x)}" for x in ran], "",
             "#### User decisions", *_items(f["decisions"], "none recorded"), "",
             "#### Hand-backs and fix rounds", *_items(f["handbacks"], "none"), "",
             "#### Deviations the reviewer accepted",
             *(["- no verification.md yet"] if devs is None else _items(devs, "none listed")), "",
             "</details>", END]
    return "\n".join(lines) + "\n"


def block(run_id: str, repo: Path) -> str:
    rec = find(run_id)
    if rec is None:
        raise PlatformError(f"no run {run_id} on this machine (neither in progress nor in the local buffer)",
                            hint="cplat platform runs report --pr <run-id> reads only this machine's records; "
                                 "check the run id printed by `cplat platform runs begin`")
    return render(collect(rec, Path(repo)))


def _same_spec(a, b) -> bool:
    if not a or not b:
        return True
    na, nb = re.match(r"\d+", str(a)), re.match(r"\d+", str(b))
    return int(na.group()) == int(nb.group()) if na and nb else str(a) == str(b)


def pr_section(repo: Path, spec: str | None) -> str | None:
    """The block for the checkout's current run, or None (no run, or a run for another spec)."""
    rid = runs.current_run(Path(repo))
    rec = find(rid)
    if rec is None or not _same_spec(rec.get("spec"), spec):
        return None
    return render(collect(rec, Path(repo)))


def apply(body: str, section: str) -> str:
    """Replace an earlier block, else append the block after one blank line."""
    if START in body and END in body:
        return _BLOCK.sub(lambda _m: section, body, count=1)
    return body.rstrip("\n") + "\n\n" + section
