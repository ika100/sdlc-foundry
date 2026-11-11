"""`cplat platform runs journey measure` (spec 181): one recorded journey's wall clock split, tokens, questions and GitHub CI.

  cplat platform runs journey measure <session>[,<session>...] <start> <end> <owner/repo>... [--steps FILE] [--json]
                                      [--journey RUN_ID] [--records FILE]

<session> is a coordinator transcript without `.jsonl`; its subagents are `<session>/subagents/*.jsonl`. The repo sessions
come from the system ship's run records. Each minute counts once: a person, agents, then waiting (journey_timeline.split).
"""
from __future__ import annotations

import argparse
import collections
import datetime
import glob
import json
import os
import sys
from pathlib import Path

import core
import journey_sources
import journey_timeline
import runs
import runs_journey
import runs_usage
from core import PlatformError

LABELS = [("ci", "CI"), ("deploy", "deploy"), ("promotion", "promo"), ("restore", "restore"), ("cluster", "cluster"),
          ("smoke", "smoke"), ("unattributed", "unattr"), ("no_transcript", "no-tr")]


def _epoch(t: datetime.datetime) -> float:
    return t.timestamp()


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat platform runs journey measure")
    p.add_argument("session")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("repos", nargs="+")
    p.add_argument("--steps")
    p.add_argument("--json", action="store_true")
    p.add_argument("--journey")
    p.add_argument("--records")
    return p


def _subagents(session: str) -> list[str]:
    return sorted(glob.glob(glob.escape(session) + "/subagents/*.jsonl"))


