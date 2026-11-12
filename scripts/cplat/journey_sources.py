"""Spec 181: everything a journey measurement reads from outside the transcripts.

  load_records(start, end, records_file) -> (records, followups)   run store + local buffer, or a --records file
  system_tree(records, coordinator_sessions, repos, start, end)    the system ship runs and every record reachable from them
  repo_sessions(tree, coordinator_sessions, root) -> (sessions, warnings)   {repo, session, path | None, span}
  record_evidence(records, tree, repos, start, end) -> [(a, b, kind)]      kinds the run records know
  gh_runs(repo) / actions(repos, start, end) -> (runs, intervals)           GitHub Actions runs (the seam tests replace)
  journey_record(records, run_id) -> dict | None

All times are timezone-aware UTC datetimes; spans are (start, end) pairs clipped to the measured window.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Callable

import core
import runs_report
import transcripts

Span = tuple[datetime.datetime, datetime.datetime]
NO_RECORD_WARNING = "WARNING: no system ship run record overlaps the journey; repo sessions are not counted"


def parse_ts(value) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        when = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _record_span(rec: dict) -> Span | None:
    a, b = parse_ts(rec.get("started_at")), parse_ts(rec.get("ended_at"))
    return (a, b) if a and b and b >= a else None


def _overlaps(span: Span | None, start: datetime.datetime, end: datetime.datetime) -> bool:
    return span is not None and span[0] < end and span[1] > start


def _clip(span: Span, start: datetime.datetime, end: datetime.datetime) -> Span | None:
    a, b = max(span[0], start), min(span[1], end)
    return (a, b) if b > a else None


def _sessions(rec: dict) -> list[str]:
    usage = rec.get("usage")
    found = usage.get("sessions") if isinstance(usage, dict) else None
    return [s for s in found if isinstance(s, str)] if isinstance(found, list) else []


def load_records(start: datetime.datetime, end: datetime.datetime, records_file: Path | None) -> tuple[list[dict], list[dict]]:
    """Run records and follow-ups: the `--records` file alone, or the local buffer plus the store's days (start-1 .. end+1)."""
    import runs
    texts: list[str] = []
    if records_file is not None:
        texts.append(Path(records_file).read_text())
    else:
        texts.append("".join(json.dumps(i) + "\n" for i in runs._read_buffer()))
        slug = runs.configured_repo()
        if slug:
            try:
                store = runs.open_store(slug)
                days = [start.date() - datetime.timedelta(days=1)]
                while days[-1] < end.date() + datetime.timedelta(days=1):
                    days.append(days[-1] + datetime.timedelta(days=1))
                texts += [text for _, text in store.read(days)]
            except Exception:  # noqa: BLE001  an unreachable store is skipped; the buffer still counts
                pass
    records, followups, _ = runs_report.parse(texts)
    seen: set[str] = set()
    unique = []
    for rec in records:
        rid = rec.get("run_id")
        if rid in seen:
            continue
        seen.add(rid)
        unique.append(rec)
    seen_f: set[tuple] = set()
    uf = []
    for f in followups:
        key = (f.get("run_id"), f.get("signature"), f.get("at"))
        if key not in seen_f:
            seen_f.add(key)
            uf.append(f)
    return unique, uf


def system_tree(records: list[dict], coordinator_sessions: list[str], repos: list[str], start: datetime.datetime,
                end: datetime.datetime) -> list[dict]:
    """The `product-ship` runs of the window that belong to the journey, and every record reachable by `parent` / `ships`."""
    coordinators = set(coordinator_sessions)
    by_id = {r["run_id"]: r for r in records if r.get("run_id")}
    roots = [r for r in records if r.get("kind") == "product-ship" and _overlaps(_record_span(r), start, end)
             and (coordinators & set(_sessions(r)) or r.get("repo") in repos)]
    tree: dict[str, dict] = {}
    todo = list(roots)
    while todo:
        rec = todo.pop()
        rid = rec.get("run_id")
        if rid in tree:
            continue
        tree[rid] = rec
        parent = rec.get("parent")
        if isinstance(parent, str) and parent in by_id:
            todo.append(by_id[parent])
        for child in rec.get("ships") or []:
            if isinstance(child, str) and child in by_id:
                todo.append(by_id[child])
        todo += [r for r in records if r.get("parent") == rid and r.get("run_id") not in tree]
    return list(tree.values())


