"""`cplat platform runs journey …` (spec 136, ADR-081): one run record of kind `journey` per run of the demo journey, with
every stage's wall-clock, working, person-wait and external-wait minutes, its PRs and its extra rounds.

  begin [--task-version N] [--model M] [--repo R] [--at T]        open the journey (one at a time on this machine)
  stage <id> start|end [--at T]                                   a stage of the fixed script (ids: STAGES)
  wait person|external start|end [--reason R] [--at T]            a wait of the journey, as it happens
  wait person|external add --minutes M [--at T] [--reason R]      a wait measured afterwards (T: its start)
  pr <url> [--stage <id>]                                         a PR the stage opened (default: the open stage started last)
  round <kind> --cause C [--stage <id>] [--note N]                an extra round of the stage
  show [--json]                                                   the stage table so far
  end --outcome done|failed|escalated|abandoned [--reason R] [--at T]

Working time = wall clock − person-wait; a part and the journey are spans over their (overlapping) stages, not sums.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path

import runs
from core import PlatformError

SCHEMA = 1
STAGES: list[tuple[str, int, int]] = [   # (id, part, budget in minutes): the table of spec 136
    ("1.scaffold", 1, 2), ("1.cluster", 1, 2), ("1.spec", 1, 3), ("1.plan", 1, 2), ("1.build", 1, 10), ("1.pr-ci", 1, 3),
    ("1.deploy-dev", 1, 2),
    ("2.scaffold", 2, 2), ("2.spec", 2, 5), ("2.plan", 2, 3), ("2.build", 2, 12), ("2.pr-ci", 2, 3), ("2.deploy-dev", 2, 2),
    ("3.env-settings", 3, 2), ("3.staging-prod", 3, 8),
]
STAGE_IDS = [s for s, _, _ in STAGES]
PART_BUDGETS = {1: 20, 2: 30, 3: 10}
JOURNEY_BUDGET, JOURNEY_INTERIM, JOURNEY_STRETCH = 60, 90, 50
ROUND_KINDS = ("fix-round", "ci-rerun", "escalation", "resumed-session", "reworked-spec", "reworked-plan")
WAIT_KINDS = ("person", "external")
RAW = "journey_raw"
TIME_KEYS = ("wall_minutes", "working_minutes", "person_wait_minutes", "external_wait_minutes")

Interval = tuple[datetime.datetime, datetime.datetime]


# ---------------- time ----------------

def parse_time(text: str) -> datetime.datetime:
    try:
        t = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise PlatformError(f"not a time: {text!r}", hint="use UTC, e.g. 2026-11-05T08:30Z or 2026-11-05T08:30:00Z") from None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(datetime.timezone.utc)


def _iso(t: datetime.datetime) -> str:
    return runs._iso(t)


def _union(items: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for a, b in sorted(i for i in items if i[1] > i[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _minus(items: list[Interval], cut: list[Interval]) -> list[Interval]:
    """The parts of `items` outside `cut`."""
    cuts, out = _union(cut), []
    for a, b in _union(items):
        cur = a
        for c, d in cuts:
            if d <= cur or c >= b:
                continue
            if c > cur:
                out.append((cur, c))
            cur = max(cur, d)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
    return out


def _within(items: list[Interval], span: Interval) -> float:
    """Minutes of the (united) intervals inside span."""
    s, e = span
    return sum(max(0.0, (min(b, e) - max(a, s)).total_seconds()) for a, b in _union(items)) / 60


def _length(items: list[Interval]) -> float:
    return sum((b - a).total_seconds() for a, b in _union(items)) / 60


def _r(x: float) -> float:
    return round(x + 0.0, 1)


def _times(span: Interval, person: list[Interval], external: list[Interval]) -> dict:
    wall = (span[1] - span[0]).total_seconds() / 60
    p = _within(person, span)
    x = _within(_minus(external, person), span)
    return {"started_at": _iso(span[0]), "ended_at": _iso(span[1]), "wall_minutes": _r(wall), "working_minutes": _r(wall - p),
            "person_wait_minutes": _r(p), "external_wait_minutes": _r(x)}


def _not_run() -> dict:
    return {"status": "not run", "started_at": None, "ended_at": None, **{k: None for k in TIME_KEYS}}


# ---------------- the model ----------------

def compute(raw: dict, now: datetime.datetime) -> dict:
    """The `journey` section (design § The record) from the raw state; open stages and waits end at `now`."""
    waits = [w for w in raw.get("waits") or [] if isinstance(w, dict) and w.get("kind") in WAIT_KINDS and w.get("started_at")]

    def span_of(item: dict) -> Interval:
        a = parse_time(item["started_at"])
        b = parse_time(item["ended_at"]) if item.get("ended_at") else now
        return a, max(a, b)

    person = [span_of(w) for w in waits if w["kind"] == "person"]
    external = [span_of(w) for w in waits if w["kind"] == "external"]
    stages, spans = [], {}
    for sid, part, budget in STAGES:
        st = (raw.get("stages") or {}).get(sid) or {}
        urls = list(dict.fromkeys(st.get("prs") or []))
        rounds = [dict(r) for r in st.get("rounds") or []]
        entry = {"id": sid, "part": part}
        if st.get("started_at"):
            spans[sid] = span_of(st)
            entry |= {"status": "done" if st.get("ended_at") else "stopped", **_times(spans[sid], person, external)}
        else:
            entry |= _not_run()
        stages.append(entry | {"budget_minutes": budget, "prs": len(urls), "pr_urls": urls, "extra_rounds": rounds})

    def group(members: list[dict]) -> dict:
        ran = [spans[m["id"]] for m in members if m["id"] in spans]
        prs = sum(m["prs"] for m in members)
        rounds = sum(len(m["extra_rounds"]) for m in members)
        if not ran:
            return {**_not_run(), "prs": prs, "extra_rounds": rounds, "stages_sum_minutes": None, "overlap_minutes": None}
        span = (min(a for a, _ in ran), max(b for _, b in ran))
        total = sum(m["working_minutes"] for m in members if m["id"] in spans)
        covered = _length(_minus(ran, person))
        stopped = any(m["status"] == "stopped" for m in members)
        return {"status": "stopped" if stopped else "done", **_times(span, person, external), "prs": prs,
                "extra_rounds": rounds, "stages_sum_minutes": _r(total), "overlap_minutes": _r(max(0.0, total - covered))}

    parts = [{"part": n, **group([s for s in stages if s["part"] == n]), "budget_minutes": b} for n, b in PART_BUDGETS.items()]
    total = {**group(stages), "budget_minutes": JOURNEY_BUDGET, "interim_minutes": JOURNEY_INTERIM,
             "stretch_minutes": JOURNEY_STRETCH}
    return {"schema": SCHEMA, "task_version": raw.get("task_version", 1), "coordinator_model": raw.get("coordinator_model") or "unknown",
            "stages": stages, "parts": parts, "total": total,
            "waits": [{"kind": w["kind"], "started_at": w["started_at"], "ended_at": w.get("ended_at") or _iso(now),
                       "reason": w.get("reason")} for w in waits]}


# ---------------- the pointer ----------------

def _pointer() -> Path:
    return runs.state_dir() / "journey.json"


def open_run() -> str | None:
    """The run_id of the open journey on this machine, or None."""
    try:
        rid = json.loads(_pointer().read_text()).get("run_id")
    except (OSError, ValueError, AttributeError):
        return None
    return rid if rid and runs.active(rid) is not None else None


def _require() -> tuple[str, dict]:
    rid = open_run()
    rec = runs.active(rid) if rid else None
    if not rid or rec is None:
        raise PlatformError("no journey is open on this machine: start one with `cplat platform runs journey begin`")
    return rid, rec.get(RAW) or {}


def _change(rid: str, change) -> None:
    def apply(rec: dict) -> None:
        change(rec.setdefault(RAW, {}))
    if runs.mutate(rid, apply) != "ok":
        raise PlatformError(f"the journey record {rid} could not be updated")


def _when(ns: argparse.Namespace) -> datetime.datetime:
    return parse_time(ns.at) if getattr(ns, "at", None) else runs.utcnow()


# ---------------- verbs ----------------

def begin(ns: argparse.Namespace) -> list[str]:
    if open_run():
        raise PlatformError(f"journey {open_run()} is still open: end it first with "
                            "`cplat platform runs journey end --outcome <done|abandoned|...>`")
    if ns.task_version < 1:
        raise PlatformError("--task-version must be at least 1")
    started = _iso(_when(ns))
    session = os.environ.pop("CLAUDE_CODE_SESSION_ID", None) if ns.at else None   # a reconstructed journey claims no session
    try:
        rid = runs.start("journey", repo=ns.repo, started_at=started)
    finally:
        if session is not None:
            os.environ["CLAUDE_CODE_SESSION_ID"] = session
    if not rid:
        raise PlatformError("the journey record could not be started", hint=f"is {runs.state_dir()} writable?")
    runs.set_section(rid, RAW, {"task_version": ns.task_version, "coordinator_model": ns.model or "unknown", "stages": {},
                                "waits": []})
    runs._atomic_write(_pointer(), json.dumps({"run_id": rid}))
    return [f"journey {rid}"]


def _stage_id(sid: str) -> str:
    if sid not in STAGE_IDS:
        raise PlatformError(f"unknown stage '{sid}'", hint="stages: " + ", ".join(STAGE_IDS))
    return sid


def stage(ns: argparse.Namespace) -> list[str]:
    rid, raw = _require()
    sid, when = _stage_id(ns.id), _iso(_when(ns))
    have = (raw.get("stages") or {}).get(sid) or {}
    if ns.action == "end" and not have.get("started_at"):
        raise PlatformError(f"stage {sid} was not started", hint=f"cplat platform runs journey stage {sid} start [--at T]")
    if ns.action == "end" and parse_time(when) < parse_time(have["started_at"]):
        raise PlatformError(f"stage {sid} cannot end before it started ({have['started_at']})")

    def change(r: dict) -> None:
        st = r.setdefault("stages", {}).setdefault(sid, {})
        if ns.action == "start":
            st.setdefault("started_at", when)
        else:
            st["ended_at"] = max(when, st.get("ended_at") or when)
    _change(rid, change)
    return [f"stage {sid} {'started' if ns.action == 'start' else 'ended'} at {when}"]


def wait(ns: argparse.Namespace) -> list[str]:
    rid, raw = _require()
    open_ones = [w for w in raw.get("waits") or [] if w.get("kind") == ns.kind and not w.get("ended_at")]
    if ns.action == "start":
        if open_ones:
            raise PlatformError(f"a {ns.kind} wait is already open (since {open_ones[0]['started_at']})",
                                hint=f"cplat platform runs journey wait {ns.kind} end")
        item = {"kind": ns.kind, "started_at": _iso(_when(ns)), "ended_at": None, "reason": ns.reason}
        _change(rid, lambda r: r.setdefault("waits", []).append(item))
        return [f"{ns.kind} wait started at {item['started_at']}"]
    if ns.action == "end":
        if not open_ones:
            raise PlatformError(f"no {ns.kind} wait is open", hint=f"cplat platform runs journey wait {ns.kind} start")
        when = _iso(max(_when(ns), parse_time(open_ones[0]["started_at"])))

        def close(r: dict) -> None:
            for w in r.get("waits") or []:
                if w.get("kind") == ns.kind and not w.get("ended_at"):
                    w["ended_at"] = when
        _change(rid, close)
        return [f"{ns.kind} wait ended at {when}"]
    if ns.minutes is None or ns.minutes <= 0:
        raise PlatformError("wait add needs --minutes greater than 0")
    end = parse_time(ns.at) + datetime.timedelta(minutes=ns.minutes) if ns.at else runs.utcnow()
    item = {"kind": ns.kind, "started_at": _iso(end - datetime.timedelta(minutes=ns.minutes)), "ended_at": _iso(end),
            "reason": ns.reason}
    _change(rid, lambda r: r.setdefault("waits", []).append(item))
    return [f"{ns.kind} wait of {ns.minutes:g} min added from {item['started_at']}"]


def _target(raw: dict, given: str | None) -> str:
    if given:
        return _stage_id(given)
    started = [(st["started_at"], sid) for sid, st in (raw.get("stages") or {}).items()
               if st.get("started_at") and not st.get("ended_at")]
    if not started:
        raise PlatformError("no stage is open", hint="name it with --stage <id>")
    return max(started)[1]


def pr(ns: argparse.Namespace) -> list[str]:
    rid, raw = _require()
    sid = _target(raw, ns.stage)
    _change(rid, lambda r: r.setdefault("stages", {}).setdefault(sid, {}).setdefault("prs", []).append(ns.url))
    return [f"stage {sid}: PR {ns.url}"]


def round_(ns: argparse.Namespace) -> list[str]:
    if ns.kind not in ROUND_KINDS:
        raise PlatformError(f"unknown kind of extra round '{ns.kind}'", hint="kinds: " + ", ".join(ROUND_KINDS))
    if ns.cause not in runs.CAUSES:
        raise PlatformError(f"unknown cause '{ns.cause}'", hint="causes: " + ", ".join(runs.CAUSES))
    rid, raw = _require()
    sid = _target(raw, ns.stage)
    item = {"kind": ns.kind, "cause": ns.cause, "note": ns.note}
    _change(rid, lambda r: r.setdefault("stages", {}).setdefault(sid, {}).setdefault("rounds", []).append(item))
    return [f"stage {sid}: {ns.kind} ({ns.cause})"]


def _close(raw: dict, when: str) -> dict:
    """The raw state with open stages kept open (they become `stopped`) and open waits ended at `when`."""
    out = json.loads(json.dumps(raw))
    for w in out.get("waits") or []:
        if not w.get("ended_at"):
            w["ended_at"] = when
    return out


def _fmt(x) -> str:
    return "-" if x is None else f"{x:g}"


def table(section: dict) -> list[str]:
    lines = [f"{'stage':<16}{'status':<9}{'working':>8}{'wall':>7}{'person':>8}{'external':>9}{'budget':>7}{'PRs':>5}{'rounds':>7}"]
    rows = [(s["id"], s) for s in section["stages"]] + [(f"part {p['part']}", p) for p in section["parts"]] + [("journey", section["total"])]
    for name, s in rows:
        rounds = s["extra_rounds"] if isinstance(s["extra_rounds"], int) else len(s["extra_rounds"])
        lines.append(f"{name:<16}{s['status']:<9}{_fmt(s['working_minutes']):>8}{_fmt(s['wall_minutes']):>7}"
                     f"{_fmt(s['person_wait_minutes']):>8}{_fmt(s['external_wait_minutes']):>9}{s['budget_minutes']:>7}"
                     f"{s['prs']:>5}{rounds:>7}")
    return lines


def show(ns: argparse.Namespace) -> list[str]:
    rid, raw = _require()
    section = compute(raw, runs.utcnow())
    for s in section["stages"]:   # still running, not stopped: the journey has not ended
        s["status"] = "open" if s["status"] == "stopped" else s["status"]
    if ns.json:
        return [json.dumps(section, indent=2)]
    return [f"journey {rid} (so far)", *table(section)]


def end(ns: argparse.Namespace) -> list[str]:
    rid, raw = _require()
    when = _when(ns)
    section = compute(_close(raw, _iso(when)), when)
    runs.mutate(rid, lambda rec: rec.pop(RAW, None))
    esc = {"reason": ns.reason or "journey stopped", "cause": "unknown"} if ns.outcome == "escalated" else None
    runs.finish(rid, ns.outcome, escalation=esc, fields={"journey": section})
    _pointer().unlink(missing_ok=True)
    return [f"journey {rid}: {ns.outcome}", *table(section)]


def note_external_wait(seconds: float, kind: str) -> None:
    """core.run waited `seconds` for GitHub's rate limit: an external wait of the open journey, if any. Never raises."""
    try:
        rid = open_run()
        if not rid or seconds <= 0:
            return
        now = runs.utcnow()
        item = {"kind": "external", "started_at": _iso(now - datetime.timedelta(seconds=seconds)), "ended_at": _iso(now),
                "reason": f"GitHub rate limit ({kind})"}
        runs.mutate(rid, lambda rec: rec.setdefault(RAW, {}).setdefault("waits", []).append(item))
    except Exception:  # noqa: BLE001  (recording never changes a command)
        pass