def _events(path: str):
    try:
        with open(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    yield e
    except OSError:
        return


def _ts(e: dict) -> float | None:
    try:
        return journey_timeline.ts(e["timestamp"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def tokens(paths: list[str], start: float, end: float) -> dict:
    seen: set[str] = set()
    tot: collections.Counter = collections.Counter()
    by_model: collections.Counter = collections.Counter()
    for path in paths:
        for e in _events(path):
            t = _ts(e)
            if e.get("type") != "assistant" or t is None or not start <= t <= end:
                continue
            m = e.get("message") or {}
            if not m.get("id") or m["id"] in seen:
                continue
            seen.add(m["id"])
            u = m.get("usage") or {}
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
                tot[k] += u.get(k) or 0
            by_model[m.get("model", "?")] += u.get("output_tokens") or 0
    return {"api_calls": len(seen), "input": tot["input_tokens"], "cache_write": tot["cache_creation_input_tokens"],
            "cache_read": tot["cache_read_input_tokens"], "output": tot["output_tokens"], "total": sum(tot.values()),
            "output_by_model": dict(by_model)}


def questions(sessions: list[str], start: float, end: float) -> dict:
    calls = asked = 0
    for s in sessions:
        for e in _events(s + ".jsonl"):
            content = (e.get("message") or {}).get("content")
            t = _ts(e)
            if e.get("type") != "assistant" or not isinstance(content, list) or t is None or not start <= t <= end:
                continue
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                    calls += 1
                    asked += len((c.get("input") or {}).get("questions") or [None])
    return {"questions": asked, "rounds": calls}


def inputs(sessions: list[str], start: float, end: float) -> int:
    n = 0
    for s in sessions:
        last = None
        for e in _events(s + ".jsonl"):
            t = _ts(e)
            if t is None:
                continue
            content = (e.get("message") or {}).get("content")
            if e.get("type") == "assistant":
                last = t
            elif (e.get("type") == "user" and isinstance(content, str) and not e.get("isMeta") and last is not None
                  and not content.startswith("<") and start <= t <= end):
                n += 1
    return n


def github(repos: list[str], runs_found: list[dict], start: datetime.datetime, end: datetime.datetime) -> dict:
    merged = 0
    for repo in repos:
        done = core.run(["gh", "pr", "list", "-R", repo, "--state", "merged", "--limit", "500", "--json", "mergedAt"], check=False)
        try:
            data = json.loads(done.stdout or "[]") if done.returncode == 0 else []
        except ValueError:
            data = []
        for p in data if isinstance(data, list) else []:
            when = journey_sources.parse_ts(p.get("mergedAt")) if isinstance(p, dict) else None
            if when and start <= when <= end:
                merged += 1
    spans, queue = [], 0.0
    for r in runs_found:
        created = journey_sources.parse_ts(r.get("createdAt"))
        began = journey_sources.parse_ts(r.get("startedAt")) or created
        updated = journey_sources.parse_ts(r.get("updatedAt"))
        if not (created and began and updated):
            continue
        spans.append((_epoch(began), _epoch(updated)))
        queue += max(0.0, _epoch(began) - _epoch(created))
    spans.sort()
    active, cur = 0.0, None
    for a, b in spans:
        if cur and a <= cur[1]:
            cur = (cur[0], max(cur[1], b))
        else:
            active += (cur[1] - cur[0]) if cur else 0
            cur = (a, b)
    active += (cur[1] - cur[0]) if cur else 0
    return {"merged_prs": merged, "runs": len(runs_found), "failed_runs": sum(r.get("conclusion") == "failure" for r in runs_found),
            "run_min": round(sum(b - a for a, b in spans) / 60), "queue_min": round(queue / 60), "ci_active_min": round(active / 60)}


def _steps(path: str, start: float, end: float) -> list[tuple[str, float, float]]:
    rows = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            at, _, label = line.partition("\t")
            rows.append((runs_journey.parse_time(at).timestamp(), label.strip()))
    out = []
    for i, (a, label) in enumerate(rows):
        b = rows[i + 1][0] if i + 1 < len(rows) else end
        a, b = max(a, start), min(b, end)
        if b > a:
            out.append((label, a, b))
    return out


def _iso(t: float) -> str:
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _journey_split(rec: dict, threads, evidence) -> dict:
    j = rec.get("journey") or {}

    def one(item):
        a, b = journey_sources.parse_ts(item.get("started_at")), journey_sources.parse_ts(item.get("ended_at"))
        if a is None or b is None or b <= a:
            return None
        return journey_timeline.split(threads, evidence, _epoch(a), _epoch(b))

    stages = {s["id"]: v for s in j.get("stages") or [] if isinstance(s, dict) and (v := one(s))}
    parts = {str(p["part"]): v for p in j.get("parts") or [] if isinstance(p, dict) and (v := one(p))}
    total = one(j.get("total") or {})
    return {"stages": stages, "parts": parts, "total": total}


def _fmt_row(label: str, s: dict, tok: int) -> str:
    w = s["waiting"]
    cells = [s["wall_min"], s["person_min"], s["agents_min"], s["agents"]["coordinator"], s["agents"]["children"],
             *[w[k] for k, _ in LABELS]]
    return f"{label[:32]:32} " + " ".join(f"{c:>7.1f}" for c in cells) + f" {tok / 1e6:>6.1f} M"


def _print_text(result: dict) -> None:
    w, t, g, q = result["wall"], result["tokens"], result["github"], result["questions"]
    wait = ", ".join(f"{label} {w['waiting'][k]}" for k, label in LABELS)
    print(f"wall clock {w['wall_min']:.0f} min, {w['subagents']} subagents, {w['repo_sessions']} repo sessions, {w['inputs']} inputs")
    print(f"  person {w['person_min']}, agents {w['agents_min']} (coordinator {w['agents']['coordinator']} / children "
          f"{w['agents']['children']}), waiting {w['waiting_min']} ({wait})")
    print(f"tokens {t['total'] / 1e6:.1f} M in {t['api_calls']} calls: input {t['input']}, cache write {t['cache_write']},"
          f" cache read {t['cache_read']}, output {t['output']}; output by model {t['output_by_model']}")
    print(f"github {g['merged_prs']} merged PRs, {g['runs']} runs ({g['failed_runs']} failed), {g['run_min']} min run,"
          f" {g['queue_min']} min queued, CI active {g['ci_active_min']} min")
    print(f"questions {q['questions']} in {q['rounds']} rounds")
    if "steps" in result:
        names = ["wall", "person", "agents", "coord", "child", *[label for _, label in LABELS]]
        print(f"{'step':32} " + " ".join(f"{n:>7}" for n in names) + f" {'tokens':>8}")
        for r in result["steps"]:
            print(_fmt_row(r["step"], r, r["tokens"]))
        print(_fmt_row("total", result["steps_total"], result["steps_total"]["tokens"]))


def main(argv: list[str]) -> int:
    ns = _parser().parse_args(argv)
    start_dt, end_dt = runs_journey.parse_time(ns.start), runs_journey.parse_time(ns.end)
    start, end = _epoch(start_dt), _epoch(end_dt)
    sessions = ns.session.split(",")
    for s in sessions:
        if not os.path.exists(s + ".jsonl"):
            raise PlatformError(f"coordinator transcript not found: {s}.jsonl", hint="pass the path without .jsonl")
    records, followups = journey_sources.load_records(start_dt, end_dt, Path(ns.records) if ns.records else None)
    record = None
    if ns.journey:
        record = journey_sources.journey_record(records + followups, ns.journey)
        if record is None:
            raise PlatformError(f"journey record not found: {ns.journey}",
                                hint="check the run id, or pass --records FILE with the saved records")
    warnings: list[str] = []
    coord_ids = [Path(s).name for s in sessions]
    tree = journey_sources.system_tree(records, coord_ids, ns.repos, start_dt, end_dt)
    if not any(r.get("kind") == "product-ship" and journey_sources._overlaps(journey_sources._record_span(r), start_dt, end_dt)
               for r in records):
        warnings.append(journey_sources.NO_RECORD_WARNING)
    repo_sess, missing = journey_sources.repo_sessions(tree, coord_ids, runs_usage.projects_root(), (start_dt, end_dt))
    warnings += missing

    threads = []
    paths = [s + ".jsonl" for s in sessions]
    n_sub = 0
    for s in sessions:
        threads.append(journey_timeline.read_thread(s + ".jsonl", role="coordinator", main=True))
        for p in _subagents(s):
            threads.append(journey_timeline.read_thread(p, role="coordinator", main=False))
            paths.append(p)
            n_sub += 1
    no_tr = []
    for rs in repo_sess:
        if rs["path"] is None:
            if rs["span"]:
                no_tr.append((_epoch(rs["span"][0]), _epoch(rs["span"][1])))
            continue
        base = str(rs["path"])[:-len(".jsonl")]
        threads.append(journey_timeline.read_thread(rs["path"], role="child", main=False))
        for p in _subagents(base):
            threads.append(journey_timeline.read_thread(p, role="child", main=False))
            n_sub += 1
    kinds = [(_epoch(a), _epoch(b), k) for a, b, k in journey_sources.record_evidence(records, tree, ns.repos, start_dt, end_dt)]
    runs_found, action_spans = journey_sources.actions(ns.repos, start_dt, end_dt)
    evidence = journey_timeline.Evidence(no_transcript=no_tr, kinds=kinds, actions=[(_epoch(a), _epoch(b)) for a, b in action_spans])

    for line in warnings:
        print(line, file=sys.stderr)

    wall = journey_timeline.split(threads, evidence, start, end)
    result: dict = {
        "window": {"started_at": _iso(start), "ended_at": _iso(end)},
        "wall": {**wall, "subagents": n_sub, "repo_sessions": len(repo_sess), "inputs": inputs(sessions, start, end)},
        "tokens": tokens(paths, start, end), "questions": questions(sessions, start, end),
        "github": github(ns.repos, runs_found, start_dt, end_dt), "warnings": warnings}
    if ns.steps:
        rows = []
        for label, a, b in _steps(ns.steps, start, end):
            tok = tokens(paths, a, b)
            rows.append({"step": label, "started_at": _iso(a), "ended_at": _iso(b),
                         **journey_timeline.split(threads, evidence, a, b), "tokens": tok["total"], "api_calls": tok["api_calls"]})
        result["steps"] = rows
        if rows:
            first = rows[0]
            a = journey_sources.parse_ts(first["started_at"])
            tot = tokens(paths, _epoch(a), end)
            result["steps_total"] = {**journey_timeline.split(threads, evidence, _epoch(a), end), "tokens": tot["total"],
                                     "api_calls": tot["api_calls"]}
        else:
            result["steps_total"] = {**journey_timeline.split(threads, evidence, start, start), "tokens": 0, "api_calls": 0}
    message = None
    if record is not None:
        warning = runs.followup(ns.journey, "journey_split", {"split": _journey_split(record, threads, evidence)})
        result["journey"] = {"run_id": ns.journey, "written": warning is None}
        message = f"journey split written to {ns.journey}" if warning is None else warning
    if ns.json:
        print(json.dumps(result, indent=2))
    else:
        _print_text(result)
        if message:
            print(message)
    return 0