def repo_sessions(tree: list[dict], coordinator_sessions: list[str], root: Path,
                  window: Span | None = None) -> tuple[list[dict], list[str]]:
    """Every non-coordinator session of the tree: {repo, session, path | None, span}; a missing transcript warns once."""
    coordinators = set(coordinator_sessions)
    sessions, warnings, seen = [], [], set()
    for rec in tree:
        span = _record_span(rec)
        if span and window:
            span = _clip(span, *window)
        for sid in _sessions(rec):
            if sid in coordinators or sid in seen:
                continue
            seen.add(sid)
            path = transcripts.find(sid, root)
            if path is None:
                warnings.append(f"WARNING: repo {rec.get('repo') or '?'}: session {sid} has no transcript on this machine; "
                                f'its minutes count as "repo session, no transcript"')
            sessions.append({"repo": rec.get("repo"), "session": sid, "path": path, "span": span})
    return sessions, warnings


def record_evidence(records: list[dict], tree: list[dict], repos: list[str], start: datetime.datetime, end: datetime.datetime,
                    command_wait: Callable[[str], str | None] | None = None) -> list[tuple[datetime.datetime, datetime.datetime, str]]:
    """Kinded intervals from the records of the tree or of a journey repo (clipped to the window)."""
    if command_wait is None:
        from journey_timeline import command_wait
    ids = {r.get("run_id") for r in tree}
    out = []

    def add(a, b, kind):
        a, b = parse_ts(a), parse_ts(b)
        if a and b:
            span = _clip((a, b), start, end)
            if span:
                out.append((span[0], span[1], kind))

    for rec in records:
        if rec.get("run_id") not in ids and rec.get("repo") not in repos:
            continue
        if not _overlaps(_record_span(rec), start, end):
            continue
        kind = rec.get("kind")
        if kind == "pr-wait":
            add(rec.get("started_at"), rec.get("ended_at"), "ci")
        elif kind == "verify":
            add(rec.get("started_at"), rec.get("ended_at"), "smoke")
        elif kind == "wait":
            wait = rec.get("wait") if isinstance(rec.get("wait"), dict) else {}
            found = command_wait("cplat " + str(wait.get("command", "")))
            if found and found != "wait":
                add(rec.get("started_at"), rec.get("ended_at"), found)
        elif kind == "ship":
            for ph in rec.get("phases") or []:
                if isinstance(ph, dict) and ph.get("name") == "deploy":
                    add(ph.get("started_at"), ph.get("ended_at"), "deploy")
    return out


def gh_runs(repo: str) -> list[dict]:   # tests replace this
    done = core.run(["gh", "run", "list", "-R", repo, "--limit", "1000", "--json",
                     "createdAt,startedAt,updatedAt,conclusion"], check=False)
    if done.returncode != 0:
        return []
    try:
        data = json.loads(done.stdout or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def actions(repos: list[str], start: datetime.datetime, end: datetime.datetime) -> tuple[list[dict], list[Span]]:
    """The Actions runs of the journey repos that overlap the window, and their createdAt..updatedAt intervals (clipped)."""
    runs, intervals = [], []
    for repo in repos:
        for run in gh_runs(repo):
            a, b = parse_ts(run.get("createdAt")), parse_ts(run.get("updatedAt"))
            if a is None or b is None:
                continue
            span = _clip((a, b), start, end)
            if span:
                runs.append({**run, "repo": repo})
                intervals.append(span)
    return runs, intervals


def journey_record(records: list[dict], run_id: str) -> dict | None:
    for rec in records:
        if rec.get("run_id") == run_id and isinstance(rec.get("journey"), dict):
            return rec
    return None