# ---------------- CLI ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat platform runs journey", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    b = sub.add_parser("begin", help="open a journey record")
    b.add_argument("--task-version", type=int, default=1)
    b.add_argument("--model", help="the coordinator model (opus, sonnet, ...)")
    b.add_argument("--repo", metavar="OWNER/NAME", help="the journey's gitops repo, for the report's --repo filter")
    s = sub.add_parser("stage", help="start or end a stage")
    s.add_argument("id", help="stage id: " + ", ".join(STAGE_IDS))
    s.add_argument("action", choices=["start", "end"])
    w = sub.add_parser("wait", help="a person or external wait")
    w.add_argument("kind", choices=WAIT_KINDS)
    w.add_argument("action", choices=["start", "end", "add"])
    w.add_argument("--minutes", type=float)
    w.add_argument("--reason")
    r = sub.add_parser("pr", help="a PR a stage opened")
    r.add_argument("url")
    r.add_argument("--stage")
    o = sub.add_parser("round", help="an extra round of a stage")
    o.add_argument("kind", help="one of " + ", ".join(ROUND_KINDS))
    o.add_argument("--cause", required=True, help="one of " + ", ".join(runs.CAUSES))
    o.add_argument("--stage")
    o.add_argument("--note")
    sh = sub.add_parser("show", help="the stage table so far")
    sh.add_argument("--json", action="store_true")
    e = sub.add_parser("end", help="end the journey and write its record")
    e.add_argument("--outcome", required=True, choices=runs.OUTCOMES)
    e.add_argument("--reason")
    for x in (b, s, w, r, o, e):
        x.add_argument("--at", metavar="TIME", help="UTC time of the event (default: now)")
    return p


VERBS = {"begin": begin, "stage": stage, "wait": wait, "pr": pr, "round": round_, "show": show, "end": end}


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    for line in VERBS[ns.verb](ns):
        print(line)
    return 0
