#!/usr/bin/env python3
"""Spec 112: check the shard reports of one run. Every collected test must have run in exactly one shard.

Usage: check-shards.py REPORT...   (exit 0 OK, 1 findings, 2 unreadable input)
"""
import json
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
    if not ok:
        raise SystemExit(_bad(path, "not a shard report"))
    return data


def _bad(path: str, why: str) -> int:
    print(f"{path}: {why}")
    print(f"{path}: {why}", file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
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
        return 1
    print(f"OK: {len(collected)} tests ran in exactly one of {total} shards")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
