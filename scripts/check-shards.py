#!/usr/bin/env python3
"""Spec 112: check the shard reports of one run. Every collected test must have run in exactly one shard.

Usage: check-shards.py [--timing-out PATH] REPORT...   (exit 0 OK, 1 findings, 2 unreadable input)
"""
import json
import os
import sys


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SystemExit(_bad(path, str(exc)))
    ok = (isinstance(data, dict) and isinstance(data.get("shard"), int) and isinstance(data.get("total"), int)
          and isinstance(data.get("ran"), list) and all(isinstance(x, str) for x in data["ran"])
          and (data.get("collected") is None
               or (isinstance(data["collected"], list) and all(isinstance(x, str) for x in data["collected"]))))
    if ok and "wall_s" in data:
        ok = isinstance(data["wall_s"], (int, float)) and not isinstance(data["wall_s"], bool)
    if ok and "slowest" in data:
        sl = data["slowest"]
        ok = isinstance(sl, list) and all(
            isinstance(t, dict) and isinstance(t.get("id"), str) and isinstance(t.get("s"), (int, float))
            and not isinstance(t["s"], bool) for t in sl)
    if not ok:
        raise SystemExit(_bad(path, "not a shard report"))
    return data


def _bad(path: str, why: str) -> int:
    print(f"{path}: {why}")
    print(f"{path}: {why}", file=sys.stderr)
    return 2


def _timing(reports: list[dict], timing_out: str | None) -> None:
    missing = sorted(r["shard"] for r in reports if "wall_s" not in r or "slowest" not in r)
    if len(missing) == len(reports):
        return
    if missing:
        print(f"suite time: not available: shard {missing[0]} has no timing")
        return
    walls = {r["shard"]: r["wall_s"] for r in reports}
    suite = round(sum(walls.values()), 1)
    slowest_shard = round(max(walls.values()), 1)
    tests = sorted((t for r in reports for t in r["slowest"]), key=lambda t: (-t["s"], t["id"]))[:15]
    print(f"suite time: {suite:.1f} s over {len(reports)} shards (slowest shard {slowest_shard:.1f} s)")
    print("slowest tests:")
    for t in tests:
        print(f"  {t['s']:.1f} s  {t['id']}")
    if timing_out:
        doc = {"schema": 1, "suite_s": suite, "slowest_shard_s": slowest_shard,
               "shards": {str(k): v for k, v in sorted(walls.items())}, "slowest": tests,
               "sha": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID")}
        with open(timing_out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)


def main(argv: list[str]) -> int:
    timing_out = None
    if argv[:1] == ["--timing-out"] and len(argv) >= 2:
        timing_out, argv = argv[1], argv[2:]
    if not argv:
        print("usage: check-shards.py REPORT...")
        print("usage: check-shards.py REPORT...", file=sys.stderr)
        return 2
    reports = [load(p) for p in argv]
    findings: list[str] = []
    totals = sorted({r["total"] for r in reports})
    total = reports[0]["total"]
    if len(totals) > 1:
        findings.append(f"shard reports disagree on the total ({reports[0]['total']} vs "
                        f"{next(t for t in totals if t != reports[0]['total'])})")
    by_shard: dict[int, list[dict]] = {}
    for r in reports:
        by_shard.setdefault(r["shard"], []).append(r)
    for i in range(1, total + 1):
        n = len(by_shard.get(i, []))
        if n == 0:
            findings.append(f"missing report for shard {i}/{total}")
        elif n > 1:
            findings.append(f"duplicate report for shard {i}/{total}")
    for r in reports:
        if r["collected"] is None:
            findings.append(f"shard {r['shard']}/{r['total']}: collection differed between workers")
    lists = [r["collected"] for r in reports if r["collected"] is not None]
    if any(lst != lists[0] for lst in lists):
        findings.append("shard reports disagree on the collected tests")
    collected = set(lists[0]) if lists else set()
    ran_in: dict[str, list[int]] = {}
    for r in reports:
        for nodeid in set(r["ran"]):
            ran_in.setdefault(nodeid, []).append(r["shard"])
    for nodeid in sorted(collected):
        shards = sorted(ran_in.get(nodeid, []))
        if not shards:
            findings.append(f"{nodeid}: ran in no shard")
        elif len(shards) > 1:
            findings.append(f"{nodeid}: ran in shards {', '.join(map(str, shards))}")
    for nodeid in sorted(ran_in):
        if lists and nodeid not in collected:
            findings.append(f"{nodeid}: ran in shard {ran_in[nodeid][0]} but was not collected")
    if findings:
        for line in findings:
            print(line)
        print(f"ERROR: {len(findings)} finding(s)")
        _timing(reports, timing_out)
        return 1
    print(f"OK: {len(collected)} tests ran in exactly one of {total} shards")
    _timing(reports, timing_out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
